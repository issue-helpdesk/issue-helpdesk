"""Jira 필드 갱신 작업(JIRA_UPDATE_FIELDS) — 접수 분류 변경(TK-15)을 이미 만든 Jira 이슈의 분류 칸에 반영한다.

payload 에 바꿀 칸(fields)과 그때의 세부 유형(inquiryTypeId)을 남긴다. 실행 시점의 tickets.inquiry_type_id 가
payload 와 다르면 그 뒤에 분류가 또 바뀐 것이므로 Jira 를 덮어쓰지 않고 STALE 로 끝낸다.

같은 값을 다시 보내도 결과가 같아서(멱등) 배정·상태 변경과 달리 조회 전용 복구 표식을 두지 않는다.
시간 초과·통신 오류는 그대로 재시도하고, 쓰기 뒤에는 다시 읽어 보낸 값과 같은지 확인한다.
담당자 변경은 같은 요청이 등록한 JIRA_ASSIGN 이 따로 처리한다.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.retry import RetryPolicy, next_step
from app.models import IntegrationJob, Ticket
from app.utils import datetime_utils

JOB_TYPE = "JIRA_UPDATE_FIELDS"
SUPERSEDED = "superseded:"
OPEN_FAILURE = ("FAILED", "NEEDS_ADMIN")
STALE = "stale_classification"
REQUIRED = {"ticketId", "receiptNo", "jiraKey", "inquiryTypeId", "fields", "requestedBy", "requestedAt"}


def enqueue_jira_update_fields(db: Session, ticket: Ticket, payload: dict[str, Any]) -> IntegrationJob:
    """flush 만 한다. 커밋은 호출자가 한다. 접수당 진행 중 필드 갱신 작업은 하나다 (uq_integration_jobs_one_active)."""
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0,
                         idempotency_key=f"fields:{uuid.uuid4()}", payload=payload)
    db.add(job)
    db.flush()
    return job


def supersede_field_failures(db: Session, ticket_id: int, now: datetime) -> int:
    """새 분류 변경으로 쓸모없어진 필드 갱신 실패 작업을 DONE 으로 닫는다. 커밋은 호출자가 한다.

    닫지 않으면 TK-12 로 옛 분류를 다시 보낼 수 있다. 원래 오류는 뒤에 남긴다.
    """
    retried = select(IntegrationJob.retry_of_job_id).where(IntegrationJob.retry_of_job_id.is_not(None))
    jobs = db.scalars(select(IntegrationJob).where(
        IntegrationJob.ticket_id == ticket_id, IntegrationJob.job_type == JOB_TYPE,
        IntegrationJob.status.in_(OPEN_FAILURE), IntegrationJob.id.not_in(retried),
    )).all()
    for job in jobs:
        job.status, job.next_retry_at, job.updated_at = "DONE", None, now
        job.last_error = f"{SUPERSEDED}reclassify" + (f" ({job.last_error})" if job.last_error else "")
    return len(jobs)


def is_current(ticket: Ticket | None, payload: Any) -> bool:
    """작업이 지금 접수의 분류·Jira 이슈와 같은지. 다르면 더 새 변경이 있다."""
    return (ticket is not None and isinstance(payload, dict)
            and ticket.id == payload.get("ticketId") and ticket.jira_key == payload.get("jiraKey")
            and ticket.inquiry_type_id == payload.get("inquiryTypeId"))


@dataclass(frozen=True)
class FieldsResult:
    job_id: int
    outcome: str            # UPDATED · STALE · RETRY_SCHEDULED · NEEDS_ADMIN · SKIPPED
    reason: str | None = None


def run_jira_update_fields_job(
    db: Session, jira: JiraClient, job_id: int, *, now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),
) -> FieldsResult:
    """한 작업을 선점·검증·쓰기·재조회 확인한다. payload 는 바꾸지 않는다."""
    now = now or datetime_utils.now()
    claimed = db.execute(update(IntegrationJob).where(
        IntegrationJob.id == job_id, IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    ).values(status="RUNNING", attempts=IntegrationJob.attempts + 1, updated_at=now)
      .execution_options(synchronize_session=False))
    db.commit()
    if claimed.rowcount != 1:
        return FieldsResult(job_id, "SKIPPED", "not_claimable")
    job = db.get(IntegrationJob, job_id, populate_existing=True)
    attempt, p = job.attempts, job.payload
    try:
        ticket = db.get(Ticket, job.ticket_id, populate_existing=True)
        _validate(ticket, p)
        diffs = jira.update_fields(p["jiraKey"], p["fields"])
        if diffs:
            raise JiraError("result_mismatch", f"Jira 저장값이 다릅니다: {', '.join(diffs)}", retryable=False)
        owned, ticket = _lock_owned(db, job_id, attempt)
        if owned is None:
            return FieldsResult(job_id, "SKIPPED", "ownership_lost")
        owned.status, owned.next_retry_at, owned.last_error, owned.updated_at = "DONE", None, None, now
        db.commit()
        return FieldsResult(job_id, "UPDATED")
    except JiraError as error:
        return _after_error(db, job_id, attempt, now, error, policy)


def _validate(ticket: Ticket | None, p: Any) -> None:
    if ticket is None or not isinstance(p, dict) or not REQUIRED.issubset(p):
        raise JiraError("invalid_job", "접수 또는 필드 갱신 작업 입력이 없습니다.", retryable=False)
    if not isinstance(p["fields"], dict) or not p["fields"]:
        raise JiraError("invalid_job", "고칠 Jira 칸이 없습니다.", retryable=False)
    if not isinstance(p["jiraKey"], str) or not p["jiraKey"].strip():
        raise JiraError("invalid_job", "Jira 키가 없습니다.", retryable=False)
    if not is_current(ticket, p):
        raise JiraError(STALE, "더 최신 분류 변경이 있습니다.", retryable=False)


def _lock_owned(db: Session, job_id: int, attempt: int):
    job = db.get(IntegrationJob, job_id, with_for_update=True, populate_existing=True)
    if job is None or job.status != "RUNNING" or job.attempts != attempt:
        db.rollback()
        return None, None
    return job, db.get(Ticket, job.ticket_id, with_for_update=True, populate_existing=True)


def _after_error(db, job_id, attempt, now, error, policy) -> FieldsResult:
    job, ticket = _lock_owned(db, job_id, attempt)
    if job is None:
        return FieldsResult(job_id, "SKIPPED", "ownership_lost")
    if error.reason == STALE or not is_current(ticket, job.payload):
        job.status, job.next_retry_at, job.last_error, job.updated_at = "DONE", None, STALE, now
        db.commit()
        return FieldsResult(job_id, "STALE", STALE)
    step = next_step(error, job.attempts, policy=policy)
    job.last_error, job.updated_at = error.reason, now
    if step.action in {"RETRY", "VERIFY"}:
        job.status, job.next_retry_at = "PENDING", now + timedelta(seconds=step.delay_seconds)
        outcome = "RETRY_SCHEDULED"
    else:
        job.status, job.next_retry_at = "NEEDS_ADMIN", None
        outcome = "NEEDS_ADMIN"
    db.commit()
    return FieldsResult(job_id, outcome, error.reason)


def run_due_jira_update_fields_jobs(db, jira, *, limit=10, now=None, policy=RetryPolicy()):
    now = now or datetime_utils.now()
    ids = db.scalars(select(IntegrationJob.id).where(
        IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    ).order_by(IntegrationJob.id).limit(limit)).all()
    return [run_jira_update_fields_job(db, jira, job_id, now=now, policy=policy) for job_id in ids]


def requeue_stale_field_jobs(db, *, older_than=timedelta(minutes=5), now=None, ticket_id: int | None = None):
    """중단된 필드 갱신 작업을 다시 PENDING 으로 돌린다. 같은 값을 다시 보내도 되므로 조회 전용 표식은 두지 않는다."""
    now = now or datetime_utils.now()
    jobs = db.scalars(select(IntegrationJob).where(
        IntegrationJob.job_type == JOB_TYPE,
        True if ticket_id is None else IntegrationJob.ticket_id == ticket_id,
        IntegrationJob.status == "RUNNING",
        IntegrationJob.updated_at < now - older_than,
    ).with_for_update()).all()
    for job in jobs:
        job.status, job.next_retry_at, job.last_error, job.updated_at = "PENDING", None, "stale_running", now
    db.commit()
    return len(jobs)
