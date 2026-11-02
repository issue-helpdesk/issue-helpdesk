"""실제 Jira·운영 DB를 쓰지 않는 상태 변경 실행/처리 결과 수정 회귀시험."""
import json
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.integrations.jira.client import JiraClient
from app.integrations.jira.mapper import _adf
from app.models import Base, Inquiry, IntegrationJob, Ticket, TicketStatusHistory, User
from app.services import jira_transition as service
from app.utils import datetime_utils
from test_jira_create_service import T0, db, make_ticket, reload  # noqa: F401

EVENT_AT = T0 + timedelta(seconds=10)
NOW = T0 + timedelta(seconds=30)
IDS = {"RDY": "10004", "WIP": "10005", "FIN": "10006", "CLS": "10007"}


class Workflow:
    def __init__(self, status="RDY", note=""):
        self.status, self.note = status, note
        self.calls, self.histories = [], []
        self.issue_reads = 0
        self.read_errors = {}
        self.write_error = None
        self.fail_before_write = False
        self.write_status = 204
        self.keep_history = True
        self.after_write = None
        self.after_status = None
        self.history_error = None

    @property
    def transitions(self):
        return sum(method == "POST" for method, _ in self.calls)

    @property
    def edits(self):
        return sum(method == "PUT" for method, _ in self.calls)

    def client(self):
        return JiraClient("https://jira.example", "bot@example.com", "dummy",
                          transport=httpx.MockTransport(self))

    def __call__(self, req):
        self.calls.append((req.method, req.url.path))
        if req.url.path.endswith("/changelog"):
            if self.history_error:
                raise self.history_error
            start = int(req.url.params.get("startAt", 0))
            return httpx.Response(200, json={"values": self.histories[start:start + 1],
                                             "total": len(self.histories), "isLast": start + 1 >= len(self.histories)})
        if req.method == "GET" and req.url.path.endswith("/transitions"):
            target = {"RDY": "WIP", "WIP": "FIN", "FIN": "CLS"}.get(self.status)
            return httpx.Response(200, json={"transitions": [] if target is None else [
                {"id": IDS[target], "to": {"id": IDS[target]}}]})
        if req.method == "GET":
            self.issue_reads += 1
            error = self.read_errors.get(self.issue_reads)
            if isinstance(error, Exception):
                raise error
            if error:
                return httpx.Response(error, json={"errorMessages": ["read failed"]})
            return httpx.Response(200, json={"fields": {"status": {"id": IDS[self.status]},
                                                         "customfield_10069": _adf(self.note)}})
        if self.fail_before_write and self.write_error:
            raise self.write_error
        if self.write_status != 204:
            return httpx.Response(self.write_status, json={"errorMessages": ["write failed"]})
        body = json.loads(req.content)
        fields = body.get("fields", {})
        if "customfield_10069" in fields:
            from app.integrations.jira.mapper import adf_to_text
            self.note = "\n".join(adf_to_text(p) for p in fields["customfield_10069"]["content"])
        if req.method == "POST":
            source = self.status
            self.status = next(k for k, value in IDS.items() if value == body["transition"]["id"])
            if self.keep_history:
                self.histories.append({"id": str(len(self.histories) + 1), "created": EVENT_AT.isoformat(),
                                       "items": [{"field": "status", "from": IDS[source], "to": IDS[self.status]}]})
        if self.after_status:
            self.status = self.after_status
        if self.after_write:
            self.after_write()
        if self.write_error:
            raise self.write_error
        return httpx.Response(204)


@pytest.fixture
def transition_db(db):
    Base.metadata.tables["ticket_status_history"].create(db.bind)
    db.add(User(id=18, employee_no="EMP-STAFF", name="시험 담당자", email="s@example.com",
                service_role="AGENT", account_status="ACTIVE", password_hash="x"))
    db.commit()
    return db


def make_transition(db, source="RDY", target="WIP", note=None):
    ticket = make_ticket(db, jira_key="ITHD-42", jira_sync_status="SYNCED", work_status=source,
                         resolution_note="기존 결과" if source == "FIN" else None,
                         finished_at=T0 - timedelta(days=1) if source == "FIN" else None)
    ticket.requested_work_status, ticket.transition_status = target, "PENDING"
    if target == "CLS":
        ticket.resolution_confirmed_at = T0
    payload = {"ticketId": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": ticket.jira_key,
               "fromStatus": source, "toStatus": target, "resolutionNote": note, "reason": None,
               "requestedBy": 17 if target == "CLS" else 18, "requestedAt": T0.isoformat(),
               "resolutionConfirmedAt": T0.isoformat() if target == "CLS" else None}
    job = service.enqueue_jira_transition(db, ticket, payload)
    db.commit()
    return ticket, job


