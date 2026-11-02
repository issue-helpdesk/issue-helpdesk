"""Jira 개인 담당자 배정 작업(JIRA_ASSIGN) 등록 — TK-09 배정·재배정을 연동 작업 큐에 넣는다.

payload 에 그룹·담당자·assignment_revision 을 남긴다. 실행기는 실행 시점의 tickets.assignment_revision 과
payload 의 값이 다르면 더 새 배정이 있는 것이므로 Jira 를 바꾸지 않는다 (06 연동 보완).

저장된 예약의 공통 자격을 다시 확인한 뒤 미배정 Jira 지정·재조회·DB 확정을 수행한다.
다른 Jira 담당자가 있으면 변경 전 담당자 정보가 없는 현재 payload로 덮어쓰지 않는다.
후보 선정·최초 자동배정·worker 등록은 별도 연결한다.
"""
import uuid
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.mapper import work_status_from_jira
from app.integrations.jira.retry import RetryPolicy, next_step
from app.models import (AssignmentLog, Inquiry, InquiryType, IntegrationJob, MemberSkill,
                        SupportGroup, SupportGroupMember, Ticket, User)
from app.utils import datetime_utils

JOB_TYPE = "JIRA_ASSIGN"


def enqueue_jira_assign(db: Session, ticket: Ticket, payload: dict[str, Any]) -> IntegrationJob:
    """flush 만 한다. 커밋은 호출자가 한다. 접수당 진행 중 배정 작업은 하나다 (uq_integration_jobs_one_active)."""
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0,
                         idempotency_key=f"assign:{uuid.uuid4()}", payload=payload)
    db.add(job)
    db.flush()
    return job


VERIFY_ONLY = "verify_only:"


@dataclass(frozen=True)
class AssignmentResult:
    job_id: int
    outcome: str
    reason: str | None = None


def run_jira_assign_job(
    db: Session, jira: JiraClient, job_id: int, *, now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),
) -> AssignmentResult:
    """TK-09가 검증·예약한 JIRA_ASSIGN 한 건을 처리한다. payload는 변경하지 않는다.

    외부 쓰기 전 조회 전용 복구 표식을 커밋한다. 결과가 불명확하거나 실행 중단 뒤에는
    PUT을 재전송하지 않고 조회만 한다. 같은 accountId가 이미 있으면 PUT하지 않는다.
    """
    now = now or datetime_utils.now()
    claimed = db.execute(update(IntegrationJob).where(
        IntegrationJob.id == job_id, IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    ).values(status="RUNNING", attempts=IntegrationJob.attempts + 1, updated_at=now)
      .execution_options(synchronize_session=False))
    db.commit()
    if claimed.rowcount != 1:
        return AssignmentResult(job_id, "SKIPPED", "not_claimable")
    job = db.get(IntegrationJob, job_id, populate_existing=True)
    attempt, p = job.attempts, job.payload
    rejected = False
    try:
        ticket = db.get(Ticket, job.ticket_id, populate_existing=True)
        _validate(db, jira, job, ticket)
        key, account = p["jiraKey"], p["jiraAccountId"].strip()
        actual = _read_assignment(jira, key)
        if actual is not None and actual != account:
            raise JiraError("assignment_source_unconfirmed", "다른 담당자를 임의로 덮어쓰지 않습니다.", retryable=False)
        if actual != account:
            if (job.last_error or "").startswith(VERIFY_ONLY):
                raise JiraError("result_unknown", "앞선 지정 결과를 확인 중입니다.", retryable=False)
            owned, latest_ticket = _lock_owned(db, job_id, attempt)
            if owned is None:
                return AssignmentResult(job_id, "SKIPPED", "ownership_lost")
            _validate(db, jira, owned, latest_ticket)
            owned.last_error, owned.updated_at = VERIFY_ONLY + "write_started", now
            db.commit()
            try:
                jira.set_assignee(key, account)
            except JiraError as error:
                rejected = error.reason in {"invalid_fields", "auth", "not_found", "rate_limited"}
                raise
            actual = _read_assignment(jira, key)
            if actual != account:
                raise JiraError("result_unknown", "Jira 지정 결과가 아직 일치하지 않습니다.", retryable=False)
        owned, latest_ticket = _lock_owned(db, job_id, attempt)
        if owned is None:
            return AssignmentResult(job_id, "SKIPPED", "ownership_lost")
        _validate(db, jira, owned, latest_ticket)
        inquiry = db.get(Inquiry, latest_ticket.inquiry_id, with_for_update=True, populate_existing=True)
        latest_ticket.assign_status = "ASSIGNED"
        if inquiry.status == "RECEIVED":
            inquiry.status, inquiry.updated_at = "HANDED_OFF", now
        # TK-09가 남긴 ASSIGN/REASSIGN 예약 이력은 다시 추가하지 않는다.
        owned.status, owned.next_retry_at, owned.last_error, owned.updated_at = "DONE", None, None, now
        db.commit()
        return AssignmentResult(job_id, "ASSIGNED")
    except JiraError as error:
        return _after_error(db, job_id, attempt, now, error, policy, rejected=rejected)


