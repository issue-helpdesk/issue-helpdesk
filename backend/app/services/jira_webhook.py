"""Jira 웹훅 이벤트 저장과 DB 반영 (TK-13·14). 상태·처리 결과·담당자만 다룬다. 댓글은 IGNORED 로 저장만 한다.

    record_webhook_event     API 가 부른다. 저장·중복 검사만 하고 Jira 를 부르지 않는다
    run_due_webhook_events   실행기가 회차마다 부른다. 이벤트 한 건은 process_webhook_event 가 처리한다
    sync_ticket              새로고침(TK-14). 이벤트 없이 접수 하나를 바로 다시 읽어 같은 규칙으로 반영한다
    run_due_ticket_syncs     실행기가 회차마다 부른다. 오래 대조하지 않은 접수를 골라 sync_ticket 으로 맞춘다 (웹훅이 빠졌을 때의 보정)

    run_due_webhook_events(db, jira, limit=10)

이벤트 값으로 덮어쓰지 않는다. 이벤트는 신호로만 쓰고 값은 Jira 에서 다시 읽으므로 늦게 온 과거 이벤트도 상태를 되돌리지 않는다.
ITssue 가 보낸 변경이 되돌아온 이벤트는 작업이 끝날 때까지 기다렸다가, 값이 같아 그대로 DONE 이 된다.
"""
import logging
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.jira import JiraClient, JiraError
from app.integrations.jira.webhook import WebhookEvent
from app.models import (
    AssignmentLog,
    Inquiry,
    InquiryType,
    IntegrationJob,
    JiraWebhookEvent,
    Notification,
    Ticket,
    TicketStatusHistory,
)
from app.repositories.assignment import AssignmentRepository
from app.services.assignment import manual_problem
from app.services.jira_assign import supersede_assign_failures
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

ISSUE_UPDATED = "jira:issue_updated"
GIVE_UP_AFTER = timedelta(hours=24)         # 표에 시도 횟수 칸이 없어 수신 시각으로 포기를 정한다
SYNC_INTERVAL = timedelta(seconds=30)       # 새로고침을 연타해도 Jira 호출이 늘지 않게 한다
PERIODIC_SYNC_AFTER = timedelta(minutes=1)  # 실행기가 이 시간 넘게 Jira 와 대조하지 않은 접수를 다시 읽는다 (설계: 기본 1분)
JIRA_DOWN_AFTER = 3                         # Jira 오류가 연달아 이만큼 나오면 그 회차의 나머지 접수는 건너뛴다
JOB_TYPES = ("JIRA_TRANSITION", "JIRA_ASSIGN")


@dataclass(frozen=True)
class WebhookResult:
    event_id: int
    outcome: str                    # DONE · IGNORED · NEEDS_ADMIN · WAITING(Jira 를 안 불렀다) · RETRY · SKIPPED
    reason: str | None = None


@dataclass(frozen=True)
class TicketSyncResult:
    ticket_id: int
    outcome: str                    # SYNCED · JOB_IN_PROGRESS · JIRA_UNAVAILABLE · JIRA_NOT_FOUND · UNMAPPED · SKIPPED · RECENT · ERROR