@pytest.mark.parametrize("source,target,note", [("RDY", "WIP", None), ("WIP", "FIN", "새 처리 결과"),
                                               ("FIN", "CLS", None)])
def test_basic_transition_confirms_jira_state_result_and_actual_history_time(transition_db, source, target, note):
    db = transition_db
    ticket, job = make_transition(db, source, target, note)
    payload = deepcopy(job.payload)
    jira = Workflow(source, "기존 결과" if source == "FIN" else "")

    result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW)

    assert result.outcome == "CONFIRMED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.transition_status, ticket.requested_work_status) == (target, "IDLE", None)
    assert ticket.jira_sync_status == "SYNCED"
    assert datetime_utils.as_utc(ticket.work_status_confirmed_at) == NOW
    history = db.scalar(select(TicketStatusHistory))
    assert (history.from_status, history.to_status, history.source) == (source, target, "ITSSUE")
    assert datetime_utils.as_utc(history.changed_at) == EVENT_AT
    assert reload(db, IntegrationJob, job.id).payload == payload
    assert reload(db, IntegrationJob, job.id).status == "DONE"
    if target == "FIN":
        assert ticket.resolution_note == note
        assert datetime_utils.as_utc(ticket.finished_at) == EVENT_AT != NOW
    if target == "CLS":
        assert datetime_utils.as_utc(ticket.closed_at) == T0
        assert datetime_utils.as_utc(ticket.resolution_confirmed_at) == T0
        inquiry = db.get(Inquiry, ticket.inquiry_id)
        assert inquiry.resolution_result == "RESOLVED"
        assert datetime_utils.as_utc(inquiry.closed_at) == T0
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert len(db.scalars(select(TicketStatusHistory)).all()) == 1
    assert jira.transitions == 1


@pytest.mark.parametrize("status", ["WIP", "FIN"])
def test_note_only_preserves_state_finished_time_and_does_not_add_state_history(transition_db, status):
    db = transition_db
    ticket, job = make_transition(db, status, None, "수정한 결과")
    old_finished = ticket.finished_at
    jira = Workflow(status, "기존 결과")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "CONFIRMED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.resolution_note) == (status, "수정한 결과")
    assert ticket.finished_at == old_finished
    assert db.scalar(select(TicketStatusHistory)) is None
    assert (jira.transitions, jira.edits) == (0, 1)


def test_fin_can_use_existing_saved_note_when_request_has_no_new_note(transition_db):
    db = transition_db
    ticket, job = make_transition(db, "WIP", "FIN")
    ticket.resolution_note = "저장된 결과"
    db.commit()
    jira = Workflow("WIP")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "CONFIRMED"
    assert jira.note == "저장된 결과"


@pytest.mark.parametrize("field,value", [("resolutionConfirmedAt", None), ("requestedBy", 18)])
def test_cls_requires_requester_confirmation_before_any_jira_call(transition_db, field, value):
    db = transition_db
    ticket, job = make_transition(db, "FIN", "CLS")
    job.payload = {**job.payload, field: value}
    db.commit()
    jira = Workflow("FIN", "기존 결과")
    result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW)
    assert result.outcome == "NEEDS_ADMIN"
    assert reload(db, Ticket, ticket.id).work_status == "FIN"
    assert jira.calls == []


def test_reopen_is_deferred_without_claim_or_mutation(transition_db):
    db = transition_db
    ticket, job = make_transition(db, "FIN", "WIP")
    jira = Workflow("FIN", "기존 결과")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "DEFERRED"
    assert (reload(db, IntegrationJob, job.id).status, job.attempts) == ("PENDING", 0)
    assert reload(db, Ticket, ticket.id).resolution_note == "기존 결과"
    assert jira.calls == []


def test_external_conflicting_status_is_not_overwritten(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow("CLS", "외부 결과")
    result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW)
    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "transition_conflict")
    assert reload(db, Ticket, ticket.id).work_status == "RDY"
    assert (jira.transitions, jira.edits) == (0, 0)


@pytest.mark.parametrize("applied", [True, False])
def test_transition_timeout_uses_query_only_and_never_posts_twice(transition_db, applied):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow()
    jira.write_error = httpx.ReadTimeout("slow")
    jira.fail_before_write = not applied
    first = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW)
    assert first.outcome == "VERIFY_SCHEDULED"
    assert reload(db, Ticket, ticket.id).work_status == "RDY"
    jira.write_error = None
    result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2))
    assert result.outcome == ("CONFIRMED" if applied else "VERIFY_SCHEDULED")
    assert jira.transitions == 1
    if not applied:
        for n in (3, 4):
            result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=n * 2))
        assert result.outcome == "NEEDS_ADMIN"
        assert jira.transitions == 1


