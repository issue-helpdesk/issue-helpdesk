"""새로고침 동기화 (TK-14). SQLite 메모리 DB·모의 Jira 만 사용한다."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.integrations.jira import JiraError
from app.main import app
from app.models import AssignmentLog, IntegrationJob, TicketStatusHistory
from app.services.integration_retry import jira_opener
from app.utils import datetime_utils
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import TICKETS, admin, as_user, db, staff, team  # noqa: F401

BUSY_ACCOUNT, FREE_ACCOUNT = "acc-E0005", "acc-E0006"


class FakeJira:
    def __init__(self, work_status="WIP", final_result="", account=BUSY_ACCOUNT, error=None):
        self.work_status, self.final_result, self.account, self.error = work_status, final_result, account, error
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_work_result(self, key):
        self.reads += 1
        if self.error:
            raise self.error
        return {"work_status": self.work_status, "final_result": self.final_result}

    def get_assignee(self, key):
        return {"account_id": self.account, "display_name": None}


@pytest.fixture
def use_jira():
    def use(jira):
        app.dependency_overrides[jira_opener] = lambda: (lambda: jira)
        return jira
    yield use
    app.dependency_overrides.pop(jira_opener, None)


@pytest.fixture
def ticket(db, team):
    t = team["mine"]
    t.assignee_id = team["busy"].id
    db.commit()
    return t


def sync(client, headers, ticket_id):
    return client.post(f"{TICKETS}/{ticket_id}/sync", headers=headers)


def test_reflects_jira_and_returns_ticket(client, db, headers, ticket, use_jira):
    use_jira(FakeJira(work_status="FIN", final_result="재설치로 해결"))

    res = sync(client, headers, ticket.id)

    assert res.status_code == 200
    body = res.json()
    assert (body["workStatus"], body["resolutionNote"]) == ("FIN", "재설치로 해결")
    assert body["workStatusConfirmedAt"] is not None
    (history,) = db.scalars(select(TicketStatusHistory).where(TicketStatusHistory.ticket_id == ticket.id)).all()
    assert (history.from_status, history.to_status, history.source) == ("WIP", "FIN", "JIRA")


def test_reflects_assignee(client, db, headers, ticket, team, use_jira):
    use_jira(FakeJira(account=FREE_ACCOUNT))

    assert sync(client, headers, ticket.id).status_code == 200

    assert ticket.assignee_id == team["free"].id
    (log,) = db.scalars(select(AssignmentLog).where(AssignmentLog.ticket_id == ticket.id)).all()
    assert log.event == "REASSIGN"


def test_same_values_only_update_confirmed_time(client, db, headers, ticket, use_jira):
    use_jira(FakeJira())

    assert sync(client, headers, ticket.id).json()["workStatus"] == "WIP"

    assert db.scalars(select(TicketStatusHistory)).all() == []
    assert ticket.work_status_confirmed_at is not None


def test_recent_sync_does_not_call_jira(client, db, headers, ticket, use_jira):
    jira = use_jira(FakeJira(work_status="FIN", final_result="해결"))
    ticket.work_status_confirmed_at = datetime_utils.now() - timedelta(seconds=5)
    db.commit()

    assert sync(client, headers, ticket.id).json()["workStatus"] == "WIP"
    assert jira.reads == 0


def test_old_confirmation_calls_jira(client, db, headers, ticket, use_jira):
    jira = use_jira(FakeJira())
    ticket.work_status_confirmed_at = datetime_utils.now() - timedelta(seconds=31)
    db.commit()

    sync(client, headers, ticket.id)

    assert jira.reads == 1


def test_repeated_refresh_calls_jira_once(client, headers, ticket, use_jira):
    jira = use_jira(FakeJira())

    sync(client, headers, ticket.id)
    sync(client, headers, ticket.id)

    assert jira.reads == 1


def test_recheck_interval_applies_while_failed_job_waits(client, db, headers, ticket, use_jira):
    """반영하지 않는 경우에도 연타로 Jira 를 부르지 않는다."""
    jira = use_jira(FakeJira(work_status="FIN", final_result="해결"))
    ticket.transition_status, ticket.requested_work_status = "NEEDS_ADMIN", "FIN"
    db.add(IntegrationJob(ticket_id=ticket.id, job_type="JIRA_TRANSITION", status="NEEDS_ADMIN", attempts=3,
                          idempotency_key="job:1", payload={}))
    db.commit()

    assert sync(client, headers, ticket.id).json()["workStatus"] == "WIP"
    sync(client, headers, ticket.id)

    assert jira.reads == 1
    assert ticket.transition_status == "NEEDS_ADMIN"


@pytest.mark.parametrize("error", [JiraError("timeout", "시간 초과", retryable=True),
                                   JiraError("not_found", "없음", retryable=False)])
def test_jira_failure_returns_last_values(client, db, headers, ticket, use_jira, error):
    use_jira(FakeJira(error=error))

    res = sync(client, headers, ticket.id)

    assert res.status_code == 200
    assert res.json()["workStatus"] == "WIP"
    assert ticket.work_status_confirmed_at is None


def test_jira_not_configured_returns_last_values(client, headers, ticket):
    def not_configured():
        raise JiraError("auth", "설정 없음", retryable=False)
    app.dependency_overrides[jira_opener] = lambda: not_configured
    try:
        assert sync(client, headers, ticket.id).status_code == 200
    finally:
        app.dependency_overrides.pop(jira_opener, None)


def test_unmapped_status_is_not_reflected(client, headers, ticket, use_jira):
    use_jira(FakeJira(work_status=None))

    assert sync(client, headers, ticket.id).json()["workStatus"] == "WIP"
    assert ticket.work_status_confirmed_at is None


def test_waits_while_job_is_active(client, db, headers, ticket, use_jira):
    jira = use_jira(FakeJira(work_status="FIN", final_result="해결"))
    db.add(IntegrationJob(ticket_id=ticket.id, job_type="JIRA_TRANSITION", status="PENDING", attempts=0,
                          idempotency_key="job:1", payload={}))
    db.commit()

    assert sync(client, headers, ticket.id).json()["workStatus"] == "WIP"
    assert jira.reads == 0


@pytest.mark.parametrize("fields", [{"jira_sync_status": "PENDING"}, {"work_status": "CLS"}])
def test_skips_without_calling_jira(client, db, headers, ticket, use_jira, fields):
    jira = use_jira(FakeJira(work_status="FIN"))
    for name, value in fields.items():
        setattr(ticket, name, value)
    db.commit()

    assert sync(client, headers, ticket.id).status_code == 200
    assert jira.reads == 0


def test_needs_admin_rules_match_webhook(client, headers, ticket, use_jira):
    use_jira(FakeJira(work_status="FIN", final_result=""))

    body = sync(client, headers, ticket.id).json()

    assert (body["workStatus"], body["transitionStatus"]) == ("WIP", "NEEDS_ADMIN")


def test_permissions(client, db, admin, ticket, use_jira):
    use_jira(FakeJira())

    assert sync(client, admin, ticket.id).status_code == 200
    assert client.post(f"{TICKETS}/{ticket.id}/sync").status_code == 401
    other = sync(client, as_user(client, "E0003"), ticket.id)
    assert (other.status_code, error_code(other)) == (404, "TICKET_NOT_FOUND")
    assert error_code(sync(client, admin, 999)) == "TICKET_NOT_FOUND"