def record_webhook_event(db: Session, event: WebhookEvent) -> bool:
    """이벤트를 저장하고 커밋한다. 이미 받은 이벤트면 False. 저장 실패는 그대로 올려 Jira 가 다시 보내게 한다."""
    if db.scalar(select(JiraWebhookEvent.id).where(JiraWebhookEvent.event_key == event.event_id)) is not None:
        return False
    ticket_id = db.scalar(select(Ticket.id).where(Ticket.jira_key == event.issue_key))
    db.add(JiraWebhookEvent(
        event_key=event.event_id, ticket_id=ticket_id, issue_key=event.issue_key,
        changed_at=changed_at_of(event), status="PENDING" if event.webhook_event == ISSUE_UPDATED else "IGNORED",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()               # 같은 이벤트가 동시에 들어왔다
        return False
    return True


def changed_at_of(event: WebhookEvent) -> datetime | None:
    return datetime.fromtimestamp(event.timestamp_ms / 1000, timezone.utc) if event.timestamp_ms else None


def run_due_webhook_events(db: Session, jira: JiraClient, *, limit: int = 10, now: datetime | None = None) -> list[WebhookResult]:
    """PENDING 이벤트를 오래된 순서로 처리한다. limit 은 Jira 를 부른 건수다. 기다리는 이벤트가 뒤의 이벤트를 막지 않게 한다."""
    ids = db.scalars(select(JiraWebhookEvent.id).where(JiraWebhookEvent.status == "PENDING")
                     .order_by(JiraWebhookEvent.id)).all()
    results, called = [], 0
    for event_id in ids:
        result = process_webhook_event(db, jira, event_id, now=now)
        results.append(result)
        called += result.outcome != "WAITING"
        if called >= limit:
            break
    return results


def process_webhook_event(db: Session, jira: JiraClient, event_id: int, *, now: datetime | None = None) -> WebhookResult:
    """이벤트 한 건을 처리하고 커밋한다. Jira 를 읽는 동안 행을 잠그지 않는다. 읽은 뒤 잠그고 다시 확인한다."""
    now = now or datetime_utils.now()
    event = db.get(JiraWebhookEvent, event_id, populate_existing=True)
    if event is None or event.status != "PENDING":
        return WebhookResult(event_id, "SKIPPED")

    ticket_id = event.ticket_id or db.scalar(select(Ticket.id).where(Ticket.jira_key == event.issue_key))
    if ticket_id is None:           # Jira 생성 결과가 저장되면 연결된다. 끝까지 없으면 ITssue 와 무관한 이슈다
        return close(db, event, "IGNORED", "no_ticket") if expired(event, now) else WebhookResult(event.id, "WAITING", "no_ticket")
    event.ticket_id = ticket_id
    if has_active_job(db, ticket_id):
        db.commit()
        return WebhookResult(event.id, "WAITING", "job_in_progress")

    try:
        latest = jira.get_work_result(event.issue_key)
        account_id = jira.get_assignee(event.issue_key)["account_id"]
    except JiraError as error:
        if error.reason == "not_found" or expired(event, now):
            return close(db, event, "NEEDS_ADMIN", error.reason)
        db.commit()
        return WebhookResult(event.id, "RETRY", error.reason)

    ticket = db.get(Ticket, ticket_id, with_for_update=True, populate_existing=True)
    db.refresh(event)                   # 실행기가 둘 이상이면 같은 이벤트를 먼저 끝낸 쪽이 있을 수 있다
    if event.status != "PENDING":
        db.rollback()
        return WebhookResult(event_id, "SKIPPED")
    if has_active_job(db, ticket.id):   # 읽는 사이에 작업이 등록됐다
        db.commit()
        return WebhookResult(event.id, "WAITING", "job_in_progress")
    if latest["work_status"] is None:   # 매핑에 없는 Jira 상태는 반영하지 않는다
        return close(db, event, "NEEDS_ADMIN", "unmapped_status")
    sync_work_status(db, ticket, latest, event.changed_at, now)
    sync_assignee(db, ticket, account_id, now)
    return close(db, event, "DONE")


def sync_ticket(db: Session, open_jira: Callable[[], JiraClient], ticket: Ticket, *, now: datetime | None = None) -> str:
    """접수 하나를 Jira 최신 값으로 맞추고 커밋한다. 화면이 부르므로 Jira 오류를 올리지 않는다. 결과는 로그·시험용이다."""
    now = now or datetime_utils.now()
    if ticket.jira_sync_status != "SYNCED" or not ticket.jira_key or ticket.work_status == "CLS":
        return "SKIPPED"
    confirmed = ticket.work_status_confirmed_at
    if confirmed is not None and datetime_utils.as_utc(now) - datetime_utils.as_utc(confirmed) < SYNC_INTERVAL:
        return "RECENT"
    if has_active_job(db, ticket.id):           # 실행기 저장과 겹치지 않게 한다
        return "JOB_IN_PROGRESS"
    try:
        with open_jira() as jira:
            latest = jira.get_work_result(ticket.jira_key)
            account_id = jira.get_assignee(ticket.jira_key)["account_id"]
    except JiraError as error:
        logger.warning("jira sync ticket %s failed (%s)", ticket.id, error.reason)
        return "JIRA_NOT_FOUND" if error.reason == "not_found" else "JIRA_UNAVAILABLE"     # 없는 이슈는 Jira 장애가 아니다

    ticket = db.get(Ticket, ticket.id, with_for_update=True, populate_existing=True)
    if has_active_job(db, ticket.id):           # 읽는 사이에 작업이 등록됐다
        db.commit()
        return "JOB_IN_PROGRESS"
    if latest["work_status"] is None:           # 매핑에 없는 Jira 상태는 반영하지 않는다
        db.commit()
        return "UNMAPPED"
    sync_work_status(db, ticket, latest, None, now)
    sync_assignee(db, ticket, account_id, now)
    ticket.work_status_confirmed_at = now
    db.commit()
    return "SYNCED"


def run_due_ticket_syncs(db: Session, jira: JiraClient, *, limit: int = 20, stale_after: timedelta = PERIODIC_SYNC_AFTER,
                         now: datetime | None = None) -> list[TicketSyncResult]:
    """웹훅이 빠져도 상태가 어긋나지 않게, 오래 대조하지 않은 접수를 오래된 순서로 limit 건까지 맞춘다.

    대상은 새로고침(sync_ticket)과 같다: Jira 와 연결이 끝났고(SYNCED) 종결(CLS)되지 않은 접수.
    한 번도 대조하지 않았거나(work_status_confirmed_at 없음) 마지막 대조가 stale_after 보다 오래된 것만 고른다.
    ITssue 작업이 진행 중인 접수는 sync_ticket 이 건너뛰고, 다음 회차에 다시 고른다.
    Jira 오류는 sync_ticket 이 삼킨다. 연달아 JIRA_DOWN_AFTER 건이 JIRA_UNAVAILABLE 이면 Jira 장애로 보고 이번 회차를 멈춘다.
    Jira 에서 지워진 이슈(JIRA_NOT_FOUND)는 장애가 아니므로 세지 않는다. 안 그러면 지워진 접수 몇 건이 정상 접수의 대조를 막는다.
    """
    if limit < 1 or stale_after < SYNC_INTERVAL:       # 이보다 짧으면 sync_ticket 이 RECENT 로 돌려보내 같은 접수만 계속 고른다
        raise ValueError("limit는 1 이상, stale_after는 새로고침 간격(30초) 이상이어야 합니다.")
    now = now or datetime_utils.now()
    ids = db.scalars(
        select(Ticket.id).where(
            Ticket.jira_sync_status == "SYNCED", Ticket.jira_key.is_not(None),
            or_(Ticket.work_status.is_(None), Ticket.work_status != "CLS"),
            or_(Ticket.work_status_confirmed_at.is_(None), Ticket.work_status_confirmed_at <= now - stale_after),
        ).order_by(Ticket.work_status_confirmed_at.asc().nulls_first(), Ticket.id).limit(limit)
    ).all()
    db.rollback()                       # 선택 조회의 트랜잭션을 닫고 접수마다 다시 읽는다
    results, unavailable = [], 0
    for ticket_id in ids:
        try:
            ticket = db.get(Ticket, ticket_id, populate_existing=True)
            outcome = "SKIPPED" if ticket is None else sync_ticket(db, lambda: nullcontext(jira), ticket, now=now)
        except Exception as error:      # DB 오류 등. 이 접수만 건너뛰고 나머지는 계속한다
            db.rollback()
            logger.error("jira periodic sync ticket %s failed (%s)", ticket_id, type(error).__name__)
            outcome = "ERROR"
        results.append(TicketSyncResult(ticket_id, outcome))
        if outcome == "JIRA_UNAVAILABLE":
            unavailable += 1
        elif outcome != "JIRA_NOT_FOUND":
            unavailable = 0
        if unavailable >= JIRA_DOWN_AFTER:
            logger.warning("jira periodic sync stopped: Jira 오류 %s건 연속", unavailable)
            break
    return results


def close(db: Session, event: JiraWebhookEvent, status: str, reason: str | None = None) -> WebhookResult:
    event.status = status
    event_id = event.id
    db.commit()
    if status == "NEEDS_ADMIN":
        logger.warning("jira webhook event %s → NEEDS_ADMIN (%s)", event_id, reason)
    return WebhookResult(event_id, status, reason)


def expired(event: JiraWebhookEvent, now: datetime) -> bool:
    return datetime_utils.as_utc(now) - datetime_utils.as_utc(event.received_at) > GIVE_UP_AFTER


def has_active_job(db: Session, ticket_id: int) -> bool:
    return db.scalar(select(IntegrationJob.id).where(
        IntegrationJob.ticket_id == ticket_id, IntegrationJob.job_type.in_(JOB_TYPES),
        IntegrationJob.status.in_(("PENDING", "RUNNING")),
    ).limit(1)) is not None


def has_open_failure(db: Session, ticket_id: int, job_type: str) -> bool:
    """재처리(TK-12)를 기다리는 실패 작업이 있나. 상태 변경은 있으면 반영하지 않는다. 배정은 sync_assignee 가 따로 판단한다."""
    retried = select(IntegrationJob.retry_of_job_id).where(IntegrationJob.retry_of_job_id.is_not(None))
    return db.scalar(select(IntegrationJob.id).where(
        IntegrationJob.ticket_id == ticket_id, IntegrationJob.job_type == job_type,
        IntegrationJob.status.in_(("FAILED", "NEEDS_ADMIN")), IntegrationJob.id.not_in(retried),
    ).limit(1)) is not None


def sync_work_status(db: Session, ticket: Ticket, latest: dict, changed_at: datetime | None, now: datetime) -> None:
    """Jira 최신 상태·처리 결과를 반영한다. 정상 완료로 볼 수 없는 변경은 값을 바꾸지 않고 관리자 확인으로 둔다."""
    if ticket.jira_sync_status != "SYNCED":
        return
    if ticket.transition_status != "IDLE" and has_open_failure(db, ticket.id, "JIRA_TRANSITION"):
        return
    target, note = latest["work_status"], latest["final_result"] or None
    if target == ticket.work_status:
        ticket.transition_status, ticket.requested_work_status = "IDLE", None     # 전에 잡아 둔 확인 대상이 풀렸다
        if note is not None:
            ticket.resolution_note = note
        ticket.work_status_confirmed_at = now
        return
    if (ticket.work_status == "CLS"                                 # 종결은 되돌리지 않는다 (1.3)
            or (target == "FIN" and not note)                       # 처리 결과 없는 완료
            or (target == "CLS" and ticket.resolution_confirmed_at is None)):   # 문의자 확인 없는 종결
        ticket.transition_status, ticket.requested_work_status = "NEEDS_ADMIN", target
        logger.warning("jira webhook ticket %s: %s → %s 확인 필요", ticket.id, ticket.work_status, target)
        return

    changed_at = changed_at or now
    db.add(TicketStatusHistory(ticket_id=ticket.id, from_status=ticket.work_status, to_status=target, source="JIRA",
                               resolution_note=note if target == "FIN" else None, changed_at=changed_at))
    if target == "FIN":
        ticket.finished_at = changed_at
        db.add(Notification(ticket_id=ticket.id, recipient_id=db.get(Inquiry, ticket.inquiry_id).user_id, kind="FIN"))
    elif ticket.work_status == "FIN" and target == "WIP":
        ticket.finished_at = None
    elif target == "CLS":
        inquiry = db.get(Inquiry, ticket.inquiry_id, with_for_update=True, populate_existing=True)
        inquiry.resolution_result = "RESOLVED"
        inquiry.closed_at = ticket.resolution_confirmed_at
        inquiry.updated_at = now
        ticket.closed_at = ticket.resolution_confirmed_at
    ticket.work_status = target
    if note is not None:
        ticket.resolution_note = note
    ticket.work_status_confirmed_at = now
    ticket.transition_status, ticket.requested_work_status = "IDLE", None


def sync_assignee(db: Session, ticket: Ticket, account_id: str | None, now: datetime) -> None:
    """Jira 담당자를 현재 배정 그룹 구성원과 대조한다. 그룹을 추론하지 않는다.

    배정 실패 작업이 열려 있어도 Jira 담당자가 배정 자격을 갖춘 구성원이면 받아들이고 그 실패를 닫는다 (06 R-49).
    자격이 없거나 비어 있으면 실패 작업과 접수를 그대로 두어 관리자 확인(TK-09·TK-12)에 맡긴다.
    """
    if ticket.work_status == "CLS" or ticket.group_id is None:
        return
    open_failure = has_open_failure(db, ticket.id, "JIRA_ASSIGN")
    members = AssignmentRepository(db).members(ticket.group_id, exclude_ticket_id=ticket.id)
    if account_id is None:
        if ticket.assign_status == "ASSIGNED" and not open_failure:     # 배정 전 접수는 Jira 담당자가 비어 있는 게 정상이다
            release_assignee(db, ticket, "Jira 에서 담당자 해제")
        return
    member = next((m for m in members if (m.jira_account_id or "").strip() == account_id.strip()), None)
    if member is not None and member.user_id == ticket.assignee_id and ticket.assign_status == "ASSIGNED":
        return

    inquiry_type = db.get(InquiryType, ticket.inquiry_type_id) if ticket.inquiry_type_id else None
    problem = manual_problem(member, inquiry_type.code if inquiry_type else None)
    if problem:
        if not open_failure:        # 열린 실패가 있으면 revision 을 올리지 않아 TK-12 재처리를 살려 둔다
            release_assignee(db, ticket, f"Jira 담당자 확인 필요: {problem}")
        return

    if open_failure:
        supersede_assign_failures(db, ticket.id, "jira", now)

    if member.user_id != ticket.assignee_id:
        event = "REASSIGN" if ticket.assignee_id is not None else "ASSIGN"
        ticket.assignee_id = member.user_id
        ticket.assignment_revision += 1             # 이전 판단으로 만든 작업이 덮어쓰지 못하게 한다
        db.add(AssignmentLog(ticket_id=ticket.id, event=event, group_id=ticket.group_id, assignee_id=member.user_id,
                             actor_id=None, reason="Jira 에서 담당자 변경"))
    ticket.assign_status = "ASSIGNED"
    db.add(Notification(ticket_id=ticket.id, recipient_id=ticket.assignee_id, kind="ASSIGNED"))
    inquiry = db.get(Inquiry, ticket.inquiry_id, with_for_update=True, populate_existing=True)
    if inquiry.status == "RECEIVED":
        inquiry.status, inquiry.updated_at = "HANDED_OFF", now


def release_assignee(db: Session, ticket: Ticket, reason: str) -> None:
    if ticket.assign_status == "NEEDS_ADMIN" and ticket.assignee_id is None:      # 이미 확인 대상이면 이력을 또 남기지 않는다
        return
    db.add(AssignmentLog(ticket_id=ticket.id, event="FAIL", group_id=ticket.group_id, assignee_id=ticket.assignee_id,
                         actor_id=None, reason=reason))
    ticket.assignee_id = None
    ticket.assign_status = "NEEDS_ADMIN"
    ticket.assignment_revision += 1
