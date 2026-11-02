"""JIRA_ASSIGN 실행. 모의 HTTP·임시 SQLite만 사용한다."""
import json
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.attributes import flag_modified

from app.integrations.jira.client import JiraClient
from app.models import (AssignmentLog, Base, Inquiry, IntegrationJob, MemberSkill,
                        SupportGroup, SupportGroupMember, Ticket, User)
from app.services import jira_assign as service
from app.services.assignment import reserve_assignment
from test_jira_create_service import T0, db, make_ticket, reload  # noqa: F401

NOW = T0 + timedelta(seconds=30)
ACCOUNT = "test-account-18"


class FakeAssignment:
    def __init__(self, account=None, status="10004"):
        self.account, self.status = account, status
        self.calls, self.sent = [], []
        self.reads = 0
        self.read_errors = {}
        self.write_status = 204
        self.write_error = None
        self.apply_before_error = True
        self.after_write = None
        self.keep_unassigned = False
        self.omit_assignee = False

    @property
    def puts(self):
        return len(self.sent)

    def client(self):
        return JiraClient("https://jira.example", "bot@example.com", "dummy",
                          transport=httpx.MockTransport(self))

    def __call__(self, req):
        self.calls.append((req.method, req.url.path))
        if req.method == "GET":
            self.reads += 1
            error = self.read_errors.get(self.reads)
            if isinstance(error, Exception):
                raise error
            if error:
                return httpx.Response(error, json={"errorMessages": ["read failed"]})
            who = {"accountId": self.account} if self.account else None
            fields = {"status": {"id": self.status}, "assignee": who}
            if self.omit_assignee:
                fields.pop("assignee")
            return httpx.Response(200, json={"fields": fields})
        assert req.method == "PUT" and req.url.path.endswith("/assignee")
        body = json.loads(req.content)
        self.sent.append(body)
        if self.write_error and not self.apply_before_error:
            raise self.write_error
        if self.write_status != 204:
            return httpx.Response(self.write_status, json={"errorMessages": ["write failed"]})
        if not self.keep_unassigned:
            self.account = body["accountId"]
        if self.after_write:
            self.after_write()
        if self.write_error:
            raise self.write_error
        return httpx.Response(204)


@pytest.fixture
def assign_db(db):
    for name in ("support_group_members", "member_skills", "assignment_logs"):
        Base.metadata.tables[name].create(db.bind, checkfirst=True)
    db.add_all([
        User(id=18, employee_no="EMP-AGENT", name="시험 담당자", email="a@example.com",
             service_role="AGENT", account_status="ACTIVE", password_hash="x"),
        User(id=19, employee_no="EMP-ADMIN", name="시험 관리자", email="admin@example.com",
             service_role="ADMIN", account_status="ACTIVE", password_hash="x"),
    ])
    db.flush()
    db.add_all([
        SupportGroupMember(group_id=3, user_id=18, member_role="AGENT", assignable=True,
                           jira_account_id=ACCOUNT),
        MemberSkill(user_id=18, inquiry_type_id=21),
    ])
    db.commit()
    return db


def make_assignment(db, **over):
    values = dict(jira_key="ITHD-42", jira_sync_status="SYNCED", work_status="RDY",
                  assignee_id=18, assignment_revision=1)
    values.update(over)
    ticket = make_ticket(db, **values)
    p = {"ticketId": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": ticket.jira_key,
         "groupId": 3, "assigneeId": 18, "jiraAccountId": ACCOUNT, "assignmentRevision": 1,
         "requestedBy": 19, "requestedAt": T0.isoformat()}
    db.add(AssignmentLog(ticket_id=ticket.id, event="ASSIGN", group_id=3, assignee_id=18,
                         actor_id=19, reason="시험 배정"))
    job = service.enqueue_jira_assign(db, ticket, p)
    db.commit()
    return ticket, job