def test_query_rate_limit_preserves_verify_only_marker(transition_db):
    db = transition_db
    _, job = make_transition(db)
    job.last_error = service.VERIFY_ONLY + "write_started"
    db.commit()
    jira = Workflow()
    jira.read_errors[1] = 429
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert reload(db, IntegrationJob, job.id).last_error.startswith(service.VERIFY_ONLY)
    service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2))
    assert jira.transitions == 0


def test_read_failure_before_writing_is_retryable_without_changing_confirmed_ticket(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow()
    jira.read_errors[1] = httpx.ReadTimeout("slow")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "RETRY_SCHEDULED"
    assert reload(db, Ticket, ticket.id).work_status == "RDY"
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "CONFIRMED"
    assert jira.transitions == 1


def test_post_write_read_failure_recovers_by_query(transition_db):
    db = transition_db
    _, job = make_transition(db)
    jira = Workflow()
    jira.read_errors[3] = httpx.ReadTimeout("slow")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "CONFIRMED"
    assert jira.transitions == 1


def test_post_write_read_rate_limit_is_query_only(transition_db):
    db = transition_db
    _, job = make_transition(db)
    jira = Workflow()
    jira.read_errors[3] = 429
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert reload(db, IntegrationJob, job.id).last_error.startswith(service.VERIFY_ONLY)
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "CONFIRMED"
    assert jira.transitions == 1


def test_no_history_does_not_fabricate_finish_time(transition_db):
    db = transition_db
    ticket, job = make_transition(db, "WIP", "FIN", "새 결과")
    jira = Workflow("WIP")
    jira.keep_history = False
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.finished_at, ticket.resolution_note) == ("WIP", None, None)
    assert ticket.transition_status == "PENDING"


def test_existing_log_for_same_jira_change_is_not_duplicated(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow("WIP")
    jira.histories = [{"id": "old", "created": EVENT_AT.isoformat(),
                       "items": [{"field": "status", "from": IDS["RDY"], "to": IDS["WIP"]}]}]
    db.add(TicketStatusHistory(ticket_id=ticket.id, from_status="RDY", to_status="WIP", source="JIRA", changed_at=EVENT_AT))
    db.commit()
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "CONFIRMED"
    assert len(db.scalars(select(TicketStatusHistory)).all()) == 1
    assert jira.transitions == 0


def test_expired_claim_cannot_save_over_new_owner(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow()
    def takeover():
        db.get(IntegrationJob, job.id).attempts += 1
        db.commit()
    jira.after_write = takeover
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert reload(db, Ticket, ticket.id).work_status == "RDY"
    assert db.scalar(select(TicketStatusHistory)) is None


def test_stale_recovery_is_transition_only_and_query_only(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    job.status, job.updated_at = "RUNNING", T0 - timedelta(minutes=10)
    other = IntegrationJob(ticket_id=ticket.id, job_type="JIRA_CREATE", status="RUNNING", attempts=0,
                           idempotency_key="other", payload={}, updated_at=T0 - timedelta(minutes=10))
    db.add(other)
    db.commit()
    assert service.requeue_stale_transition_jobs(db, now=NOW) == 1
    assert reload(db, IntegrationJob, other.id).status == "RUNNING"
    assert reload(db, Ticket, ticket.id).jira_sync_status == "SYNCED"
    jira = Workflow()
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    assert jira.transitions == 0


def test_due_runner_respects_schedule_and_limit(transition_db):
    db = transition_db
    _, job = make_transition(db)
    job.next_retry_at = NOW + timedelta(minutes=5)
    db.commit()
    jira = Workflow()
    assert service.run_due_jira_transition_jobs(db, jira.client(), now=NOW) == []
    assert service.run_due_jira_transition_jobs(db, jira.client(), now=NOW + timedelta(minutes=6), limit=0) == []
    result = service.run_due_jira_transition_jobs(db, jira.client(), now=NOW + timedelta(minutes=6))
    assert [r.outcome for r in result] == ["CONFIRMED"]


@pytest.mark.parametrize("http_status,expected", [(400, "NEEDS_ADMIN"), (401, "NEEDS_ADMIN"),
                                                 (429, "RETRY_SCHEDULED"), (503, "VERIFY_SCHEDULED")])
def test_write_failure_preserves_confirmed_fields_and_create_sync_status(transition_db, http_status, expected):
    db = transition_db
    ticket, job = make_transition(db, "WIP", "FIN", "새 결과")
    jira = Workflow("WIP")
    jira.write_status = http_status
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == expected
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.resolution_note, ticket.finished_at, ticket.jira_sync_status) == ("WIP", None, None, "SYNCED")
    assert ticket.transition_status == ("NEEDS_ADMIN" if expected == "NEEDS_ADMIN" else "PENDING")


def test_note_edit_timeout_after_apply_is_confirmed_without_second_put(transition_db):
    db = transition_db
    _, job = make_transition(db, "WIP", None, "새 결과")
    jira = Workflow("WIP", "기존 결과")
    jira.write_error = httpx.ReadTimeout("slow")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "VERIFY_SCHEDULED"
    jira.write_error = None
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW + timedelta(minutes=2)).outcome == "CONFIRMED"
    assert (jira.edits, jira.transitions) == (1, 0)


def test_same_note_is_confirmed_without_write_or_state_history(transition_db):
    db = transition_db
    _, job = make_transition(db, "FIN", None, "기존 결과")
    jira = Workflow("FIN", "기존 결과")
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "CONFIRMED"
    assert jira.edits == 0 and db.scalar(select(TicketStatusHistory)) is None


def test_cls_without_jira_final_result_is_not_sent(transition_db):
    db = transition_db
    _, job = make_transition(db, "FIN", "CLS")
    jira = Workflow("FIN")
    result = service.run_jira_transition_job(db, jira.client(), job.id, now=NOW)
    assert (result.outcome, result.reason) == ("NEEDS_ADMIN", "final_result_missing")
    assert jira.transitions == 0


def test_changed_ticket_request_is_not_overwritten_after_jira_call(transition_db):
    db = transition_db
    ticket, job = make_transition(db)
    jira = Workflow()
    def external_update():
        ticket.work_status, ticket.requested_work_status, ticket.transition_status = "FIN", None, "IDLE"
        db.commit()
    jira.after_write = external_update
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.work_status, ticket.transition_status) == ("FIN", "IDLE")
    assert db.scalar(select(TicketStatusHistory)) is None


