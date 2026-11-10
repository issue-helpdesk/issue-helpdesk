"""연동 재처리 (TK-12) — FAILED·NEEDS_ADMIN 원본 작업을 다시 등록하거나, Jira 에 이미 반영됐으면 복구한다.

새 작업은 원본 payload 를 그대로 복사하고 retry_of_job_id 로 원본을 가리킨다. 실제 실행은 실행기(worker)가 한다.
Jira 를 읽는 동안 행을 잠그지 않는다. 읽은 뒤 잠그고 상태를 다시 확인한다.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.integrations.jira import JiraClient, JiraError
from app.models import AssignmentLog, IntegrationJob, Ticket
from app.repositories.audit_log import AuditLogRepository
from app.repositories.ticket import TicketRepository
from app.services.jira_create import save_create_success, work_status_to_fill
from app.services.jira_fields import is_current
from app.services.jira_transition import matches_result, validate_request, run_jira_transition_job
from app.utils import datetime_utils

RETRYABLE = ("FAILED", "NEEDS_ADMIN")
LINKED_EXISTING = "LINKED_EXISTING"
ALREADY_APPLIED = "ALREADY_APPLIED"


def jira_opener() -> Callable[[], JiraClient]:
    return JiraClient.from_env


JiraOpenerDep = Annotated[Callable[[], JiraClient], Depends(jira_opener)]


@dataclass(frozen=True)
class RetryResult:
    job: IntegrationJob | None          # 새로 등록한 작업. 복구로 끝났으면 None
    recovery: str | None = None


def retry_job(
    db: Session,
    open_jira: Callable[[], JiraClient],
    ticket_id: int,
    source_id: int,
    *,
    actor_id: int,
    reason: str,
    now: datetime | None = None,
) -> RetryResult:
    """커밋까지 한다. 외부 결과를 확인할 수 없으면 상태를 바꾸지 않고 503 이다."""
    now = now or datetime_utils.now()
    ticket, source = load(db, ticket_id, source_id)
    context = (actor_id, reason, now)
    try:
        # 배정은 실행기가 Jira 담당자를 먼저 읽고 같으면 쓰지 않으므로 여기서 읽지 않는다
        if source.job_type == "JIRA_ASSIGN":
            return retry_assign(db, ticket_id, source_id, *context)
        # 필드 갱신은 같은 값을 다시 보내도 되므로 Jira 를 미리 읽지 않는다
        if source.job_type == "JIRA_UPDATE_FIELDS":
            return retry_fields(db, ticket_id, source_id, *context)
        with open_jira() as jira:
            if source.job_type == "JIRA_CREATE":
                return retry_create(db, jira, ticket_id, source_id, *context)
            return retry_transition(db, jira, ticket_id, source_id, *context)
    except JiraError as error:
        db.rollback()
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE) from error
    except IntegrityError as error:
        db.rollback()               # 같은 접수에 다른 요청이 먼저 작업을 등록했다
        raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS) from error


def load(db: Session, ticket_id: int, source_id: int, *, lock: bool = False) -> tuple[Ticket, IntegrationJob]:
    ticket = db.get(Ticket, ticket_id, with_for_update=lock, populate_existing=True)
    if ticket is None:
        raise AppError(ErrorCode.TICKET_NOT_FOUND)
    source = db.get(IntegrationJob, source_id, with_for_update=lock, populate_existing=True)
    if source is None or source.ticket_id != ticket.id:
        raise AppError(ErrorCode.NOT_FOUND)
    if source.status not in RETRYABLE:
        raise not_allowed("SOURCE_STATUS", "원본 작업 상태", source.status)
    # 같은 원본을 두 번 재처리하지 않는다. 재처리가 또 실패하면 그 작업을 지정한다
    if db.scalar(select(IntegrationJob.id).where(IntegrationJob.retry_of_job_id == source.id).limit(1)) is not None:
        raise not_allowed("ALREADY_RETRIED", "이미 재처리한 작업", source.id)
    if TicketRepository(db).has_active_job(ticket.id, source.job_type):
        raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS)
    return ticket, source


def retry_create(db, jira, ticket_id, source_id, actor_id, reason, now) -> RetryResult:
    ticket, source = load(db, ticket_id, source_id)
    check_create(ticket)
    found = jira.find_by_receipt(ticket.receipt_no)
    work_status = None
    if found is not None:
        found = {**found, "created": False, "source": "jira_lookup"}
        work_status = work_status_to_fill(jira, ticket, found)

    ticket, source = load(db, ticket_id, source_id, lock=True)
    check_create(ticket)
    if found is None:
        ticket.jira_sync_status = "PENDING"
        return register(db, ticket, source, actor_id, reason)
    audit(db, ticket, actor_id, reason, LINKED_EXISTING)
    # 생성 성공 때와 같게 저장한다 (jira_key·SYNCED·최초 자동배정 예약·커밋). 원본 작업은 DONE 이 된다
    saved = save_create_success(db, source, ticket, now, found, work_status)
    if saved.outcome == "NEEDS_ADMIN":          # 같은 jira_key 가 다른 접수에 있다
        raise not_allowed("JIRA_KEY", "다른 접수에 연결된 Jira", found["jira_key"])
    return RetryResult(None, LINKED_EXISTING)


def check_create(ticket: Ticket) -> None:
    if ticket.jira_key:
        raise AppError(ErrorCode.INTEGRATION_ALREADY_SYNCED, [
            {"reason": "JIRA_KEY", "message": "연동된 Jira", "value": ticket.jira_key},
        ])


def retry_assign(db, ticket_id, source_id, actor_id, reason, now) -> RetryResult:
    ticket, source = load(db, ticket_id, source_id, lock=True)
    p = payload_of(source)
    assignee_id = p.get("assigneeId")
    if ticket.assignment_revision != p.get("assignmentRevision"):
        raise not_allowed("ASSIGNMENT_REVISION", "현재 배정 revision", ticket.assignment_revision)
    if (ticket.assign_status != "NEEDS_ADMIN" or not assignee_id or ticket.group_id != p.get("groupId")
            or ticket.assignee_id not in (None, assignee_id)):
        raise not_allowed("ASSIGN_STATUS", "현재 배정 상태", ticket.assign_status)
    if ticket.assignee_id is None:              # 확실한 실패로 예약이 풀린 경우. 결과 불명확이면 예약이 남아 있다
        ticket.assignee_id = assignee_id
        db.add(AssignmentLog(ticket_id=ticket.id, event="ASSIGN", group_id=ticket.group_id, assignee_id=assignee_id,
                             actor_id=actor_id, reason=reason))
    ticket.assign_status = "PENDING"
    return register(db, ticket, source, actor_id, reason)


def retry_fields(db, ticket_id, source_id, actor_id, reason, now) -> RetryResult:
    ticket, source = load(db, ticket_id, source_id, lock=True)
    if not is_current(ticket, payload_of(source)):          # 그 뒤 분류가 또 바뀌었다. 옛 분류를 다시 보내지 않는다
        raise not_allowed("CLASSIFICATION", "현재 세부 유형", ticket.inquiry_type_id)
    return register(db, ticket, source, actor_id, reason)


def retry_transition(db, jira, ticket_id, source_id, actor_id, reason, now) -> RetryResult:
    ticket, source = load(db, ticket_id, source_id)
    check_transition(ticket, source)
    latest = jira.get_work_result(ticket.jira_key)

    ticket, source = load(db, ticket_id, source_id, lock=True)
    check_transition(ticket, source)
    ticket.transition_status = "PENDING"
    job = new_job(db, source)
    try:
        request = validate_request(db, job, ticket)
    except JiraError as error:
        db.rollback()
        raise not_allowed("TRANSITION", "재처리할 수 없는 요청", error.reason) from error
    applied = matches_result(latest, request)
    if not applied and latest["work_status"] != request.source:
        conflict = latest["work_status"]
        db.rollback()
        raise not_allowed("JIRA_STATUS", "Jira 현재 상태", conflict)
    audit(db, ticket, actor_id, reason, ALREADY_APPLIED if applied else "QUEUED")
    db.commit()
    if not applied:
        return RetryResult(job)

    # 이력·완료 시각·종결 저장은 실행기와 같아야 하므로 새 작업을 바로 실행한다. 이미 반영됐으니 쓰지 않는다
    result = run_jira_transition_job(db, jira, job.id, now=now)
    if result.outcome != "CONFIRMED":           # 실행기가 재시도·관리자 확인으로 이어간다
        return RetryResult(db.get(IntegrationJob, job.id, populate_existing=True))
    source = db.get(IntegrationJob, source_id, populate_existing=True)
    source.status, source.next_retry_at, source.updated_at = "DONE", None, now
    db.commit()
    return RetryResult(None, ALREADY_APPLIED)


def check_transition(ticket: Ticket, source: IntegrationJob) -> None:
    if ticket.transition_status != "NEEDS_ADMIN" or ticket.requested_work_status != payload_of(source).get("toStatus"):
        raise not_allowed("TRANSITION_STATUS", "상태 변경 작업 상태", ticket.transition_status)


def register(db: Session, ticket: Ticket, source: IntegrationJob, actor_id: int, reason: str) -> RetryResult:
    job = new_job(db, source)
    audit(db, ticket, actor_id, reason, "QUEUED")
    db.commit()
    return RetryResult(job)


def new_job(db: Session, source: IntegrationJob) -> IntegrationJob:
    """실행 키는 UNIQUE 라 새로 만든다. 앞부분에 원본 논리 작업 키를 남긴다 (06 연동 보완)."""
    logical_key = source.idempotency_key.split(":retry:")[0]
    job = IntegrationJob(ticket_id=source.ticket_id, job_type=source.job_type, status="PENDING", attempts=0,
                         idempotency_key=f"{logical_key}:retry:{source.id}", payload=source.payload,
                         retry_of_job_id=source.id)
    db.add(job)
    db.flush()
    return job


def audit(db: Session, ticket: Ticket, actor_id: int, reason: str, result: str) -> None:
    AuditLogRepository(db).add("INTEGRATION_RETRY", "ticket", ticket.id, result=result, actor_id=actor_id, reason=reason)


def payload_of(job: IntegrationJob) -> dict[str, Any]:
    return job.payload if isinstance(job.payload, dict) else {}


def not_allowed(detail_reason: str, message: str, value: Any) -> AppError:
    return AppError(ErrorCode.INTEGRATION_RETRY_NOT_ALLOWED, [{"reason": detail_reason, "message": message, "value": value}])
