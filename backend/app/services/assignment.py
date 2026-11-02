"""담당자 배정 공용 함수 — 후보 선정·예약·revision·배정 이력·JIRA_ASSIGN 작업 등록 (docs/11 2.3~2.5, 3장).

부르는 곳
    TK-09 담당자 지정·재배정   권한·사유·종료 여부를 확인한 뒤 부르고, 감사 로그·커밋은 TK-09 가 한다
    Jira 생성 직후 자동배정    실행기가 생성 결과를 저장한 뒤 자기 트랜잭션에서 부르고 커밋한다

    reservation = reserve_assignment(db, ticket, ticket.group_id, reason="최초 자동배정", actor_id=None)
    db.commit()

이 함수는 flush 만 하고 커밋하지 않는다. 같은 접수에 진행 중 배정 작업이 이미 있으면
작업 등록에서 IntegrityError 가 난다 (uq_integration_jobs_one_active). 부르는 쪽이 롤백한다.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.jira import Member, pick_assignee
from app.models import AssignmentLog, InquiryType, IntegrationJob, Ticket
from app.repositories.assignment import AssignmentRepository
from app.services.jira_assign import enqueue_jira_assign
from app.services.time_off import current_absentees
from app.utils import datetime_utils


class AssigneeNotAssignable(Exception):
    """직접 지정한 사람이 배정 자격이 없다. message 는 빠진 이유 ("Jira 계정 없음" 등)."""


@dataclass(frozen=True)
class Reservation:
    event: str                          # 배정 이력 이벤트: ASSIGN · REASSIGN · FAIL
    assignee_id: int | None
    reason: str                         # 배정 이력 reason
    job: IntegrationJob | None          # Jira 이슈가 없거나 담당자가 없으면 None


def reserve_assignment(
    db: Session,
    ticket: Ticket,
    group_id: int,
    *,
    reason: str,
    actor_id: int | None,
    assignee_id: int | None = None,
    now: datetime | None = None,
) -> Reservation:
    """group_id 의 담당자로 예약한다 (assignee_id 입력 + assign_status = PENDING).

    - assignee_id 가 있으면 직접 지정: 공통 자격만 본다. 팀장·부재 제외는 적용하지 않는다 (docs/11 3.1)
    - 없으면 자동 선정: pick_assignee (업무량 → 마지막 배정 → 사번). now 시점의 부재자를 뺀다
    - 후보가 없거나 미분류면 담당자를 비우고 NEEDS_ADMIN, 배정 이력 FAIL (docs/11 2.5)
    - assignment_revision 을 올려 이전 판단으로 만든 작업이 새 배정을 덮어쓰지 못하게 한다
    """
    repo = AssignmentRepository(db)
    repo.lock_group(group_id)
    inquiry_type = db.get(InquiryType, ticket.inquiry_type_id) if ticket.inquiry_type_id else None
    scenario = inquiry_type.code if inquiry_type else None
    members = {m.user_id: m for m in repo.members(group_id, exclude_ticket_id=ticket.id)}

    if assignee_id is not None:
        problem = manual_problem(members.get(assignee_id), scenario)
        if problem:
            raise AssigneeNotAssignable(problem)
        chosen, log_reason = members[assignee_id], reason
    else:
        decision = pick_assignee(members.values(), scenario, exclude_user_ids=current_absentees(db, now))
        chosen = members[decision.user_id] if decision.selected else None
        log_reason = f"{reason} (자동배정: {decision.reason})" if chosen else f"{reason} ({decision.reason})"

    previous = ticket.assignee_id
    ticket.assignment_revision += 1
    ticket.group_id = group_id
    ticket.assignee_id = chosen.user_id if chosen else None
    ticket.assign_status = "PENDING" if chosen else "NEEDS_ADMIN"
    event = "FAIL" if chosen is None else "REASSIGN" if previous is not None else "ASSIGN"
    db.add(AssignmentLog(ticket_id=ticket.id, event=event, group_id=group_id, assignee_id=ticket.assignee_id,
                         reason=log_reason, actor_id=actor_id))

    job = None
    # Jira 이슈가 아직 없으면 생성 뒤에 배정한다. 생성 실행기가 이 함수를 다시 부른다
    if chosen is not None and ticket.jira_key:
        now = now or datetime_utils.now()
        job = enqueue_jira_assign(db, ticket, {
            "ticketId": ticket.id,
            "receiptNo": ticket.receipt_no,
            "jiraKey": ticket.jira_key,
            "groupId": group_id,
            "assigneeId": chosen.user_id,
            "jiraAccountId": chosen.jira_account_id,
            "assignmentRevision": ticket.assignment_revision,
            "requestedBy": actor_id,
            "requestedAt": now.isoformat(),
        })
    db.flush()
    return Reservation(event, ticket.assignee_id, log_reason, job)


def manual_problem(member: Member | None, scenario: str | None) -> str | None:
    """직접 지정 자격 (API 03 TK-09, docs/11 3.1). Jira 실행(assign_confirmed_ticket)의 수동 지정 검사와 같은 항목이다."""
    if member is None:
        return "그룹 구성원 아님"
    checks = (
        (member.user_active, "사용자 비활성 또는 담당자 권한 아님"),
        (member.member_active, "그룹 구성원 아님(비활성)"),
        (member.assignable, "배정 대상 아님"),
        (scenario is not None, "미분류 접수는 직접 지정할 수 없음(서비스데스크 확인)"),
        (scenario in member.scenario_ids, "해당 세부 분류 처리 불가"),
        (bool((member.jira_account_id or "").strip()), "Jira 계정 없음"),
    )
    return next((why for ok, why in checks if not ok), None)