def _validate(db: Session, jira: JiraClient, job: IntegrationJob, ticket: Ticket | None) -> None:
    p = job.payload
    required = {"ticketId", "receiptNo", "jiraKey", "groupId", "assigneeId", "jiraAccountId",
                "assignmentRevision", "requestedBy", "requestedAt"}
    if ticket is None or not isinstance(p, dict) or not required.issubset(p):
        raise JiraError("invalid_job", "접수 또는 배정 작업 입력이 없습니다.", retryable=False)
    for key in ("ticketId", "groupId", "assigneeId", "assignmentRevision"):
        if type(p[key]) is not int or p[key] <= 0:
            raise JiraError("invalid_job", "배정 식별자가 올바르지 않습니다.", retryable=False)
    if p["requestedBy"] is not None and (type(p["requestedBy"]) is not int or p["requestedBy"] <= 0):
        raise JiraError("invalid_job", "배정 요청자가 올바르지 않습니다.", retryable=False)
    if ticket.assignment_revision != p["assignmentRevision"]:
        raise JiraError("stale_assignment", "더 최신 배정이 있습니다.", retryable=False)
    if (ticket.id != p["ticketId"] or ticket.receipt_no != p["receiptNo"]
            or ticket.jira_key != p["jiraKey"] or ticket.group_id != p["groupId"]
            or ticket.assignee_id != p["assigneeId"]):
        raise JiraError("reservation_mismatch", "작업과 현재 배정 예약이 다릅니다.", retryable=False)
    prefix = re.escape(str(jira.mapping["project"]["key"]))
    if not isinstance(p["jiraKey"], str) or not re.fullmatch(prefix + r"-[1-9]\d*", p["jiraKey"]):
        raise JiraError("invalid_job", "현재 프로젝트의 Jira 키가 아닙니다.", retryable=False)
    if (ticket.jira_sync_status != "SYNCED" or ticket.work_status not in {"RDY", "WIP", "FIN"}
            or ticket.assign_status not in {"PENDING", "ASSIGNED"}):
        raise JiraError("assignment_not_allowed", "현재 접수 상태에서는 배정할 수 없습니다.", retryable=False)
    if not isinstance(p["jiraAccountId"], str) or not p["jiraAccountId"].strip():
        raise JiraError("invalid_job", "Jira 계정이 없습니다.", retryable=False)
    try:
        requested_at = datetime.fromisoformat(p["requestedAt"].replace("Z", "+00:00"))
        if requested_at.tzinfo is None:
            raise ValueError("timezone missing")
    except (AttributeError, TypeError, ValueError) as error:
        raise JiraError("invalid_job", "요청 시각이 올바르지 않습니다.", retryable=False) from error
    group = db.get(SupportGroup, ticket.group_id, populate_existing=True)
    user = db.get(User, ticket.assignee_id, populate_existing=True)
    member = db.get(SupportGroupMember, (ticket.group_id, ticket.assignee_id), populate_existing=True)
    kind = db.get(InquiryType, ticket.inquiry_type_id, populate_existing=True) if ticket.inquiry_type_id else None
    inquiry = db.get(Inquiry, ticket.inquiry_id, populate_existing=True)
    if (not group or not group.is_active or not user or user.account_status != "ACTIVE"
            or user.service_role not in {"AGENT", "ADMIN"} or not member or not member.is_active
            or not member.assignable or not kind or not kind.is_active
            or db.get(MemberSkill, (user.id, kind.id), populate_existing=True) is None
            or not inquiry or inquiry.status not in {"RECEIVED", "HANDED_OFF"}
            or (p["requestedBy"] is not None and db.get(User, p["requestedBy"]) is None)):
        raise JiraError("ineligible_assignee", "현재 배정 공통 자격을 충족하지 않습니다.", retryable=False)
    if (member.jira_account_id or "").strip() != p["jiraAccountId"].strip():
        raise JiraError("account_mapping_changed", "작업 등록 후 Jira 계정 연결이 바뀌었습니다.", retryable=False)