@pytest.mark.parametrize("existing,puts", [(None, 1), (ACCOUNT, 0)])
def test_assign_or_confirm_existing_target_without_duplicate_history(assign_db, existing, puts):
    db = assign_db
    ticket, job = make_assignment(db)
    payload = deepcopy(job.payload)
    jira = FakeAssignment(existing)
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW)
    assert result.outcome == "ASSIGNED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assign_status, ticket.jira_sync_status, ticket.work_status) == (18, "ASSIGNED", "SYNCED", "RDY")
    assert db.get(Inquiry, ticket.inquiry_id).status == "HANDED_OFF"
    assert reload(db, IntegrationJob, job.id).payload == payload
    assert reload(db, IntegrationJob, job.id).status == "DONE"
    assert jira.puts == puts
    assert len(db.scalars(select(AssignmentLog)).all()) == 1
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert jira.puts == puts


def test_new_shared_reservation_supports_system_actor_and_caller_commit(assign_db):
    db = assign_db
    ticket = make_ticket(db, jira_key="ITHD-42", jira_sync_status="SYNCED", work_status="RDY")
    reservation = reserve_assignment(db, ticket, 3, reason="최초 자동배정", actor_id=None, now=T0)
    assert reservation.job.payload["requestedBy"] is None
    db.commit()
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), reservation.job.id, now=NOW).outcome == "ASSIGNED"
    assert reload(db, Ticket, ticket.id).assign_status == "ASSIGNED"
    logs = db.scalars(select(AssignmentLog)).all()
    assert len(logs) == 1 and logs[0].actor_id is None


def test_new_shared_manual_reservation_accepts_manager_as_target(assign_db):
    db = assign_db
    db.get(SupportGroupMember, (3, 18)).member_role = "MANAGER"
    db.commit()
    ticket = make_ticket(db, jira_key="ITHD-42", jira_sync_status="SYNCED", work_status="RDY")
    reservation = reserve_assignment(db, ticket, 3, reason="수동 지정", actor_id=19, assignee_id=18, now=T0)
    db.commit()
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), reservation.job.id, now=NOW).outcome == "ASSIGNED"


def test_different_existing_account_is_not_overwritten_and_reservation_is_released(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment("another-account")
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW)
    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "assignment_source_unconfirmed")
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assign_status) == (None, "NEEDS_ADMIN")
    assert jira.account == "another-account" and jira.puts == 0
    assert db.get(Inquiry, ticket.inquiry_id).status == "RECEIVED"
    assert len(db.scalars(select(AssignmentLog).where(AssignmentLog.event == "FAIL")).all()) == 1


def test_old_revision_does_not_touch_latest_reservation_or_call_jira(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    ticket.assignment_revision = 2
    db.commit()
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "STALE"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assign_status, ticket.assignment_revision) == (18, "PENDING", 2)
    assert reload(db, IntegrationJob, job.id).status == "DONE"
    assert jira.calls == []
    assert len(db.scalars(select(AssignmentLog)).all()) == 1


@pytest.mark.parametrize("change", ["user_inactive", "role", "group_inactive", "member_inactive", "unassignable", "skill", "account"])
def test_current_eligibility_is_checked_before_external_call(assign_db, change):
    db = assign_db
    ticket, job = make_assignment(db)
    user, member = db.get(User, 18), db.get(SupportGroupMember, (3, 18))
    if change == "user_inactive": user.account_status = "INACTIVE"
    elif change == "role": user.service_role = "EMPLOYEE"
    elif change == "group_inactive": db.get(SupportGroup, 3).is_active = False
    elif change == "member_inactive": member.is_active = False
    elif change == "unassignable": member.assignable = False
    elif change == "skill": db.delete(db.get(MemberSkill, (18, 21)))
    elif change == "account": member.jira_account_id = "changed-account"
    db.commit()
    jira = FakeAssignment()
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW)
    assert result.outcome == "NEEDS_ADMIN"
    assert reload(db, Ticket, ticket.id).assignee_id is None
    assert jira.calls == []


@pytest.mark.parametrize("status", ["10007", "unknown"])
def test_jira_closed_or_unmapped_status_is_not_assigned(assign_db, status):
    db = assign_db
    _, job = make_assignment(db)
    jira = FakeAssignment(status=status)
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    assert jira.puts == 0