@pytest.mark.parametrize("field,value", [("ticketId", 999), ("jiraKey", "ITHD-999"),
                                        ("fromStatus", []), ("reason", []), ("requestedAt", "bad")])
def test_invalid_job_is_rejected_before_external_call(transition_db, field, value):
    db = transition_db
    _, job = make_transition(db)
    job.payload = {**job.payload, field: value}
    db.commit()
    jira = Workflow()
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "NEEDS_ADMIN"
    assert jira.calls == []


def test_transition_does_not_claim_a_create_job(transition_db):
    db = transition_db
    ticket = make_ticket(db)
    job = IntegrationJob(ticket_id=ticket.id, job_type="JIRA_CREATE", status="PENDING", attempts=0,
                         idempotency_key="create:other", payload={})
    db.add(job)
    db.commit()
    jira = Workflow()
    assert service.run_jira_transition_job(db, jira.client(), job.id, now=NOW).outcome == "SKIPPED"
    assert reload(db, IntegrationJob, job.id).attempts == 0
    assert jira.calls == []


def test_db_commit_failure_after_jira_apply_recovers_without_reposting(transition_db, monkeypatch):
    db = transition_db
    ticket, job = make_transition(db)
    ticket_id, job_id = ticket.id, job.id
    jira = Workflow()
    commit = db.commit
    calls = 0
    def fail_final_commit():
        nonlocal calls
        calls += 1
        if calls == 3:  # 선점·쓰기 전 표식은 저장됐고, Jira 적용 후 DB 확정 저장만 실패
            raise OperationalError("COMMIT", {}, Exception("DB unavailable"))
        commit()
    monkeypatch.setattr(db, "commit", fail_final_commit)
    with pytest.raises(OperationalError):
        service.run_jira_transition_job(db, jira.client(), job_id, now=NOW)
    db.rollback()
    monkeypatch.setattr(db, "commit", commit)
    assert reload(db, Ticket, ticket_id).work_status == "RDY"
    assert reload(db, IntegrationJob, job_id).status == "RUNNING"
    later = NOW + timedelta(minutes=10)
    assert service.requeue_stale_transition_jobs(db, now=later) == 1
    assert service.run_jira_transition_job(db, jira.client(), job_id, now=later).outcome == "CONFIRMED"
    assert jira.transitions == 1
    assert len(db.scalars(select(TicketStatusHistory)).all()) == 1
