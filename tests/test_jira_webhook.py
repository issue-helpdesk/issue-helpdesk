"""Jira 웹훅 (TK-13). SQLite 메모리 DB·모의 Jira 만 사용한다."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.integrations.jira import JiraError
from app.models import AssignmentLog, Base, Inquiry, IntegrationJob, JiraWebhookEvent, TicketStatusHistory
from app.services.jira_webhook import process_webhook_event, run_due_webhook_events
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import db, staff, team  # noqa: F401

URL = "/api/v1/webhooks/jira"
SECRET = "test-webhook-secret"
NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
KEY = "ITHD-1520"
BUSY_ACCOUNT, FREE_ACCOUNT = "acc-E0005", "acc-E0006"


class FakeJira:
    def __init__(self, work_status="WIP", final_result="", account=BUSY_ACCOUNT, error=None):
        self.work_status, self.final_result, self.account, self.error = work_status, final_result, account, error
        self.reads = 0

    def get_work_result(self, key):
        self.reads += 1
        if self.error:
            raise self.error
        return {"work_status": self.work_status, "final_result": self.final_result}

    def get_assignee(self, key):
        return {"account_id": self.account, "display_name": None}


@pytest.fixture(autouse=True)
def webhook_table(db, monkeypatch):
    Base.metadata.tables["jira_webhook_events"].create(db.bind)
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", SECRET)


@pytest.fixture
def ticket(db, team):
    """WIP·ASSIGNED, 담당자 E0005(Jira 계정 acc-E0005). Jira 와 같은 상태로 시작한다."""
    t = team["mine"]
    t.assignee_id = team["busy"].id
    db.commit()
    return t


def signed(body: bytes, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send(client, payload, *, signature=None, delivery=None):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-Hub-Signature": signature or signed(body)}
    if delivery:
        headers["X-Atlassian-Webhook-Identifier"] = delivery
    return client.post(URL, content=body, headers=headers)


def issue_updated(key=KEY, changelog_id="1001"):
    return {"webhookEvent": "jira:issue_updated", "timestamp": 1793592000000, "issue": {"key": key},
            "changelog": {"id": changelog_id, "items": [{"field": "status", "from": "10004", "to": "10005"}]}}


def add_event(db, ticket_id=None, issue_key=KEY, received_at=NOW, changed_at=None, key="changelog:1"):
    event = JiraWebhookEvent(event_key=key, ticket_id=ticket_id, issue_key=issue_key, status="PENDING",
                             received_at=received_at, changed_at=changed_at)
    db.add(event)
    db.commit()
    return event


def process(db, jira, event):
    return process_webhook_event(db, jira, event.id, now=NOW)


def histories(db, ticket):
    return db.scalars(select(TicketStatusHistory).where(TicketStatusHistory.ticket_id == ticket.id)).all()


def logs(db, ticket):
    return db.scalars(select(AssignmentLog).where(AssignmentLog.ticket_id == ticket.id)).all()


def add_job(db, ticket, job_type="JIRA_TRANSITION", status="PENDING", key="job:1", **over):
    db.add(IntegrationJob(ticket_id=ticket.id, job_type=job_type, status=status, attempts=0, idempotency_key=key,
                          payload={}, **over))
    db.commit()


# ------------------------------------------------------------------ 수신


def test_saves_pending_event_and_links_ticket(client, db, ticket):
    assert send(client, issue_updated()).status_code == 204

    event = db.scalars(select(JiraWebhookEvent)).one()
    assert (event.event_key, event.issue_key, event.ticket_id, event.status) == ("changelog:1001", KEY, ticket.id, "PENDING")
    assert event.changed_at is not None


def test_does_not_touch_ticket_on_receive(client, db, ticket):
    send(client, issue_updated())

    assert ticket.work_status == "WIP"
    assert histories(db, ticket) == []


def test_duplicate_is_saved_once(client, db, ticket):
    assert send(client, issue_updated(), delivery="d-1").status_code == 204
    assert send(client, issue_updated(), delivery="d-1").status_code == 204

    assert db.scalars(select(JiraWebhookEvent)).one().event_key == "delivery:d-1"


def test_unlinked_issue_is_saved(client, db, team):
    assert send(client, issue_updated(key="ITHD-9")).status_code == 204

    event = db.scalars(select(JiraWebhookEvent)).one()
    assert (event.ticket_id, event.status) == (None, "PENDING")


def test_comment_event_is_saved_as_ignored(client, db, ticket):
    payload = {"webhookEvent": "comment_created", "issue": {"key": KEY}, "comment": {"id": "77"}}

    assert send(client, payload).status_code == 204
    assert db.scalars(select(JiraWebhookEvent)).one().status == "IGNORED"


@pytest.mark.parametrize("signature", ["sha256=" + "0" * 64, "md5=abc", "nonsense"])
def test_bad_signature(client, db, signature):
    res = send(client, issue_updated(), signature=signature)

    assert (res.status_code, error_code(res)) == (401, "WEBHOOK_SIGNATURE_INVALID")
    assert db.scalars(select(JiraWebhookEvent)).all() == []


def test_signature_header_required(client):
    res = client.post(URL, content=b"{}", headers={"Content-Type": "application/json"})

    assert error_code(res) == "WEBHOOK_SIGNATURE_INVALID"


def test_rejects_when_server_has_no_secret(client, monkeypatch):
    monkeypatch.delenv("JIRA_WEBHOOK_SECRET")

    assert error_code(send(client, issue_updated())) == "WEBHOOK_SIGNATURE_INVALID"


@pytest.mark.parametrize("body", [b"not json", b"[1]", b'{"webhookEvent":"jira:issue_updated"}', b"\xff\xfe"])
def test_invalid_body(client, body):
    res = send(client, body)

    assert (res.status_code, error_code(res)) == (400, "INVALID_REQUEST")


def test_signature_checked_before_body(client):
    assert error_code(send(client, b"not json", signature="sha256=00")) == "WEBHOOK_SIGNATURE_INVALID"


# ------------------------------------------------------------------ 상태·처리 결과


def test_reflects_status_with_history(db, ticket):
    changed = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
    event = add_event(db, ticket.id, changed_at=changed)

    result = process(db, FakeJira(work_status="FIN", final_result="재설치로 해결"), event)

    assert result.outcome == "DONE"
    assert event.status == "DONE"
    assert (ticket.work_status, ticket.resolution_note, ticket.transition_status) == ("FIN", "재설치로 해결", "IDLE")
    assert ticket.finished_at is not None
    (history,) = histories(db, ticket)
    assert (history.from_status, history.to_status, history.source, history.actor_id) == ("WIP", "FIN", "JIRA", None)


def test_same_status_adds_no_history_and_is_idempotent(db, ticket):
    first, second = add_event(db, ticket.id, key="e:1"), add_event(db, ticket.id, key="e:2")
    jira = FakeJira(work_status="FIN", final_result="해결")

    process(db, jira, first)
    process(db, jira, second)

    assert len(histories(db, ticket)) == 1
    assert second.status == "DONE"


def test_old_event_does_not_roll_back(db, ticket):
    """이벤트 값이 아니라 Jira 최신 값을 쓴다."""
    ticket.work_status, ticket.resolution_note = "FIN", "해결"
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="FIN", final_result="해결"), event)

    assert ticket.work_status == "FIN"
    assert histories(db, ticket) == []


def test_note_only_change(db, ticket):
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="WIP", final_result="중간 메모"), event)

    assert ticket.resolution_note == "중간 메모"
    assert histories(db, ticket) == []


def test_reopen_clears_finished_at(db, ticket):
    ticket.work_status, ticket.finished_at = "FIN", NOW
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="WIP"), event)

    assert (ticket.work_status, ticket.finished_at) == ("WIP", None)


def test_fin_without_note_needs_admin_then_clears(db, ticket):
    first = add_event(db, ticket.id, key="e:1")
    process(db, FakeJira(work_status="FIN", final_result=""), first)

    assert first.status == "DONE"
    assert (ticket.work_status, ticket.transition_status, ticket.requested_work_status) == ("WIP", "NEEDS_ADMIN", "FIN")
    assert ticket.finished_at is None and histories(db, ticket) == []

    second = add_event(db, ticket.id, key="e:2")
    process(db, FakeJira(work_status="FIN", final_result="이제 입력"), second)

    assert (ticket.work_status, ticket.transition_status, ticket.requested_work_status) == ("FIN", "IDLE", None)


def test_hold_clears_when_jira_returns_to_same_status(db, ticket):
    first, second = add_event(db, ticket.id, key="e:1"), add_event(db, ticket.id, key="e:2")
    process(db, FakeJira(work_status="FIN"), first)

    process(db, FakeJira(work_status="WIP"), second)

    assert (ticket.transition_status, ticket.requested_work_status) == ("IDLE", None)


def test_cls_without_confirmation_needs_admin(db, ticket):
    ticket.work_status, ticket.resolution_note = "FIN", "해결"
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="CLS", final_result="해결"), event)

    assert (ticket.work_status, ticket.transition_status, ticket.closed_at) == ("FIN", "NEEDS_ADMIN", None)
    assert db.get(Inquiry, ticket.inquiry_id).resolution_result is None


def test_cls_with_confirmation_closes(db, ticket):
    confirmed = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    ticket.work_status, ticket.resolution_note, ticket.resolution_confirmed_at = "FIN", "해결", confirmed
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="CLS", final_result="해결"), event)

    inquiry = db.get(Inquiry, ticket.inquiry_id)
    assert ticket.work_status == "CLS" and ticket.closed_at is not None
    assert inquiry.resolution_result == "RESOLVED" and inquiry.closed_at is not None


def test_closed_ticket_is_not_reopened(db, ticket):
    ticket.work_status = "CLS"
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="WIP"), event)

    assert (ticket.work_status, ticket.transition_status) == ("CLS", "NEEDS_ADMIN")


def test_unmapped_status_needs_admin(db, ticket):
    event = add_event(db, ticket.id)

    result = process(db, FakeJira(work_status=None), event)

    assert result.outcome == "NEEDS_ADMIN"
    assert ticket.work_status == "WIP"


def test_waits_while_itssue_job_is_active(db, ticket):
    """ITssue 가 보낸 변경이 돌아온 이벤트는 실행기 저장과 겹치지 않게 기다린다."""
    add_job(db, ticket)
    event = add_event(db, ticket.id)
    jira = FakeJira(work_status="FIN", final_result="해결")

    result = process(db, jira, event)

    assert (result.outcome, event.status, jira.reads) == ("WAITING", "PENDING", 0)
    assert ticket.work_status == "WIP"


def test_failed_transition_job_is_left_to_retry_api(db, ticket):
    ticket.transition_status, ticket.requested_work_status = "NEEDS_ADMIN", "FIN"
    add_job(db, ticket, status="NEEDS_ADMIN")
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="FIN", final_result="해결"), event)

    assert event.status == "DONE"
    assert (ticket.work_status, ticket.transition_status) == ("WIP", "NEEDS_ADMIN")


def test_not_synced_ticket_status_is_not_reflected(db, ticket):
    ticket.jira_sync_status = "VERIFYING"
    db.commit()
    event = add_event(db, ticket.id)

    process(db, FakeJira(work_status="FIN", final_result="해결"), event)

    assert ticket.work_status == "WIP"


# ------------------------------------------------------------------ 담당자


def test_same_assignee_adds_no_log(db, ticket):
    process(db, FakeJira(), add_event(db, ticket.id))

    assert logs(db, ticket) == []
    assert ticket.assignment_revision == 0


def test_valid_reassign_in_jira(db, ticket, team):
    process(db, FakeJira(account=FREE_ACCOUNT), add_event(db, ticket.id))

    assert (ticket.assignee_id, ticket.assign_status, ticket.assignment_revision) == (team["free"].id, "ASSIGNED", 1)
    (log,) = logs(db, ticket)
    assert (log.event, log.assignee_id, log.actor_id) == ("REASSIGN", team["free"].id, None)


def test_first_assign_hands_off_inquiry(db, ticket, team):
    ticket.assign_status, ticket.assignee_id = "PENDING", None
    db.get(Inquiry, ticket.inquiry_id).status = "RECEIVED"
    db.commit()

    process(db, FakeJira(account=FREE_ACCOUNT), add_event(db, ticket.id))

    assert logs(db, ticket)[0].event == "ASSIGN"
    assert db.get(Inquiry, ticket.inquiry_id).status == "HANDED_OFF"


@pytest.mark.parametrize("account", ["unknown-account", None])
def test_unknown_or_cleared_assignee_needs_admin(db, ticket, account):
    process(db, FakeJira(account=account), add_event(db, ticket.id))

    assert (ticket.assignee_id, ticket.assign_status, ticket.assignment_revision) == (None, "NEEDS_ADMIN", 1)
    (log,) = logs(db, ticket)
    assert log.event == "FAIL"


def test_needs_admin_log_is_not_repeated(db, ticket):
    process(db, FakeJira(account="unknown"), add_event(db, ticket.id, key="e:1"))
    process(db, FakeJira(account="unknown"), add_event(db, ticket.id, key="e:2"))

    assert len(logs(db, ticket)) == 1


def test_empty_jira_assignee_before_assignment_is_normal(db, ticket):
    ticket.assign_status, ticket.assignee_id = "PENDING", None
    db.commit()

    process(db, FakeJira(account=None), add_event(db, ticket.id))

    assert ticket.assign_status == "PENDING"
    assert logs(db, ticket) == []


def test_failed_assign_job_is_left_to_retry_api(db, ticket):
    ticket.assign_status, ticket.assignee_id = "NEEDS_ADMIN", None
    add_job(db, ticket, job_type="JIRA_ASSIGN", status="NEEDS_ADMIN")

    process(db, FakeJira(account=FREE_ACCOUNT), add_event(db, ticket.id))

    assert (ticket.assign_status, ticket.assignee_id) == ("NEEDS_ADMIN", None)


# ------------------------------------------------------------------ 연결·재시도·포기


def test_links_ticket_when_created_later(db, ticket):
    event = add_event(db, None)

    result = process(db, FakeJira(work_status="FIN", final_result="해결"), event)

    assert result.outcome == "DONE"
    assert event.ticket_id == ticket.id


def test_unlinked_event_waits_then_is_ignored(db, team):
    event = add_event(db, None, issue_key="ITHD-9")
    jira = FakeJira()

    assert process(db, jira, event).outcome == "WAITING"
    assert jira.reads == 0
    event.received_at = NOW - timedelta(hours=25)
    db.commit()

    assert process(db, jira, event).outcome == "IGNORED"


def test_jira_failure_stays_pending_then_needs_admin(db, ticket):
    event = add_event(db, ticket.id)
    jira = FakeJira(error=JiraError("timeout", "시간 초과", retryable=True))

    assert process(db, jira, event).outcome == "RETRY"
    assert event.status == "PENDING"
    event.received_at = NOW - timedelta(hours=25)
    db.commit()

    assert process(db, jira, event).outcome == "NEEDS_ADMIN"


def test_deleted_issue_needs_admin(db, ticket):
    event = add_event(db, ticket.id)

    assert process(db, FakeJira(error=JiraError("not_found", "없음", retryable=False)), event).outcome == "NEEDS_ADMIN"


def test_finished_event_is_skipped(db, ticket):
    event = add_event(db, ticket.id)
    event.status = "DONE"
    db.commit()

    assert process(db, FakeJira(), event).outcome == "SKIPPED"


def test_run_due_counts_only_jira_calls(db, ticket, team):
    """기다리는 이벤트가 limit 을 차지하지 않는다."""
    add_event(db, None, issue_key="ITHD-9", key="e:0")
    first = add_event(db, ticket.id, key="e:1")
    second = add_event(db, ticket.id, key="e:2")

    results = run_due_webhook_events(db, FakeJira(), limit=1, now=NOW)

    assert [r.outcome for r in results] == ["WAITING", "DONE"]
    assert first.status == "DONE" and second.status == "PENDING"