@pytest.mark.parametrize("applied", [True, False])
def test_timeout_recovers_by_query_only_without_second_put(assign_db, applied):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment()
    jira.write_error, jira.apply_before_error = httpx.ReadTimeout("slow"), applied
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert reload(db, Ticket, ticket.id).assignee_id == 18
    jira.write_error = None
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2))
    assert result.outcome == ("ASSIGNED" if applied else "VERIFY_SCHEDULED")
    assert jira.puts == 1
    if not applied:
        for n in (4, 6):
            result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=n))
        assert result.outcome == "NEEDS_ADMIN"
        assert reload(db, Ticket, ticket.id).assignee_id == 18  # 결과 불명확은 확실한 실패처럼 해제하지 않음
        assert jira.puts == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), 429])
def test_read_after_write_failure_preserves_verify_only(assign_db, error):
    db = assign_db
    _, job = make_assignment(db)
    jira = FakeAssignment()
    jira.read_errors[2] = error
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert reload(db, IntegrationJob, job.id).last_error.startswith(service.VERIFY_ONLY)
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "ASSIGNED"
    assert jira.puts == 1


def test_initial_read_timeout_retries_before_any_write(assign_db):
    db = assign_db
    _, job = make_assignment(db)
    jira = FakeAssignment()
    jira.read_errors[1] = httpx.ReadTimeout("slow")
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "RETRY_SCHEDULED"
    assert jira.puts == 0
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "ASSIGNED"
    assert jira.puts == 1


@pytest.mark.parametrize("status,expected", [(400, "NEEDS_ADMIN"), (401, "NEEDS_ADMIN"),
                                          (429, "RETRY_SCHEDULED"), (503, "VERIFY_SCHEDULED")])
def test_write_errors_distinguish_rejection_from_uncertain_result(assign_db, status, expected):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment()
    jira.write_status = status
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW)
    assert result.outcome == expected
    ticket = reload(db, Ticket, ticket.id)
    assert ticket.jira_sync_status == "SYNCED"
    assert ticket.assignee_id == (None if expected == "NEEDS_ADMIN" else 18)


