"""Jira 생성 작업 처리(services/jira_create.py) — SQLite 메모리 DB + Jira 모의 응답. 실제 Jira 호출 없음."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.integrations.jira.client import JiraClient
from app.models import Base, Category, Inquiry, InquiryType, IntegrationJob, SupportGroup, Ticket, User
from app.services import jira_create
from app.utils import datetime_utils

TABLES = ["users", "support_groups", "categories", "inquiry_types", "inquiries", "tickets", "integration_jobs"]
T0 = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
POST_ISSUE = ("POST", "/rest/api/3/issue")


@compiles(BigInteger, "sqlite")
def bigint_as_integer(type_, compiler, **kw):
    # SQLite 는 INTEGER PRIMARY KEY 만 자동 증가한다
    return "INTEGER"


class FakeJira:
    """Jira 모의 서버. 호출 기록(calls)을 남기고, 설정에 따라 응답을 바꾼다."""

    def __init__(self, *, existing: bool = False, post_status: int = 201, post_exc: Exception | None = None,
                 status_id: str = "10005", status_exc: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.existing = existing
        self.post_status = post_status
        self.post_exc = post_exc
        self.status_id = status_id  # 기존 이슈의 Jira 상태(기본 WIP=10005)
        self.status_exc = status_exc

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "GET" and "/rest/api/3/issue/" in request.url.path:  # 상태 조회
            if self.status_exc is not None:
                raise self.status_exc
            return httpx.Response(200, json={"fields": {"status": {"id": self.status_id, "name": "x"}}})
        if request.url.path.endswith("search/jql"):
            issues = [{"id": "20001", "key": "ITHD-77", "fields": {"customfield_10043": "RCPT-0042"}}]
            return httpx.Response(200, json={"issues": issues if self.existing else [], "isLast": True})
        if self.post_exc is not None:
            raise self.post_exc
        if self.post_status != 201:
            return httpx.Response(self.post_status, json={"errorMessages": ["거절"]})
        return httpx.Response(201, json={"id": "20002", "key": "ITHD-999"})

    @property
    def posts(self) -> int:
        return self.calls.count(POST_ISSUE)

    def client(self) -> JiraClient:
        return JiraClient("https://jira.example", "test@example.com", "dummy", transport=httpx.MockTransport(self))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES])
    with Session(engine) as session:
        session.add_all([
            Category(code="NET", name="VPN·네트워크"),
            SupportGroup(id=3, name="네트워크팀"),
            User(id=17, employee_no="EMP-TEST", name="시험 사용자", email="t@hanwha-ict.example",
                 service_role="EMPLOYEE", account_status="ACTIVE", password_hash="x"),
        ])
        session.flush()
        session.add_all([
            InquiryType(id=21, code="NET-01", category_code="NET", name="VPN 접속 불가",
                        request_kind="INCIDENT", default_urgency="P2", default_group_id=3),
            Inquiry(id=1, user_id=17, status="RECEIVED"),
        ])
        session.commit()
        yield session
    engine.dispose()


def make_ticket(db, **over) -> Ticket:
    values = dict(
        id=42, receipt_no="RCPT-0042", draft_id=55, inquiry_id=1, session_id=1,
        summary="VPN 접속 오류", target_system="VPN", symptom="인증 서버 연결 실패", occurred_at="오늘 오전",
        category_code="NET", inquiry_type_id=21, urgency="P2", urgency_reason="개인 업무 전면 중단",
        business_impact="사내 시스템 접속 불가", tried_actions="재설치", group_id=3,
        jira_sync_status="PENDING", assign_status="PENDING", work_status=None,  # 접수(TK-04)는 null로 저장한다
    )
    values.update(over)
    ticket = Ticket(**values)
    db.add(ticket)
    db.commit()
    return ticket


def make_job(db, ticket: Ticket, **over) -> IntegrationJob:
    job = jira_create.enqueue_jira_create(db, ticket)
    for key, value in over.items():
        setattr(job, key, value)
    db.commit()
    return job


def reload(db, model, pk):
    db.expire_all()
    return db.get(model, pk)


# ------------------------------------------------------------------ 등록

def test_enqueue_is_idempotent_per_receipt(db):
    ticket = make_ticket(db)
    first = jira_create.enqueue_jira_create(db, ticket)
    db.commit()
    second = jira_create.enqueue_jira_create(db, ticket)
    assert first.id == second.id
    assert (first.job_type, first.status, first.attempts) == ("JIRA_CREATE", "PENDING", 0)
    assert first.idempotency_key == "create:RCPT-0042"


# ------------------------------------------------------------------ 성공 경로

def test_success_creates_issue_and_saves_key(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira()

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.jira_key) == ("CREATED", "ITHD-999")
    ticket, job = reload(db, Ticket, 42), reload(db, IntegrationJob, job.id)
    assert (ticket.jira_key, ticket.jira_sync_status) == ("ITHD-999", "SYNCED")
    assert ticket.work_status == "RDY"  # Jira 생성 직후 RDY (docs/06)
    assert (job.status, job.attempts, job.last_error, job.next_retry_at) == ("DONE", 1, None, None)
    assert jira.posts == 1


def test_issue_already_in_jira_is_linked_without_creating(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(existing=True)

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.jira_key) == ("LINKED", "ITHD-77")
    row = reload(db, Ticket, 42)
    assert row.jira_key == "ITHD-77"
    assert row.work_status == "WIP"  # 기존 이슈는 RDY로 가정하지 않고 Jira 현재 상태를 따른다
    assert jira.posts == 0


def test_linked_issue_keeps_work_status_that_is_already_set(db):
    ticket = make_ticket(db, work_status="FIN")
    job = make_job(db, ticket)
    jira = FakeJira(existing=True)

    jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert reload(db, Ticket, 42).work_status == "FIN"  # 상태 동기화가 정한 값은 덮어쓰지 않는다
    assert ("GET", "/rest/api/3/issue/ITHD-77") not in jira.calls


def test_status_lookup_failure_retries_without_saving_key(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(existing=True, status_exc=httpx.ReadTimeout("느림"))

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert result.outcome in ("RETRY_SCHEDULED", "VERIFY_SCHEDULED")
    row = reload(db, Ticket, 42)
    assert (row.jira_key, row.work_status) == (None, None)  # 반쪽 저장 없이 다음 실행에서 다시 연결
    assert reload(db, IntegrationJob, job.id).status == "PENDING"


def test_ticket_with_saved_key_makes_no_jira_call(db):
    ticket = make_ticket(db, jira_key="ITHD-5", jira_sync_status="SYNCED", work_status="RDY")
    job = make_job(db, ticket)
    jira = FakeJira()

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.jira_key) == ("SAVED", "ITHD-5")
    assert reload(db, IntegrationJob, job.id).status == "DONE"
    assert jira.calls == []


def test_saved_key_with_empty_work_status_is_filled_from_jira(db):
    ticket = make_ticket(db, jira_key="ITHD-5", jira_sync_status="SYNCED")
    job = make_job(db, ticket)
    jira = FakeJira(status_id="10004")  # RDY

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert result.outcome == "SAVED"
    assert reload(db, Ticket, 42).work_status == "RDY"


# ------------------------------------------------------------------ 결과 불명확 → 찾기만

def test_timeout_on_create_goes_verifying_then_lookup_links_it(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(post_exc=httpx.ReadTimeout("느림"))

    first = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert first.outcome == "VERIFY_SCHEDULED"
    ticket_row, job_row = reload(db, Ticket, 42), reload(db, IntegrationJob, job.id)
    assert ticket_row.jira_sync_status == "VERIFYING"
    assert (job_row.status, job_row.last_error) == ("PENDING", "result_unknown")
    assert datetime_utils.as_utc(job_row.next_retry_at) == T0 + timedelta(seconds=60)
    assert jira.posts == 1

    # 아직 실행 시각 전이면 건드리지 않는다
    assert jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0 + timedelta(seconds=30)).outcome == "SKIPPED"

    # Jira에 이슈가 실제로 만들어져 있었다 → 찾아서 연결, 다시 만들지 않는다
    jira.existing = True
    second = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0 + timedelta(seconds=61))
    assert (second.outcome, second.jira_key) == ("LINKED", "ITHD-77")
    assert reload(db, Ticket, 42).jira_sync_status == "SYNCED"
    assert jira.posts == 1


def test_verifying_never_creates_and_ends_in_admin(db):
    ticket = make_ticket(db, jira_sync_status="VERIFYING")
    job = make_job(db, ticket)
    jira = FakeJira()  # 이슈가 없다

    outcomes = [
        jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0 + timedelta(hours=n)).outcome
        for n in range(4)
    ]

    assert outcomes == ["VERIFY_SCHEDULED", "VERIFY_SCHEDULED", "VERIFY_SCHEDULED", "NEEDS_ADMIN"]
    assert jira.posts == 0
    assert reload(db, Ticket, 42).jira_sync_status == "NEEDS_ADMIN"
    assert reload(db, IntegrationJob, job.id).status == "NEEDS_ADMIN"


# ------------------------------------------------------------------ 재시도·관리자 확인

def test_retryable_error_is_rescheduled_then_escalates_after_max_attempts(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(post_status=429)

    first = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)
    assert first.outcome == "RETRY_SCHEDULED"
    row = reload(db, IntegrationJob, job.id)
    assert (row.status, row.attempts, row.last_error) == ("PENDING", 1, "rate_limited (HTTP 429)")
    assert datetime_utils.as_utc(row.next_retry_at) == T0 + timedelta(seconds=60)
    assert reload(db, Ticket, 42).jira_sync_status == "PENDING"  # 재시도 오류는 접수 상태를 바꾸지 않는다

    second = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0 + timedelta(hours=1))
    third = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0 + timedelta(hours=2))
    assert (second.outcome, third.outcome) == ("RETRY_SCHEDULED", "NEEDS_ADMIN")
    assert reload(db, Ticket, 42).jira_sync_status == "NEEDS_ADMIN"
    assert reload(db, IntegrationJob, job.id).attempts == 3


def test_non_retryable_error_goes_to_admin_at_once(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(post_status=401)

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "auth")
    assert reload(db, Ticket, 42).jira_sync_status == "NEEDS_ADMIN"
    assert reload(db, IntegrationJob, job.id).last_error == "auth (HTTP 401)"
    assert jira.posts == 1  # 한 번만 시도


def test_missing_required_data_goes_to_admin_without_calling_jira(db):
    ticket = make_ticket(db, group_id=None)  # 담당 그룹 없음
    job = make_job(db, ticket)
    jira = FakeJira()

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert result.outcome == "NEEDS_ADMIN"
    assert "groupId" in result.reason
    assert jira.calls == []


def test_jira_key_already_used_by_another_ticket_goes_to_admin(db):
    make_ticket(db, id=7, receipt_no="RCPT-0007", draft_id=56, jira_key="ITHD-999", jira_sync_status="SYNCED")
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira()  # 새 이슈 키가 ITHD-999 로 돌아와 충돌한다

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "jira_key_conflict")
    ticket = reload(db, Ticket, 42)
    assert (ticket.jira_key, ticket.jira_sync_status) == (None, "NEEDS_ADMIN")


# ------------------------------------------------------------------ 선점·실행 대상·복구

def test_job_cannot_be_claimed_twice(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket, status="RUNNING")
    jira = FakeJira()

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert (result.outcome, result.reason) == ("SKIPPED", "not_claimable")
    assert jira.calls == []
    assert reload(db, IntegrationJob, job.id).attempts == 0


def test_run_due_runs_only_due_pending_jobs(db):
    due = make_job(db, make_ticket(db))
    make_job(db, make_ticket(db, id=43, receipt_no="RCPT-0043", draft_id=56),
             next_retry_at=T0 + timedelta(minutes=10))
    make_job(db, make_ticket(db, id=44, receipt_no="RCPT-0044", draft_id=57), status="DONE")
    jira = FakeJira()

    results = jira_create.run_due_jira_create_jobs(db, jira.client(), now=T0)

    assert [r.job_id for r in results] == [due.id]
    assert jira.posts == 1


def test_stale_running_job_is_requeued_as_verifying(db):
    ticket = make_ticket(db)
    job = make_job(db, ticket, status="RUNNING", attempts=1, updated_at=T0 - timedelta(minutes=10))

    assert jira_create.requeue_stale_running_jobs(db, now=T0) == 1

    assert reload(db, IntegrationJob, job.id).status == "PENDING"
    assert reload(db, Ticket, 42).jira_sync_status == "VERIFYING"

    # 방금 시작한 작업은 건드리지 않는다
    fresh = make_job(db, make_ticket(db, id=43, receipt_no="RCPT-0043", draft_id=56),
                     status="RUNNING", updated_at=T0 - timedelta(minutes=1))
    assert jira_create.requeue_stale_running_jobs(db, now=T0) == 0
    assert reload(db, IntegrationJob, fresh.id).status == "RUNNING"
