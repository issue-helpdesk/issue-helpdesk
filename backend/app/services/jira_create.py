"""Jira 이슈 생성 작업(JIRA_CREATE) 처리 — 접수(Ticket)를 Jira ITHD 이슈로 만들고 결과를 DB에 남긴다.

흐름
    TK-04(접수 확정)  →  enqueue_jira_create()      같은 트랜잭션에서 작업 1건 등록(커밋은 호출자)
    작업 실행        →  run_jira_create_job()       작업 선점 → Jira 호출 → jira_key·상태 저장
                       run_due_jira_create_jobs()   실행 시각이 된 작업을 모아서 실행
                       requeue_stale_running_jobs() 죽은 실행(RUNNING 방치)을 다시 대기로

DB 상태 규칙 (docs/06 integration_jobs·tickets.jira_sync_status)
    성공(새로 만듦·기존 이슈 연결·이미 저장됨)  job DONE · ticket SYNCED · jira_key 저장 · work_status 채움(아래)
    재시도 가능 오류                             job PENDING(next_retry_at 지정) · ticket PENDING 유지
    생성 결과 불명확(result_unknown)             job PENDING · ticket VERIFYING — 이후에는 "찾기"만 하고 다시 만들지 않는다
    재시도 불가·횟수 초과·접수 데이터 오류       job NEEDS_ADMIN · ticket NEEDS_ADMIN

업무 상태(work_status)는 접수(TK-04)에서 null로 저장되고 "Jira 생성 직후 RDY로 채운다"(docs/06·docs/api/03).
    새로 만들었으면 RDY, 기존 이슈에 연결하거나 jira_key만 있고 값이 비어 있으면 Jira의 현재 상태를 읽어 그 값으로 채운다.
    이미 값이 있으면 건드리지 않는다(상태 동기화의 몫). 상태 조회가 실패하면 일반 Jira 오류처럼 재시도한다.

중복 생성 방어는 세 겹이다.
    1) 작업 선점은 조건부 UPDATE(status=PENDING → RUNNING) 한 번이라 두 실행기가 같은 작업을 동시에 잡지 못한다.
    2) 생성 직전 Jira를 접수번호로 먼저 검색한다(JiraClient.create_ticket 안에서 수행).
    3) VERIFYING 상태에서는 생성 호출 자체를 하지 않는다.

한계(팀 확인 필요)
    - 이 모듈은 Jira만 호출한다. 개인 담당자 배정(JIRA_ASSIGN)·상태 전환은 다른 작업이다.
    - 생성 내용은 integration_jobs.payload의 등록 시점 값을 쓴다. jiraKey·jiraSyncStatus만 최신 Ticket에서 읽는다.
      과거 마이그레이션의 빈 payload({})는 현재 DB 값으로 처리하며 경고를 남긴다. 원래 등록값의 복원은 아니다.
    - 실행기가 Jira 응답 직후 DB 저장 전에 죽으면 작업이 RUNNING으로 남는다. requeue_stale_running_jobs()가
      이를 VERIFYING 경로(찾기만)로 되돌린다. 독립 실행기(integrations/jira/worker.py)가 주기 호출하며,
      실제 서버의 실행기 배포·프로세스 관리는 별도로 연결해야 한다.
    - 재시도 대기 시간·횟수는 retry.RetryPolicy의 제안값(60·300·900초, 3회)을 그대로 쓴다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.confirmed_ticket import ConfirmedTicketError, create_from_confirmed_ticket
from app.integrations.jira.retry import RetryPolicy, next_step
from app.models import Category, Inquiry, InquiryType, IntegrationJob, SupportGroup, Ticket, User
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

JOB_TYPE = "JIRA_CREATE"


@dataclass(frozen=True)
class JobResult:
    """작업 1건을 실행한 결과. outcome 값은 아래 중 하나다.

    CREATED(새 이슈) · LINKED(Jira에 이미 있던 이슈 연결) · SAVED(DB에 이미 jira_key가 있음)
    RETRY_SCHEDULED · VERIFY_SCHEDULED · NEEDS_ADMIN · SKIPPED(선점 실패·실행 시각 전·없는 작업)
    """

    job_id: int
    outcome: str
    job_status: str | None = None
    ticket_status: str | None = None
    jira_key: str | None = None
    reason: str | None = None


# ------------------------------------------------------------------ 등록

def enqueue_jira_create(db: Session, ticket: Ticket) -> IntegrationJob:
    """접수 1건의 Jira 생성 작업을 등록한다. 이미 있으면 그 작업을 돌려준다(접수번호당 1건).

    flush만 한다. 커밋은 접수(Ticket) 저장과 같은 트랜잭션으로 호출자가 한다.
    두 요청이 동시에 처음 등록하면 두 번째는 idempotency_key 중복으로 IntegrityError가 난다.
    """
    key = f"create:{ticket.receipt_no}"
    existing = db.scalars(select(IntegrationJob).where(IntegrationJob.idempotency_key == key)).first()
    if existing is not None:
        return existing
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0, idempotency_key=key,
                         payload=_ticket_payload(db, ticket))     # 등록 시점 스냅샷 (06 v0.8)
    db.add(job)
    db.flush()
    return job


# ------------------------------------------------------------------ 실행

def run_jira_create_job(
    db: Session,
    jira: JiraClient,
    job_id: int,
    *,
    now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),
) -> JobResult:
    """작업 1건을 선점해서 실행하고, 결과를 DB에 커밋한다.

    JiraError·ConfirmedTicketError는 여기서 상태로 바꾼다. 그 밖의 예외(코드 오류·DB 오류)는 그대로 올라가며
    작업은 RUNNING으로 남는다 — requeue_stale_running_jobs()가 찾기 전용 경로로 되돌린다.
    """
    now = now or datetime_utils.now()
    if not _claim(db, job_id, now):
        return JobResult(job_id, "SKIPPED", reason="not_claimable")

    job = db.get(IntegrationJob, job_id)
    ticket = db.get(Ticket, job.ticket_id)
    if ticket is None:
        return _needs_admin(db, job, None, now, "ticket_not_found")

    try:
        if ticket.jira_sync_status == "VERIFYING":
            # 생성 결과를 모르는 접수: 다시 만들지 않고 Jira에서 찾기만 한다.
            found = jira.find_by_receipt(ticket.receipt_no)
            if found is None:
                raise JiraError("result_unknown", "Jira에서 아직 찾지 못했습니다.", retryable=False)
            result = {**found, "created": False, "source": "jira_lookup"}
        else:
            if not isinstance(job.payload, dict):
                raise ConfirmedTicketError("invalid_type", ("payload",))
            if job.payload:
                data = dict(job.payload)
            else:
                # 마이그레이션 전 작업에는 등록 시점 입력이 없다. 이 경우에만 현재 DB 값으로 처리한다.
                logger.warning("jira create job %s uses legacy empty payload", job.id)
                data = _ticket_payload(db, ticket)
            # 접수 내용은 보존하고, 중복 생성 방지에 쓰는 제어값만 최신 상태로 확인한다.
            data.update(jiraKey=ticket.jira_key, jiraSyncStatus=ticket.jira_sync_status)
            result = create_from_confirmed_ticket(jira, data)
        work_status = _work_status_to_fill(jira, ticket, result)
    except ConfirmedTicketError as e:
        return _needs_admin(db, job, ticket, now, f"{e.reason}: {', '.join(e.fields)}")
    except JiraError as e:
        return _after_jira_error(db, job, ticket, now, e, policy)

    return _save_success(db, job, ticket, now, result, work_status)


def _work_status_to_fill(jira: JiraClient, ticket: Ticket, result: dict[str, Any]) -> str | None:
    """비어 있는 work_status에 넣을 값. 채울 필요가 없거나 Jira 상태가 매핑에 없으면 None."""
    if ticket.work_status is not None:
        return None
    if result.get("created"):
        return "RDY"
    return jira.get_work_status(result["jira_key"])["work_status"]


def run_due_jira_create_jobs(
    db: Session,
    jira: JiraClient,
    *,
    limit: int = 10,
    now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),
) -> list[JobResult]:
    """실행 시각이 된 JIRA_CREATE 작업을 오래된 순서로 최대 limit건 실행한다."""
    now = now or datetime_utils.now()
    ids = db.scalars(
        select(IntegrationJob.id)
        .where(IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING", _is_due(now))
        .order_by(IntegrationJob.id)
        .limit(limit)
    ).all()
    return [run_jira_create_job(db, jira, job_id, now=now, policy=policy) for job_id in ids]


def requeue_stale_running_jobs(
    db: Session,
    *,
    older_than: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> int:
    """RUNNING으로 오래 방치된 작업을 다시 대기시킨다. 돌려주는 값은 되돌린 작업 수.

    Jira를 호출하다 죽었을 수 있으므로 접수를 VERIFYING으로 바꿔, 다음 실행은 새로 만들지 않고 찾기만 한다.
    """
    now = now or datetime_utils.now()
    stale = db.scalars(
        select(IntegrationJob).where(
            IntegrationJob.job_type == JOB_TYPE,
            IntegrationJob.status == "RUNNING",
            IntegrationJob.updated_at < now - older_than,
        )
    ).all()
    for job in stale:
        job.status = "PENDING"
        job.next_retry_at = None
        job.updated_at = now
        job.last_error = "stale_running"
        ticket = db.get(Ticket, job.ticket_id)
        if ticket is not None and ticket.jira_sync_status == "PENDING":
            ticket.jira_sync_status = "VERIFYING"
    db.commit()
    return len(stale)


# ------------------------------------------------------------------ 내부

def _is_due(now: datetime):
    return or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now)


def _claim(db: Session, job_id: int, now: datetime) -> bool:
    """PENDING이고 실행 시각이 된 작업을 RUNNING으로 바꾸는 조건부 UPDATE. 성공한 쪽만 True."""
    result = db.execute(
        update(IntegrationJob)
        .where(
            IntegrationJob.id == job_id,
            IntegrationJob.job_type == JOB_TYPE,
            IntegrationJob.status == "PENDING",
            _is_due(now),
        )
        .values(status="RUNNING", attempts=IntegrationJob.attempts + 1, updated_at=now)
        # 바로 커밋하고 다시 읽는다. 세션 안 객체를 파이썬에서 재평가하지 않게 한다(시간대 없는 값 비교 오류 방지).
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _ticket_payload(db: Session, ticket: Ticket) -> dict[str, Any]:
    """Ticket 행을 TK-04 응답 모양(camelCase)으로 만든다. create_from_confirmed_ticket 이 이 모양을 받는다.

    값이 비어 있으면 그대로 None으로 넘긴다. 필수값 누락은 ConfirmedTicketError가 잡는다(추측하지 않는다).
    """
    group = db.get(SupportGroup, ticket.group_id) if ticket.group_id else None
    category = db.get(Category, ticket.category_code) if ticket.category_code else None
    inquiry_type = db.get(InquiryType, ticket.inquiry_type_id) if ticket.inquiry_type_id else None
    inquiry = db.get(Inquiry, ticket.inquiry_id)
    requester = db.get(User, inquiry.user_id) if inquiry is not None else None
    return {
        "id": ticket.id,
        "draftId": ticket.draft_id,
        "receiptNo": ticket.receipt_no,
        "summary": ticket.summary,
        "categoryCode": ticket.category_code,
        "urgency": ticket.urgency,
        "category": {"code": category.code, "name": category.name} if category else None,
        "inquiryType": (
            {"id": inquiry_type.id, "code": inquiry_type.code, "name": inquiry_type.name} if inquiry_type else None
        ),
        "groupId": ticket.group_id,
        "group": {"id": group.id, "name": group.name} if group else None,
        "targetSystem": ticket.target_system,
        "symptom": ticket.symptom,
        "occurredAt": ticket.occurred_at,
        "businessImpact": ticket.business_impact,
        "triedActions": ticket.tried_actions,
        "urgencyReason": ticket.urgency_reason,
        "requester": (
            {"id": requester.id, "employeeNo": requester.employee_no, "name": requester.name} if requester else None
        ),
        "jiraSyncStatus": ticket.jira_sync_status,
        "jiraKey": ticket.jira_key,
    }


def _save_success(
    db: Session, job: IntegrationJob, ticket: Ticket, now: datetime, result: dict[str, Any], work_status: str | None = None
) -> JobResult:
    key = result["jira_key"]
    ticket.jira_key = key
    ticket.jira_sync_status = "SYNCED"
    if work_status is not None:
        ticket.work_status = work_status
    job.status = "DONE"
    job.next_retry_at = None
    job.last_error = None
    job.updated_at = now
    job_id, ticket_id = job.id, ticket.id
    try:
        db.commit()
    except IntegrityError:
        # 같은 jira_key가 다른 접수에 이미 저장돼 있다. 어느 쪽이 맞는지는 사람이 본다.
        db.rollback()
        return _needs_admin(
            db, db.get(IntegrationJob, job_id), db.get(Ticket, ticket_id), now, "jira_key_conflict"
        )

    if result.get("source") == "saved_ticket":
        outcome = "SAVED"
    elif result.get("created"):
        outcome = "CREATED"
    else:
        outcome = "LINKED"
    logger.info("jira create job %s ticket %s → %s %s", job_id, ticket_id, outcome, key)
    return JobResult(job_id, outcome, "DONE", "SYNCED", key)


def _after_jira_error(
    db: Session, job: IntegrationJob, ticket: Ticket, now: datetime, error: JiraError, policy: RetryPolicy
) -> JobResult:
    # elapsed 는 넘기지 않는다(0). 실패 첫 시각을 저장하지 않으므로 횟수(attempts)로만 끊는다.
    step = next_step(error, job.attempts, 0, policy)
    job.last_error = _error_text(error)
    job.updated_at = now

    if error.reason == "result_unknown":
        ticket.jira_sync_status = "VERIFYING"

    if step.action in ("RETRY", "VERIFY"):
        job.status = "PENDING"
        job.next_retry_at = now + timedelta(seconds=step.delay_seconds)
        outcome = "RETRY_SCHEDULED" if step.action == "RETRY" else "VERIFY_SCHEDULED"
    else:
        job.status = "NEEDS_ADMIN"
        job.next_retry_at = None
        ticket.jira_sync_status = "NEEDS_ADMIN"
        outcome = "NEEDS_ADMIN"

    job_id, job_status, ticket_status = job.id, job.status, ticket.jira_sync_status
    db.commit()
    logger.warning("jira create job %s → %s (%s)", job_id, outcome, error.reason)
    return JobResult(job_id, outcome, job_status, ticket_status, reason=error.reason)


def _needs_admin(
    db: Session, job: IntegrationJob, ticket: Ticket | None, now: datetime, reason: str
) -> JobResult:
    job.status = "NEEDS_ADMIN"
    job.next_retry_at = None
    job.last_error = reason[:200]
    job.updated_at = now
    if ticket is not None:
        ticket.jira_sync_status = "NEEDS_ADMIN"
    job_id = job.id
    ticket_status = ticket.jira_sync_status if ticket is not None else None
    db.commit()
    logger.warning("jira create job %s → NEEDS_ADMIN (%s)", job_id, reason)
    return JobResult(job_id, "NEEDS_ADMIN", "NEEDS_ADMIN", ticket_status, reason=reason)


def _error_text(error: JiraError) -> str:
    """last_error 에는 이유와 HTTP 코드만 남긴다. Jira 응답 본문은 접수 내용이 섞일 수 있어 넣지 않는다."""
    if error.status_code:
        return f"{error.reason} (HTTP {error.status_code})"
    return error.reason