def test_revision_changed_during_http_does_not_save_old_result(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment()
    def revise():
        ticket.assignment_revision = 2
        db.commit()
    jira.after_write = revise
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "STALE"
    assert reload(db, Ticket, ticket.id).assign_status == "PENDING"
    assert len(db.scalars(select(AssignmentLog)).all()) == 1


def test_new_claim_owner_cannot_be_overwritten(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment()
    def takeover():
        db.get(IntegrationJob, job.id).attempts += 1
        db.commit()
    jira.after_write = takeover
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert reload(db, Ticket, ticket.id).assign_status == "PENDING"


def test_db_save_failure_after_assign_is_recovered_without_reassignment(assign_db, monkeypatch):
    db = assign_db
    ticket, job = make_assignment(db)
    ticket_id, job_id = ticket.id, job.id
    jira = FakeAssignment()
    commit, calls = db.commit, 0
    def fail_final_commit():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OperationalError("COMMIT", {}, Exception("DB unavailable"))
        commit()
    monkeypatch.setattr(db, "commit", fail_final_commit)
    with pytest.raises(OperationalError):
        service.run_jira_assign_job(db, jira.client(), job_id, now=NOW)
    db.rollback()
    monkeypatch.setattr(db, "commit", commit)
    assert reload(db, Ticket, ticket_id).assign_status == "PENDING"
    later = NOW + timedelta(minutes=10)
    assert service.requeue_stale_assign_jobs(db, now=later) == 1
    assert service.run_jira_assign_job(db, jira.client(), job_id, now=later).outcome == "ASSIGNED"
    assert jira.puts == 1


def test_recovery_is_assignment_only_and_does_not_touch_create_sync(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    job.status, job.updated_at = "RUNNING", T0 - timedelta(minutes=10)
    other = IntegrationJob(ticket_id=ticket.id, job_type="JIRA_CREATE", status="RUNNING", attempts=0,
                           idempotency_key="create:other", payload={}, updated_at=T0 - timedelta(minutes=10))
    db.add(other)
    db.commit()
    assert service.requeue_stale_assign_jobs(db, now=NOW) == 1
    assert reload(db, IntegrationJob, other.id).status == "RUNNING"
    assert reload(db, Ticket, ticket.id).jira_sync_status == "SYNCED"
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert jira.puts == 0


def test_due_runner_respects_next_retry_and_limit(assign_db):
    db = assign_db
    _, job = make_assignment(db)
    job.next_retry_at = NOW + timedelta(minutes=5)
    db.commit()
    jira = FakeAssignment()
    assert service.run_due_jira_assign_jobs(db, jira.client(), now=NOW) == []
    assert service.run_due_jira_assign_jobs(db, jira.client(), now=NOW + timedelta(minutes=6), limit=0) == []
    results = service.run_due_jira_assign_jobs(db, jira.client(), now=NOW + timedelta(minutes=6))
    assert [r.outcome for r in results] == ["ASSIGNED"]


@pytest.mark.parametrize("field,value", [("ticketId", 999), ("jiraKey", "ITHD-999"),
                                        ("jiraAccountId", " "), ("assignmentRevision", True),
                                        ("requestedBy", []), ("requestedAt", "bad")])
def test_invalid_payload_does_not_call_jira(assign_db, field, value):
    db = assign_db
    _, job = make_assignment(db)
    job.payload = {**job.payload, field: value}
    flag_modified(job, "payload")  # JSON의 true와 숫자 1도 구분해 DB에 저장
    db.commit()
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    assert jira.calls == []


def test_definite_rate_limit_can_retry_after_rechecking_current_assignee(assign_db):
    db = assign_db
    _, job = make_assignment(db)
    jira = FakeAssignment()
    jira.write_status = 429
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "RETRY_SCHEDULED"
    assert not reload(db, IntegrationJob, job.id).last_error.startswith(service.VERIFY_ONLY)
    jira.write_status = 204
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "ASSIGNED"
    assert jira.puts == 2  # 첫 요청은 거절됨


def test_missing_assignee_field_is_not_interpreted_as_unassigned(assign_db):
    db = assign_db
    _, job = make_assignment(db)
    jira = FakeAssignment("another-account")
    jira.omit_assignee = True
    result = service.run_jira_assign_job(db, jira.client(), job.id, now=NOW)
    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "incomplete_jira_assignment")
    assert jira.puts == 0


def test_db_cls_is_rejected_before_jira_access(assign_db):
    db = assign_db
    _, job = make_assignment(db, work_status="CLS")
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    assert jira.calls == []


def test_fin_assignment_preserves_work_status_and_result(assign_db):
    db = assign_db
    ticket, job = make_assignment(db, work_status="FIN", resolution_note="처리 결과", finished_at=T0)
    jira = FakeAssignment(status="10006")
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "ASSIGNED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.resolution_note) == ("FIN", "처리 결과")
    assert ticket.finished_at is not None


def test_cls_during_put_does_not_confirm_assignment(assign_db):
    db = assign_db
    ticket, job = make_assignment(db)
    jira = FakeAssignment()
    jira.after_write = lambda: setattr(jira, "status", "10007")
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assign_status, ticket.assignee_id, ticket.work_status) == ("NEEDS_ADMIN", 18, "RDY")
    assert db.get(Inquiry, ticket.inquiry_id).status == "RECEIVED"


def test_foreign_job_type_is_not_claimed(assign_db):
    db = assign_db
    ticket = make_ticket(db)
    job = IntegrationJob(ticket_id=ticket.id, job_type="JIRA_TRANSITION", status="PENDING", attempts=0,
                         idempotency_key="transition:other", payload={})
    db.add(job)
    db.commit()
    jira = FakeAssignment()
    assert service.run_jira_assign_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert reload(db, IntegrationJob, job.id).attempts == 0
    assert jira.calls == []