def _read_assignment(jira: JiraClient, key: str) -> str | None:
    fields = jira.get_issue(key, ["status", "assignee"])["fields"]
    if not isinstance(fields, dict) or "status" not in fields or "assignee" not in fields:
        raise JiraError("incomplete_jira_assignment", "Jira 상태·담당자 조회가 불완전합니다.", retryable=False)
    status = work_status_from_jira((fields.get("status") or {}).get("id"), jira.mapping)
    if status not in {"RDY", "WIP", "FIN"}:
        raise JiraError("jira_status_not_assignable", "종결 또는 알 수 없는 Jira 상태입니다.", retryable=False)
    who = fields.get("assignee")
    if who is None:
        return None
    account = who.get("accountId") if isinstance(who, dict) else None
    if not isinstance(account, str) or not account.strip():
        raise JiraError("unknown_assignee", "Jira 담당자 계정을 확인할 수 없습니다.", retryable=False)
    return account.strip()


def _lock_owned(db, job_id, attempt):
    job = db.get(IntegrationJob, job_id, with_for_update=True, populate_existing=True)
    if job is None or job.status != "RUNNING" or job.attempts != attempt:
        db.rollback()
        return None, None
    return job, db.get(Ticket, job.ticket_id, with_for_update=True, populate_existing=True)


def _same_reservation(ticket, payload) -> bool:
    return (ticket is not None and isinstance(payload, dict)
            and ticket.id == payload.get("ticketId") and ticket.receipt_no == payload.get("receiptNo")
            and ticket.jira_key == payload.get("jiraKey")
            and ticket.assignment_revision == payload.get("assignmentRevision")
            and ticket.group_id == payload.get("groupId") and ticket.assignee_id == payload.get("assigneeId"))


def _after_error(db, job_id, attempt, now, error, policy, *, rejected=False):
    job, ticket = _lock_owned(db, job_id, attempt)
    if job is None:
        return AssignmentResult(job_id, "SKIPPED", "ownership_lost")
    p = job.payload
    if (error.reason == "stale_assignment" or (ticket is not None and isinstance(p, dict)
            and type(p.get("assignmentRevision")) is int and ticket.assignment_revision != p["assignmentRevision"])):
        job.status, job.next_retry_at, job.last_error, job.updated_at = "DONE", None, "stale_assignment", now
        db.commit()
        return AssignmentResult(job_id, "STALE", "stale_assignment")
    uncertain = error.reason == "result_unknown" or ((job.last_error or "").startswith(VERIFY_ONLY) and not rejected)
    transient = error.reason in {"result_unknown", "timeout", "network", "server_error", "rate_limited"}
    failure = JiraError("result_unknown", "배정 결과 확인 필요", retryable=False) if uncertain and transient else error
    step = next_step(failure, job.attempts, policy=policy)
    job.last_error = (VERIFY_ONLY if uncertain else "") + error.reason
    job.updated_at = now
    if step.action in {"RETRY", "VERIFY"}:
        job.status = "PENDING"
        job.next_retry_at = now + timedelta(seconds=step.delay_seconds)
        outcome = "VERIFY_SCHEDULED" if uncertain else "RETRY_SCHEDULED"
    else:
        job.status, job.next_retry_at = "NEEDS_ADMIN", None
        if _same_reservation(ticket, p):
            target_id = ticket.assignee_id
            ticket.assign_status = "NEEDS_ADMIN"
            if not uncertain:
                ticket.assignee_id = None  # 확실한 실패만 예약 해제. 결과 불명확이면 보존한다.
            db.add(AssignmentLog(ticket_id=ticket.id, event="FAIL", group_id=ticket.group_id,
                                 assignee_id=target_id, actor_id=None,
                                 reason=f"Jira 배정 실행 실패: {error.reason}"))
        outcome = "NEEDS_ADMIN"
    db.commit()
    return AssignmentResult(job_id, outcome, error.reason)


def run_due_jira_assign_jobs(db, jira, *, limit=10, now=None, policy=RetryPolicy()):
    now = now or datetime_utils.now()
    ids = db.scalars(select(IntegrationJob.id).where(
        IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    ).order_by(IntegrationJob.id).limit(limit)).all()
    return [run_jira_assign_job(db, jira, job_id, now=now, policy=policy) for job_id in ids]


def requeue_stale_assign_jobs(db, *, older_than=timedelta(minutes=5), now=None):
    """중단된 배정 작업만 조회 전용으로 복구한다. 생성·상태 변경 작업은 건드리지 않는다."""
    now = now or datetime_utils.now()
    jobs = db.scalars(select(IntegrationJob).where(
        IntegrationJob.job_type == JOB_TYPE, IntegrationJob.status == "RUNNING",
        IntegrationJob.updated_at < now - older_than,
    ).with_for_update()).all()
    for job in jobs:
        job.status, job.next_retry_at, job.last_error, job.updated_at = "PENDING", None, VERIFY_ONLY + "stale_running", now
    db.commit()
    return len(jobs)
