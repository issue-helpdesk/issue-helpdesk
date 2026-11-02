"""Jira 업무 상태 변경 작업(JIRA_TRANSITION) 등록 — TK-07 요청을 연동 작업 큐에 넣는다.

TK-07 은 Ticket 의 확인된 상태(work_status)를 바로 바꾸지 않는다. 목표 상태·처리 결과·사유를 payload 에 담아
작업을 등록하고, Jira 반영이 조회로 확인된 뒤에 상태·처리 결과·시각과 이력을 갱신한다 (API 03 1.3).

기본 전환(RDY→WIP, WIP→FIN, FIN→CLS)과 WIP·FIN 처리 결과 수정을 실행한다.
FIN→WIP는 과거 결과 보존 정책이 확정될 때까지 DEFERRED로 두며 선점하지 않는다.
worker·API 등록은 별도 연결한다. 이 서비스는 이미 권한 검증을 마친 TK-07 작업만 받는다.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.retry import RetryPolicy, next_step
from app.models import Inquiry, IntegrationJob, Ticket, TicketStatusHistory, User
from app.repositories.ticket import TicketRepository
from app.utils import datetime_utils

JOB_TYPE = "JIRA_TRANSITION"


def enqueue_jira_transition(db: Session, ticket: Ticket, payload: dict[str, Any]) -> IntegrationJob:
    """flush 만 한다. 커밋은 호출자가 한다.

    접수당 진행 중(PENDING·RUNNING) 상태 변경 작업은 하나다 (uq_integration_jobs_one_active).
    동시에 두 요청이 들어오면 두 번째는 IntegrityError 가 난다. 키는 논리 작업마다 새 UUID (06 연동 보완).
    """
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0,
                         idempotency_key=f"transition:{uuid.uuid4()}", payload=payload)
    db.add(job)
    db.flush()
    return job


VERIFY_ONLY = "verify_only:"
BASIC_TRANSITIONS = {("RDY", "WIP"), ("WIP", "FIN"), ("FIN", "CLS")}


@dataclass(frozen=True)
class TransitionResult:
    job_id: int
    outcome: str
    reason: str | None = None


@dataclass(frozen=True)
class TransitionRequest:
    source: str
    target: str | None
    note: str | None
    actor_id: int
    requested_at: datetime
    confirmed_at: datetime | None
    reason: str | None

    @property
    def expected_status(self) -> str:
        return self.target or self.source


def run_jira_transition_job(
    db: Session, jira: JiraClient, job_id: int, *, now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),
) -> TransitionResult:
    """한 작업을 선점·실행·확인·저장한다. 결과 불명확/중단 복구 뒤에는 조회만 한다.

    외부 쓰기 전에 verify_only 표식을 커밋한다. 응답 또는 DB 저장 전에 죽어도 다음 실행에서
    POST/PUT을 재전송하지 않는다. 표식은 payload를 바꾸지 않고 last_error에 저장한다.
    재시도 숫자는 기존 RetryPolicy 제안값이다. PostgreSQL 동시성·실제 Jira 검증은 별도다.
    """
    now = now or datetime_utils.now()
    preview = db.get(IntegrationJob, job_id, populate_existing=True)
    if (preview and preview.job_type == JOB_TYPE and preview.status == "PENDING"
            and isinstance(preview.payload, dict)
            and (preview.payload.get("fromStatus"), preview.payload.get("toStatus")) == ("FIN", "WIP")):
        return TransitionResult(job_id, "DEFERRED", "reopen_policy_pending")
    claimed = db.execute(
        update(IntegrationJob).where(
            IntegrationJob.id == job_id, IntegrationJob.job_type == JOB_TYPE,
            IntegrationJob.status == "PENDING",
            or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
        ).values(status="RUNNING", attempts=IntegrationJob.attempts + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if claimed.rowcount != 1:
        return TransitionResult(job_id, "SKIPPED", "not_claimable")
    job = db.get(IntegrationJob, job_id, populate_existing=True)
    attempt = job.attempts
    ticket = db.get(Ticket, job.ticket_id, populate_existing=True)
    write_rejected = False
    try:
        request = _validate_request(db, job, ticket)
        issue_key = ticket.jira_key
        verify_only = (job.last_error or "").startswith(VERIFY_ONLY)
        latest = jira.get_work_result(issue_key)
        if latest["work_status"] not in {request.source, request.expected_status}:
            raise _conflict()
        if request.target == "CLS" and not latest["final_result"] and request.note is None:
            raise JiraError("final_result_missing", "최종 처리 결과 없이 종결하지 않습니다.", retryable=False)
        applied = _matches_result(latest, request)
        # 상태 전환 전에는 source==expected인 처리 결과 수정을 별도로 판정한다.
        if not applied:
            if verify_only:
                raise JiraError("result_unknown", "앞선 변경의 결과를 확인 중입니다.", retryable=False)
            if latest["work_status"] != request.source:
                raise _conflict()
            if not _mark_write(db, job_id, attempt, now):
                return TransitionResult(job_id, "SKIPPED", "ownership_lost")
            try:
                _apply_request(jira, issue_key, request)
            except JiraError as error:
                # 쓰기 함수의 429는 미전송/거절이다. 쓰기 뒤 재조회·이력 조회의 429와 구분한다.
                write_rejected = error.reason == "rate_limited"
                raise
            latest = jira.get_work_result(issue_key)
            if not _matches_result(latest, request):
                raise JiraError("result_unknown", "Jira 변경 결과가 아직 요청과 일치하지 않습니다.", retryable=False)
        changed_at = None
        if request.target is not None:
            changed_at = jira.get_status_changed_at(
                issue_key, request.source, request.target, not_before=request.requested_at,
            )
            # 변경 이력을 읽는 동안 다른 변경이 있었는지도 다시 확인한다.
            latest = jira.get_work_result(issue_key)
            if not _matches_result(latest, request):
                raise _conflict()
        return _save_confirmed(db, job_id, attempt, request, latest, changed_at, now)
    except JiraError as error:
        return _after_error(db, job_id, attempt, now, error, policy, write_rejected=write_rejected)


def _apply_request(jira: JiraClient, issue_key: str, request: TransitionRequest) -> None:
    if request.target is None:
        jira.update_final_result(issue_key, request.note)
        return
    # FIN에서 결과와 CLS를 함께 요청한 경우에는 닫기 전에 결과를 수정한다.
    if request.note is not None and request.target == "CLS":
        jira.update_final_result(issue_key, request.note)
    jira.transition_issue(issue_key, request.target, final_result=request.note)
    if request.note is not None and (request.source, request.target) == ("RDY", "WIP"):
        jira.update_final_result(issue_key, request.note)


def _validate_request(db: Session, job: IntegrationJob, ticket: Ticket | None) -> TransitionRequest:
    p = job.payload
    if ticket is None or not isinstance(p, dict):
        raise JiraError("invalid_job", "접수 또는 작업 입력이 없습니다.", retryable=False)
    required = {"ticketId", "receiptNo", "jiraKey", "fromStatus", "toStatus", "resolutionNote",
                "requestedBy", "requestedAt", "resolutionConfirmedAt"}
    if not required.issubset(p):
        raise JiraError("invalid_job", "작업 필수 항목이 없습니다.", retryable=False)
    if (p.get("ticketId") != ticket.id or p.get("receiptNo") != ticket.receipt_no
            or not ticket.jira_key or p.get("jiraKey") != ticket.jira_key):
        raise JiraError("invalid_job", "접수와 작업 식별자가 다릅니다.", retryable=False)
    source, target, note = p.get("fromStatus"), p.get("toStatus"), p.get("resolutionNote")
    if not isinstance(source, str) or (target is not None and not isinstance(target, str)):
        raise JiraError("invalid_job", "작업 상태 형식이 올바르지 않습니다.", retryable=False)
    if not (target is None and source in {"WIP", "FIN"}) and (source, target) not in BASIC_TRANSITIONS:
        raise JiraError("invalid_transition", "이번 실행기의 지원 전환이 아닙니다.", retryable=False)
    if (ticket.jira_sync_status != "SYNCED" or ticket.transition_status != "PENDING"
            or ticket.requested_work_status != target or ticket.work_status not in {source, target or source}):
        raise _conflict()
    if note is not None and (not isinstance(note, str) or not 1 <= len(note.strip()) <= 4000):
        raise JiraError("invalid_fields", "처리 결과가 올바르지 않습니다.", retryable=False)
    note = note.replace("\r\n", "\n").replace("\r", "\n").strip() if note is not None else None
    if target == "FIN":
        # 이전에 등록된 작업도 재완료 입력 규칙을 지켜야 한다. Jira 조회·쓰기 전에 막는다.
        if note is None and TicketRepository(db).has_reopened(ticket.id):
            raise JiraError("invalid_fields", "재완료 요청에 처리 결과가 필요합니다.", retryable=False)
        note = note or (ticket.resolution_note.replace("\r\n", "\n").replace("\r", "\n").strip()
                        if ticket.resolution_note else None)
    if (target is None or target == "FIN") and not note:
        raise JiraError("invalid_fields", "처리 결과가 필요합니다.", retryable=False)
    if note is not None and not 1 <= len(note) <= 4000:
        raise JiraError("invalid_fields", "처리 결과 길이가 올바르지 않습니다.", retryable=False)
    reason = p.get("reason")
    if reason is not None and (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000):
        raise JiraError("invalid_job", "작업 사유가 올바르지 않습니다.", retryable=False)
    actor = p.get("requestedBy")
    if type(actor) is not int or db.get(User, actor) is None:
        raise JiraError("invalid_job", "요청자가 없습니다.", retryable=False)
    requested_at = _timestamp(p.get("requestedAt"))
    confirmed_at = None
    if target == "CLS":
        confirmed_at = _timestamp(p.get("resolutionConfirmedAt"))
        inquiry = db.get(Inquiry, ticket.inquiry_id)
        if (inquiry is None or inquiry.user_id != actor or ticket.resolution_confirmed_at is None
                or confirmed_at != datetime_utils.as_utc(ticket.resolution_confirmed_at)):
            raise JiraError("confirmation_missing", "문의자 해결 확인 기록이 일치하지 않습니다.", retryable=False)
    return TransitionRequest(source, target, note, actor, requested_at, confirmed_at, reason)


def _timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as error:
        raise JiraError("invalid_job", "작업 시각이 올바르지 않습니다.", retryable=False) from error


def _matches_result(latest: dict, request: TransitionRequest) -> bool:
    return (latest["work_status"] == request.expected_status
            and (request.note is None or latest["final_result"] == request.note)
            and (request.expected_status not in {"FIN", "CLS"} or bool(latest["final_result"])))


def _conflict() -> JiraError:
    return JiraError("transition_conflict", "확인된 상태 또는 요청이 달라졌습니다.", retryable=False)


def _lock_owned(db: Session, job_id: int, attempt: int):
    job = db.get(IntegrationJob, job_id, with_for_update=True, populate_existing=True)
    if job is None or job.status != "RUNNING" or job.attempts != attempt:
        db.rollback()
        return None, None
    ticket = db.get(Ticket, job.ticket_id, with_for_update=True, populate_existing=True)
    return job, ticket


def _mark_write(db: Session, job_id: int, attempt: int, now: datetime) -> bool:
    job, ticket = _lock_owned(db, job_id, attempt)
    if job is None:
        return False
    _validate_request(db, job, ticket)
    job.last_error = VERIFY_ONLY + "write_started"
    job.updated_at = now
    db.commit()
    return True


def _save_confirmed(db, job_id, attempt, request, latest, changed_at, now) -> TransitionResult:
    job, ticket = _lock_owned(db, job_id, attempt)
    if job is None:
        return TransitionResult(job_id, "SKIPPED", "ownership_lost")
    _validate_request(db, job, ticket)
    if request.target is not None:
        existing = db.scalar(select(TicketStatusHistory.id).where(
            TicketStatusHistory.ticket_id == ticket.id,
            TicketStatusHistory.to_status == request.target,
            TicketStatusHistory.changed_at == changed_at,
        ))
        if existing is None:
            db.add(TicketStatusHistory(
                ticket_id=ticket.id, from_status=request.source, to_status=request.target,
                source="ITSSUE", actor_id=request.actor_id, reason=request.reason, changed_at=changed_at,
            ))
        if request.target == "FIN":
            ticket.finished_at = changed_at
        if request.target == "CLS":
            inquiry = db.get(Inquiry, ticket.inquiry_id, with_for_update=True, populate_existing=True)
            inquiry.resolution_result = "RESOLVED"
            inquiry.closed_at = request.confirmed_at
            inquiry.updated_at = now
            ticket.closed_at = request.confirmed_at
    ticket.work_status = request.expected_status
    ticket.resolution_note = latest["final_result"] or None
    ticket.work_status_confirmed_at = now
    ticket.requested_work_status = None
    ticket.transition_status = "IDLE"
    job.status, job.last_error, job.next_retry_at, job.updated_at = "DONE", None, None, now
    db.commit()
    return TransitionResult(job_id, "CONFIRMED")


def _after_error(db, job_id, attempt, now, error, policy, *, write_rejected=False) -> TransitionResult:
    job, ticket = _lock_owned(db, job_id, attempt)
    if job is None:
        return TransitionResult(job_id, "SKIPPED", "ownership_lost")
    ambiguous = error.reason == "result_unknown" or (
        (job.last_error or "").startswith(VERIFY_ONLY)
        and error.reason in {"timeout", "network", "server_error", "rate_limited"}
        and not write_rejected
    )
    failure = JiraError("result_unknown", "Jira 반영 여부 확인 필요", retryable=False) if ambiguous else error
    step = next_step(failure, job.attempts, policy=policy)
    job.last_error = (VERIFY_ONLY if ambiguous else "") + error.reason
    job.updated_at = now
    active_request = (ticket is not None and isinstance(job.payload, dict)
                      and ticket.transition_status == "PENDING"
                      and ticket.requested_work_status == job.payload.get("toStatus"))
    if step.action in {"RETRY", "VERIFY"}:
        job.status = "PENDING"
        job.next_retry_at = now + timedelta(seconds=step.delay_seconds)
        outcome = "VERIFY_SCHEDULED" if ambiguous else "RETRY_SCHEDULED"
    else:
        job.status, job.next_retry_at = "NEEDS_ADMIN", None
        if active_request:
            ticket.transition_status = "NEEDS_ADMIN"
        outcome = "NEEDS_ADMIN"
    db.commit()
    return TransitionResult(job_id, outcome, error.reason)


def run_due_jira_transition_jobs(db, jira, *, limit=10, now=None, policy=RetryPolicy()):
    now = now or datetime_utils.now()
    ids = db.scalars(select(IntegrationJob.id).where(
        IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    ).order_by(IntegrationJob.id).limit(limit)).all()
    return [run_jira_transition_job(db, jira, job_id, now=now, policy=policy) for job_id in ids]


def requeue_stale_transition_jobs(db, *, older_than=timedelta(minutes=5), now=None) -> int:
    """중단된 전환 작업은 조회 전용으로 복구한다. 생성용 VERIFYING으로 바꾸지 않는다."""
    now = now or datetime_utils.now()
    jobs = db.scalars(select(IntegrationJob).where(
        IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "RUNNING",
        IntegrationJob.updated_at < now - older_than,
    ).with_for_update()).all()
    for job in jobs:
        job.status, job.next_retry_at, job.updated_at = "PENDING", None, now
        job.last_error = VERIFY_ONLY + "stale_running"
    db.commit()
    return len(jobs)
