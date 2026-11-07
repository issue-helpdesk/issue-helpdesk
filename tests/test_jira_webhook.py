"""Jira 웹훅 (TK-13). SQLite 메모리 DB·모의 Jira 만 사용한다."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.integrations.jira import JiraError
from app.integrations.jira import worker
from app.models import AssignmentLog, Base, Inquiry, IntegrationJob, JiraWebhookEvent, Notification, TicketStatusHistory
from app.services.jira_webhook import process_webhook_event, run_due_ticket_syncs, run_due_webhook_events
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import db, make_ticket, staff, team  # noqa: F401

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
    assert history.resolution_note == "재설치로 해결"
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


def failed_assign(db, ticket, *, assignee=None, key="assign:failed", last_error="invalid_fields"):
    """배정 작업이 실패해 관리자 확인이 된 접수 (06 R-49, 예: RCPT-0332)."""
    ticket.assign_status, ticket.assignee_id = "NEEDS_ADMIN", assignee
    add_job(db, ticket, job_type="JIRA_ASSIGN", status="NEEDS_ADMIN", key=key, last_error=last_error)
    return db.scalar(select(IntegrationJob).where(IntegrationJob.idempotency_key == key))


def test_jira_assignee_is_accepted_after_failed_assign_job(db, ticket, team):
    db.get(Inquiry, ticket.inquiry_id).status = "RECEIVED"
    job = failed_assign(db, ticket)

    process(db, FakeJira(account=FREE_ACCOUNT), add_event(db, ticket.id))

    assert (ticket.assign_status, ticket.assignee_id, ticket.assignment_revision) == ("ASSIGNED", team["free"].id, 1)
    assert (job.status, job.last_error) == ("DONE", "superseded:jira (invalid_fields)")
    (log,) = logs(db, ticket)
    assert (log.event, log.assignee_id, log.actor_id) == ("ASSIGN", team["free"].id, None)
    assert db.get(Inquiry, ticket.inquiry_id).status == "HANDED_OFF"
    assert db.scalar(select(Notification.recipient_id).where(Notification.kind == "ASSIGNED")) == team["free"].id


def test_uncertain_failure_is_closed_when_jira_has_the_reserved_assignee(db, ticket, team):
    job = failed_assign(db, ticket, assignee=team["busy"].id, last_error="verify_only:result_unknown")

    process(db, FakeJira(account=BUSY_ACCOUNT), add_event(db, ticket.id))

    assert (ticket.assign_status, ticket.assignee_id, ticket.assignment_revision) == ("ASSIGNED", team["busy"].id, 0)
    assert job.status == "DONE"
    assert logs(db, ticket) == []           # 담당자가 그대로라 이력은 남기지 않는다


@pytest.mark.parametrize("account", ["unknown-account", None])
def test_failed_assign_job_stays_for_admin_when_jira_assignee_is_not_eligible(db, ticket, team, account):
    job = failed_assign(db, ticket, assignee=team["busy"].id)

    process(db, FakeJira(account=account), add_event(db, ticket.id))

    # 접수·revision 을 바꾸지 않아야 TK-12 재처리가 그대로 가능하다
    assert (ticket.assign_status, ticket.assignee_id, ticket.assignment_revision) == ("NEEDS_ADMIN", team["busy"].id, 0)
    assert job.status == "NEEDS_ADMIN"
    assert logs(db, ticket) == []


def test_retried_failure_does_not_block_and_only_open_ones_are_closed(db, ticket, team):
    old = failed_assign(db, ticket, key="assign:old")
    add_job(db, ticket, job_type="JIRA_ASSIGN", status="NEEDS_ADMIN", key="assign:old:retry", retry_of_job_id=old.id)

    process(db, FakeJira(account=FREE_ACCOUNT), add_event(db, ticket.id))

    retry = db.scalar(select(IntegrationJob).where(IntegrationJob.idempotency_key == "assign:old:retry"))
    assert (old.status, old.last_error) == ("NEEDS_ADMIN", "invalid_fields")     # 이미 재처리된 원본은 손대지 않는다
    assert (retry.status, ticket.assign_status) == ("DONE", "ASSIGNED")


def test_failed_assign_is_accepted_by_periodic_sync_too(db, ticket, team):
    job = failed_assign(db, ticket)

    results = run_due_ticket_syncs(db, FakeJira(account=FREE_ACCOUNT), now=NOW)

    db.refresh(ticket)
    db.refresh(job)
    assert [(r.ticket_id, r.outcome) for r in results] == [(ticket.id, "SYNCED")]
    assert (ticket.assign_status, ticket.assignee_id, job.status) == ("ASSIGNED", team["free"].id, "DONE")


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


def test_event_finished_by_another_worker_while_reading_jira_is_skipped(db, ticket):
    """실행기가 둘이면 Jira 를 읽는 사이 다른 쪽이 같은 이벤트를 끝낼 수 있다. 늦은 쪽은 반영하지 않고 넘어간다."""
    event = add_event(db, ticket.id)

    class Raced(FakeJira):
        def get_assignee(self, key):
            db.execute(JiraWebhookEvent.__table__.update().where(JiraWebhookEvent.id == event.id).values(status="DONE"))
            return super().get_assignee(key)

    result = process(db, Raced(work_status="FIN", final_result="해결"), event)

    assert result.outcome == "SKIPPED"
    assert ticket.work_status == "WIP" and histories(db, ticket) == []


# ------------------------------------------------------------------ 실행기 연결


def test_worker_round_applies_received_event(client, db, ticket):
    """API 가 저장한 이벤트를 실행기 한 회차가 DB 에 반영한다 (수신 → 저장 → 실행기 → 반영)."""
    send(client, issue_updated())
    assert ticket.work_status == "WIP"                       # 받기만 해서는 바뀌지 않는다

    report = worker.run_round(db, FakeJira(work_status="FIN", final_result="재설치로 해결"), now=NOW)

    assert report.errors == [] and report.result_types == ["WEBHOOK"]
    assert [r.outcome for r in report.results] == ["DONE"] and "WEBHOOK:DONE 1" in report.summary()
    assert db.scalars(select(JiraWebhookEvent)).one().status == "DONE"
    assert (ticket.work_status, ticket.resolution_note) == ("FIN", "재설치로 해결")
    assert [h.to_status for h in histories(db, ticket)] == ["FIN"]


def test_worker_round_leaves_event_when_webhook_is_off_or_ticket_scoped(db, ticket):
    add_event(db, ticket.id)

    off = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, webhook=False)
    scoped = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, ticket_id=ticket.id)

    assert off.results == [] and scoped.results == []
    assert db.scalars(select(JiraWebhookEvent)).one().status == "PENDING" and ticket.work_status == "WIP"


def test_worker_round_runs_webhook_after_jobs_and_waits_for_active_job(db, ticket):
    """ITssue 작업이 진행 중인 접수의 이벤트는 기다린다. 다음 회차에 작업이 끝난 뒤 반영된다."""
    add_event(db, ticket.id)
    add_job(db, ticket, status="RUNNING")                    # 방치 판정 전의 진행 중 작업

    first = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, job_types=("JIRA_CREATE",))

    assert [(r.outcome, r.reason) for r in first.results] == [("WAITING", "job_in_progress")]
    assert db.scalars(select(JiraWebhookEvent)).one().status == "PENDING"


def test_worker_round_reports_webhook_failure_without_losing_job_results(db, ticket, monkeypatch):
    add_event(db, ticket.id)

    def boom(*a, **kw):
        raise RuntimeError("DB 끊김")

    monkeypatch.setattr("app.services.jira_webhook.run_due_webhook_events", boom)

    report = worker.run_round(db, FakeJira(), now=NOW)

    assert report.errors == ["WEBHOOK:run:RuntimeError"] and report.results == []


def test_refinish_keeps_each_result_in_history(db, ticket):
    """재완료로 접수의 값을 덮어써도 완료마다의 처리 결과가 이력에 남는다."""
    process(db, FakeJira(work_status="FIN", final_result="재설치"), add_event(db, ticket.id, key="changelog:1"))
    process(db, FakeJira(work_status="WIP", final_result=""), add_event(db, ticket.id, key="changelog:2"))
    process(db, FakeJira(work_status="FIN", final_result="인증서 재발급"), add_event(db, ticket.id, key="changelog:3"))

    db.refresh(ticket)
    assert ticket.resolution_note == "인증서 재발급"
    rows = sorted(histories(db, ticket), key=lambda h: h.id)
    assert [(h.to_status, h.resolution_note) for h in rows] == [("FIN", "재설치"), ("WIP", None), ("FIN", "인증서 재발급")]


# ------------------------------------------------------------------ 주기 대조 (웹훅이 빠졌을 때의 보정)


def extra_ticket(db, team, n, confirmed_at=None, **fields):
    """Jira 와 연결이 끝난 접수를 더 만든다 (키 ITHD-16nn, 그룹·담당자 없음)."""
    values = {"work_status": "WIP", "jira_key": f"ITHD-16{n:02d}", "work_status_confirmed_at": confirmed_at} | fields
    return make_ticket(db, team["busy"], **values)


def fresh(ticket):
    """fixture 접수가 대상에서 빠지도록 방금 대조한 것으로 둔다."""
    ticket.work_status_confirmed_at = NOW


def test_periodic_sync_reflects_jira_change_without_webhook(db, ticket):
    """웹훅이 한 번도 오지 않아도, 한 번도 대조하지 않은 접수는 Jira 최신 상태로 맞춰진다."""
    results = run_due_ticket_syncs(db, FakeJira(work_status="FIN", final_result="재설치로 해결"), now=NOW)

    db.refresh(ticket)
    assert [(r.ticket_id, r.outcome) for r in results] == [(ticket.id, "SYNCED")]
    assert (ticket.work_status, ticket.resolution_note) == ("FIN", "재설치로 해결")
    assert [h.to_status for h in histories(db, ticket)] == ["FIN"]
    assert datetime_as_utc(ticket.work_status_confirmed_at) == NOW


def datetime_as_utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def test_periodic_sync_skips_recently_confirmed_and_picks_up_old_ones(db, ticket):
    ticket.work_status_confirmed_at = NOW - timedelta(seconds=59)
    db.commit()
    jira = FakeJira()

    assert run_due_ticket_syncs(db, jira, now=NOW) == [] and jira.reads == 0

    ticket.work_status_confirmed_at = NOW - timedelta(seconds=60)
    db.commit()
    assert [r.outcome for r in run_due_ticket_syncs(db, jira, now=NOW)] == ["SYNCED"] and jira.reads == 1


def test_periodic_sync_is_idempotent(db, ticket):
    """같은 값을 다시 읽어도 이력·알림을 또 만들지 않는다 (실행기가 둘이어도 안전한 이유)."""
    run_due_ticket_syncs(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW)
    later = NOW + timedelta(minutes=2)

    assert [r.outcome for r in run_due_ticket_syncs(db, FakeJira(work_status="FIN", final_result="해결"), now=later)] == ["SYNCED"]

    assert [h.to_status for h in histories(db, ticket)] == ["FIN"]
    assert len(db.scalars(select(Notification).where(Notification.kind == "FIN")).all()) == 1


def test_periodic_sync_takes_never_confirmed_first_then_oldest_within_limit(db, team, ticket):
    fresh(ticket)
    old = extra_ticket(db, team, 1, confirmed_at=NOW - timedelta(minutes=10))
    older = extra_ticket(db, team, 2, confirmed_at=NOW - timedelta(minutes=30))
    never = extra_ticket(db, team, 3, confirmed_at=None)
    db.commit()

    results = run_due_ticket_syncs(db, FakeJira(), limit=2, now=NOW)

    assert [r.ticket_id for r in results] == [never.id, older.id]
    db.refresh(old)
    assert datetime_as_utc(old.work_status_confirmed_at) == NOW - timedelta(minutes=10)      # 한도 밖이라 건드리지 않았다


def test_periodic_sync_leaves_closed_unlinked_and_not_synced_tickets(db, team, ticket):
    fresh(ticket)
    extra_ticket(db, team, 1, work_status="CLS")
    extra_ticket(db, team, 2, jira_sync_status="PENDING")
    extra_ticket(db, team, 3, jira_key=None)
    db.commit()
    jira = FakeJira()

    assert run_due_ticket_syncs(db, jira, now=NOW) == [] and jira.reads == 0


def test_periodic_sync_waits_for_active_itssue_job(db, ticket):
    add_job(db, ticket, status="RUNNING")
    jira = FakeJira(work_status="FIN", final_result="해결")

    results = run_due_ticket_syncs(db, jira, now=NOW)

    assert [r.outcome for r in results] == ["JOB_IN_PROGRESS"] and jira.reads == 0
    assert ticket.work_status == "WIP" and ticket.work_status_confirmed_at is None


def test_periodic_sync_stops_after_consecutive_jira_failures(db, team, ticket):
    for n in range(1, 6):
        extra_ticket(db, team, n)
    jira = FakeJira(error=JiraError("timeout", "시간 초과", retryable=True))

    results = run_due_ticket_syncs(db, jira, now=NOW)

    assert [r.outcome for r in results] == ["JIRA_UNAVAILABLE"] * 3 and jira.reads == 3      # 6건 중 3건에서 멈춘다
    assert ticket.work_status_confirmed_at is None                                            # 실패한 접수는 다음 회차에 다시 고른다


def test_periodic_sync_does_not_treat_missing_issues_as_jira_outage(db, team, ticket):
    """Jira 에서 지워진 이슈(404)는 장애가 아니다. 여러 건이어도 회차를 멈추지 않고 모두 확인한다."""
    for n in range(1, 5):
        extra_ticket(db, team, n)
    jira = FakeJira(error=JiraError("not_found", "없음", retryable=False))

    results = run_due_ticket_syncs(db, jira, now=NOW)

    assert [r.outcome for r in results] == ["JIRA_NOT_FOUND"] * 5 and jira.reads == 5      # 5건 모두 확인했다


def test_periodic_sync_unexpected_error_skips_only_that_ticket(db, team, ticket):
    fresh(ticket)
    bad = extra_ticket(db, team, 1, confirmed_at=NOW - timedelta(minutes=9))
    good = extra_ticket(db, team, 2, confirmed_at=NOW - timedelta(minutes=5))

    class Flaky(FakeJira):
        def get_work_result(self, key):
            if key == bad.jira_key:
                raise RuntimeError("DB 끊김")
            return super().get_work_result(key)

    results = run_due_ticket_syncs(db, Flaky(work_status="FIN", final_result="해결"), now=NOW)

    assert [(r.ticket_id, r.outcome) for r in results] == [(bad.id, "ERROR"), (good.id, "SYNCED")]
    db.refresh(good)
    assert good.work_status == "FIN"


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"stale_after": timedelta(seconds=29)}])
def test_periodic_sync_rejects_bad_arguments(db, kwargs):
    with pytest.raises(ValueError):
        run_due_ticket_syncs(db, FakeJira(), now=NOW, **kwargs)


# ------------------------------------------------------------------ 주기 대조 · 실행기 연결


def test_worker_round_runs_periodic_sync_after_webhook_when_enabled(db, ticket):
    add_event(db, ticket.id)

    report = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, sync=True)

    assert report.errors == [] and report.result_types == ["WEBHOOK"]       # 웹훅이 방금 대조해서 주기 대조 대상이 아니다
    ticket.work_status_confirmed_at = NOW - timedelta(minutes=5)
    db.commit()

    second = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, sync=True)

    assert second.result_types == ["SYNC"] and "SYNC:SYNCED 1" in second.summary()


def test_worker_round_does_not_sync_by_default_or_when_ticket_scoped(db, ticket):
    jira = FakeJira(work_status="FIN", final_result="해결")

    default = worker.run_round(db, jira, now=NOW)
    scoped = worker.run_round(db, jira, now=NOW, sync=True, ticket_id=ticket.id)

    assert default.results == [] and scoped.results == [] and jira.reads == 0 and ticket.work_status == "WIP"


def test_worker_round_reports_sync_failures_without_losing_other_results(db, ticket, monkeypatch):
    add_event(db, ticket.id)

    def boom(*a, **kw):
        raise RuntimeError("DB 끊김")

    monkeypatch.setattr("app.services.jira_webhook.run_due_ticket_syncs", boom)

    report = worker.run_round(db, FakeJira(work_status="FIN", final_result="해결"), now=NOW, sync=True)

    assert report.errors == ["SYNC:run:RuntimeError"] and report.result_types == ["WEBHOOK"]


def test_worker_round_counts_ticket_level_sync_error(db, ticket):
    class Broken(FakeJira):
        def get_work_result(self, key):
            raise RuntimeError("DB 끊김")

    report = worker.run_round(db, Broken(), now=NOW, sync=True)

    assert report.errors == [f"SYNC:{ticket.id}:error"] and [r.outcome for r in report.results] == ["ERROR"]


@pytest.mark.parametrize("args", [["--sync-after-seconds", "29"], ["--sync-limit", "0"]])
def test_worker_cli_rejects_bad_sync_options(args):
    with pytest.raises(SystemExit):
        worker.main(args)
