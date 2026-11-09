"""연동 재처리 (TK-12). SQLite 메모리 DB·모의 Jira 만 사용한다."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.integrations.jira import JiraError
from app.integrations.jira.mapper import load_mapping
from app.main import app
from app.models import AssignmentLog, AuditLog, IntegrationJob, TicketStatusHistory
from app.services.integration_retry import jira_opener
from app.services.jira_assign import run_jira_assign_job
from app.services.jira_transition import run_jira_transition_job
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import TICKETS, admin, as_user, db, staff, team  # noqa: F401

CHANGED_AT = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
ACCOUNT = "acc-E0005"


class FakeJira:
    def __init__(self, *, found=None, work_status="RDY", final_result="", error=None):
        self.found, self.work_status, self.final_result, self.error = found, work_status, final_result, error
        self.account, self.mapping = None, load_mapping()
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def find_by_receipt(self, receipt_no):
        if self.error:
            raise self.error
        return self.found

    def get_work_status(self, key):
        return {"work_status": self.work_status}

    def get_work_result(self, key):
        if self.error:
            raise self.error
        return {"work_status": self.work_status, "final_result": self.final_result}

    def get_status_changed_at(self, key, source, target, *, not_before):
        return CHANGED_AT

    def transition_issue(self, key, target, final_result=None):
        self.writes.append(("transition", key, target))
        self.work_status = target

    def update_final_result(self, key, note):
        self.writes.append(("final_result", key, note))
        self.final_result = note

    def get_issue(self, key, fields=None):
        return {"fields": {"status": {"id": "10004"},        # RDY
                           "assignee": {"accountId": self.account} if self.account else None}}

    def set_assignee(self, key, account):
        self.writes.append(("assign", key, account))
        self.account = account


@pytest.fixture
def use_jira():
    def use(jira):
        app.dependency_overrides[jira_opener] = lambda: (lambda: jira)
        return jira
    yield use
    app.dependency_overrides.pop(jira_opener, None)


def retry(client, headers, ticket_id, job_id, reason="Jira 장애 복구"):
    return client.post(f"{TICKETS}/{ticket_id}/integration-jobs", headers=headers,
                       json={"retryOfJobId": job_id, "reason": reason})


def add_job(db, ticket, job_type, payload, status="NEEDS_ADMIN", key=None, **over):
    job = IntegrationJob(ticket_id=ticket.id, job_type=job_type, status=status, attempts=3,
                         idempotency_key=key or f"{job_type}:{ticket.id}:{status}", payload=payload,
                         last_error="server_error", **over)
    db.add(job)
    db.commit()
    return job


def create_source(db, ticket, **over):
    ticket.jira_key, ticket.jira_sync_status, ticket.assign_status, ticket.work_status = None, "NEEDS_ADMIN", "PENDING", None
    return add_job(db, ticket, "JIRA_CREATE", {"summary": "VPN"}, key=f"create:{ticket.receipt_no}", **over)


def assign_source(db, team, **over):
    ticket = team["mine"]
    ticket.assign_status, ticket.assignee_id, ticket.assignment_revision = "NEEDS_ADMIN", None, 2
    payload = {"ticketId": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": ticket.jira_key,
               "groupId": ticket.group_id, "assigneeId": team["busy"].id, "jiraAccountId": ACCOUNT,
               "assignmentRevision": 2, "requestedBy": None, "requestedAt": "2026-11-02T00:00:00+00:00", **over}
    return ticket, add_job(db, ticket, "JIRA_ASSIGN", payload, key="assign:abc")


def transition_source(db, team, source="RDY", target="WIP"):
    ticket = team["mine"]
    ticket.work_status, ticket.requested_work_status, ticket.transition_status = source, target, "NEEDS_ADMIN"
    payload = {"ticketId": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": ticket.jira_key,
               "fromStatus": source, "toStatus": target, "resolutionNote": None, "reason": None,
               "requestedBy": team["busy"].id, "requestedAt": "2026-11-02T00:00:00+00:00",
               "resolutionConfirmedAt": None}
    return ticket, add_job(db, ticket, "JIRA_TRANSITION", payload, key="transition:abc")


def audit_results(db):
    return [(a.event_type, a.result, a.reason) for a in db.scalars(select(AuditLog).where(
        AuditLog.event_type == "INTEGRATION_RETRY"))]


def test_create_registers_new_job_when_not_in_jira(client, db, admin, team, use_jira):
    use_jira(FakeJira(found=None))
    ticket = team["mine"]
    source = create_source(db, ticket)

    res = retry(client, admin, ticket.id, source.id)

    assert res.status_code == 201
    body = res.json()
    assert (body["jobType"], body["status"], body["attempts"], body["retryOfJobId"]) == ("JIRA_CREATE", "PENDING", 0, source.id)
    assert body["idempotencyKey"] == f"create:{ticket.receipt_no}:retry:{source.id}"
    assert ticket.jira_sync_status == "PENDING"
    assert db.get(IntegrationJob, body["id"]).payload == source.payload
    assert source.status == "NEEDS_ADMIN"                   # 원본은 그대로 둔다
    assert audit_results(db) == [("INTEGRATION_RETRY", "QUEUED", "Jira 장애 복구")]


def test_create_links_existing_issue(client, db, admin, team, use_jira):
    use_jira(FakeJira(found={"jira_issue_id": "9", "jira_key": "ITHD-77"}, work_status="WIP"))
    ticket = team["mine"]
    source = create_source(db, ticket)

    res = retry(client, admin, ticket.id, source.id)

    assert res.status_code == 200
    body = res.json()
    assert body["job"] is None and body["recoveryResult"] == "LINKED_EXISTING"
    assert body["ticket"]["jiraKey"] == "ITHD-77"
    assert (ticket.jira_key, ticket.jira_sync_status, ticket.work_status) == ("ITHD-77", "SYNCED", "WIP")
    assert source.status == "DONE"
    assert audit_results(db) == [("INTEGRATION_RETRY", "LINKED_EXISTING", "Jira 장애 복구")]


def test_create_already_synced(client, db, admin, team, use_jira):
    use_jira(FakeJira())
    ticket = team["mine"]
    source = create_source(db, ticket)
    ticket.jira_key = "ITHD-5"
    db.commit()

    res = retry(client, admin, ticket.id, source.id)

    assert error_code(res) == "INTEGRATION_ALREADY_SYNCED"
    assert res.json()["error"]["details"][0]["value"] == "ITHD-5"


def test_create_unknown_result_keeps_state_and_returns_503(client, db, admin, team, use_jira):
    use_jira(FakeJira(error=JiraError("timeout", "시간 초과", retryable=True)))
    ticket = team["mine"]
    source = create_source(db, ticket)

    res = retry(client, admin, ticket.id, source.id)

    assert (res.status_code, error_code(res)) == (503, "SERVICE_UNAVAILABLE")
    assert ticket.jira_sync_status == "NEEDS_ADMIN"
    assert db.scalars(select(IntegrationJob)).all() == [source]
    assert audit_results(db) == []


def test_jira_not_configured_returns_503(client, db, admin, team):
    def not_configured():
        raise JiraError("auth", "설정 없음", retryable=False)
    app.dependency_overrides[jira_opener] = lambda: not_configured
    ticket = team["mine"]
    source = create_source(db, ticket)

    assert error_code(retry(client, admin, ticket.id, source.id)) == "SERVICE_UNAVAILABLE"


def test_assign_restores_reservation(client, db, admin, team):
    """Jira 를 읽지 않고 등록한다. 비교는 실행기가 한다."""
    ticket, source = assign_source(db, team)

    res = retry(client, admin, ticket.id, source.id)

    assert res.status_code == 201
    assert res.json()["idempotencyKey"] == f"assign:abc:retry:{source.id}"
    assert (ticket.assign_status, ticket.assignee_id, ticket.assignment_revision) == ("PENDING", team["busy"].id, 2)
    log = db.scalars(select(AssignmentLog).where(AssignmentLog.ticket_id == ticket.id)).one()
    assert (log.event, log.assignee_id, log.reason) == ("ASSIGN", team["busy"].id, "Jira 장애 복구")


def test_retried_assign_runs_in_executor(client, db, admin, team):
    """복구한 예약이 실행기 검증을 통과해 실제로 배정까지 간다."""
    ticket, source = assign_source(db, team)
    ticket.work_status, ticket.jira_key, source.payload = "RDY", "ITHD-1520", {**source.payload, "jiraKey": "ITHD-1520"}
    db.commit()
    job_id = retry(client, admin, ticket.id, source.id).json()["id"]
    jira = FakeJira()

    result = run_jira_assign_job(db, jira, job_id)

    assert result.outcome == "ASSIGNED", result.reason
    assert jira.writes == [("assign", "ITHD-1520", ACCOUNT)]
    assert ticket.assign_status == "ASSIGNED"


def test_assign_keeps_reservation_when_result_was_unknown(client, db, admin, team):
    ticket, source = assign_source(db, team)
    ticket.assignee_id = team["busy"].id
    db.commit()

    assert retry(client, admin, ticket.id, source.id).status_code == 201
    assert db.scalars(select(AssignmentLog).where(AssignmentLog.ticket_id == ticket.id)).all() == []


def test_assign_revision_mismatch(client, db, admin, team):
    ticket, source = assign_source(db, team, assignmentRevision=1)

    res = retry(client, admin, ticket.id, source.id)

    assert error_code(res) == "INTEGRATION_RETRY_NOT_ALLOWED"
    assert res.json()["error"]["details"][0]["reason"] == "ASSIGNMENT_REVISION"
    assert ticket.assign_status == "NEEDS_ADMIN"


def test_assign_other_assignee_is_not_overwritten(client, db, admin, team):
    ticket, source = assign_source(db, team)
    ticket.assignee_id = team["free"].id
    db.commit()

    assert error_code(retry(client, admin, ticket.id, source.id)) == "INTEGRATION_RETRY_NOT_ALLOWED"
    assert ticket.assignee_id == team["free"].id


def test_transition_registers_new_job(client, db, admin, team, use_jira):
    use_jira(FakeJira(work_status="RDY"))
    ticket, source = transition_source(db, team)

    res = retry(client, admin, ticket.id, source.id)

    assert res.status_code == 201
    assert res.json()["retryOfJobId"] == source.id
    assert (ticket.transition_status, ticket.requested_work_status, ticket.work_status) == ("PENDING", "WIP", "RDY")


def test_retried_transition_runs_in_executor(client, db, admin, team, use_jira):
    jira = use_jira(FakeJira(work_status="RDY"))
    ticket, source = transition_source(db, team)
    job_id = retry(client, admin, ticket.id, source.id).json()["id"]

    result = run_jira_transition_job(db, jira, job_id)

    assert result.outcome == "CONFIRMED", result.reason
    assert jira.writes == [("transition", "ITHD-1520", "WIP")]
    assert (ticket.transition_status, ticket.work_status) == ("IDLE", "WIP")


def test_transition_already_applied_saves_like_executor(client, db, admin, team, use_jira):
    jira = use_jira(FakeJira(work_status="WIP"))
    ticket, source = transition_source(db, team)

    res = retry(client, admin, ticket.id, source.id)

    assert res.status_code == 200
    assert res.json()["job"] is None and res.json()["recoveryResult"] == "ALREADY_APPLIED"
    assert jira.writes == []
    assert source.status == "DONE"
    assert (ticket.transition_status, ticket.requested_work_status, ticket.work_status) == ("IDLE", None, "WIP")
    history = db.scalars(select(TicketStatusHistory).where(TicketStatusHistory.ticket_id == ticket.id)).one()
    assert (history.from_status, history.to_status) == ("RDY", "WIP")
    assert audit_results(db) == [("INTEGRATION_RETRY", "ALREADY_APPLIED", "Jira 장애 복구")]


def test_transition_conflict_with_jira(client, db, admin, team, use_jira):
    use_jira(FakeJira(work_status="CLS"))
    ticket, source = transition_source(db, team)

    res = retry(client, admin, ticket.id, source.id)

    assert error_code(res) == "INTEGRATION_RETRY_NOT_ALLOWED"
    assert res.json()["error"]["details"][0] == {"reason": "JIRA_STATUS", "message": "Jira 현재 상태", "value": "CLS"}
    assert ticket.transition_status == "NEEDS_ADMIN"
    assert db.scalars(select(IntegrationJob)).all() == [source]


def test_transition_unknown_result_returns_503(client, db, admin, team, use_jira):
    use_jira(FakeJira(error=JiraError("network", "연결 실패", retryable=True)))
    ticket, source = transition_source(db, team)

    assert error_code(retry(client, admin, ticket.id, source.id)) == "SERVICE_UNAVAILABLE"
    assert ticket.transition_status == "NEEDS_ADMIN"


def test_transition_request_changed_since_failure(client, db, admin, team, use_jira):
    use_jira(FakeJira())
    ticket, source = transition_source(db, team)
    ticket.transition_status = "IDLE"
    db.commit()

    assert error_code(retry(client, admin, ticket.id, source.id)) == "INTEGRATION_RETRY_NOT_ALLOWED"


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "DONE"])
def test_source_must_be_failed(client, db, admin, team, status):
    ticket = team["mine"]
    source = add_job(db, ticket, "JIRA_ASSIGN", {}, status=status)

    assert error_code(retry(client, admin, ticket.id, source.id)) == "INTEGRATION_RETRY_NOT_ALLOWED"


def test_failed_status_is_retryable(client, db, admin, team):
    ticket, source = assign_source(db, team)
    source.status = "FAILED"
    db.commit()

    assert retry(client, admin, ticket.id, source.id).status_code == 201


def test_same_source_cannot_be_retried_twice(client, db, admin, team):
    ticket, source = assign_source(db, team)
    first = retry(client, admin, ticket.id, source.id).json()
    db.get(IntegrationJob, first["id"]).status = "NEEDS_ADMIN"
    ticket.assign_status = "NEEDS_ADMIN"
    db.commit()

    res = retry(client, admin, ticket.id, source.id)

    assert error_code(res) == "INTEGRATION_RETRY_NOT_ALLOWED"
    assert res.json()["error"]["details"][0]["reason"] == "ALREADY_RETRIED"
    # 재처리 작업을 다시 재처리하면 키가 쌓이지 않는다
    assert retry(client, admin, ticket.id, first["id"]).json()["idempotencyKey"] == f"assign:abc:retry:{first['id']}"


def test_active_job_blocks_retry(client, db, admin, team):
    ticket, source = assign_source(db, team)
    add_job(db, ticket, "JIRA_ASSIGN", {}, status="PENDING", key="assign:other")

    assert error_code(retry(client, admin, ticket.id, source.id)) == "INTEGRATION_JOB_IN_PROGRESS"


def test_not_found_and_other_ticket(client, db, admin, team):
    ticket, source = assign_source(db, team)

    assert error_code(retry(client, admin, 999, source.id)) == "TICKET_NOT_FOUND"
    assert error_code(retry(client, admin, ticket.id, 999)) == "NOT_FOUND"
    assert error_code(retry(client, admin, team["secret"].id, source.id)) == "NOT_FOUND"


def test_admin_only_and_reason_required(client, db, admin, team):
    ticket, source = assign_source(db, team)

    assert retry(client, as_user(client, "E0004"), ticket.id, source.id).status_code == 403
    assert retry(client, admin, ticket.id, source.id, reason="   ").status_code == 422
    assert retry(client, admin, ticket.id, source.id, reason="가" * 501).status_code == 422
