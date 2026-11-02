from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.integrations.jira import Member
from app.models import AssignmentLog, InquiryType, MemberSkill, SupportGroup, SupportGroupMember, Ticket, User


class AssignmentRepository:
    """담당자 선정에 쓰는 조회 (docs/11 3장). TK-09 와 Jira 생성 직후 자동배정이 같이 쓴다.

    FastAPI 의존성 없이 Session 만 받는다. 실행기(worker)도 자기 세션으로 만들어 쓸 수 있다.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def lock_group(self, group_id: int) -> SupportGroup | None:
        """같은 그룹의 선정을 줄 세운다. 동시에 접수된 두 건이 한 사람에게 몰리지 않게 한다 (docs/11 3장 동시 선정 방지)."""
        return self.db.get(SupportGroup, group_id, with_for_update=True, populate_existing=True)

    def members(self, group_id: int, exclude_ticket_id: int | None = None) -> list[Member]:
        """그룹 구성원 전원을 pick_assignee 입력으로. 거르는 일은 pick_assignee 가 하고 빠진 이유도 남긴다.

        exclude_ticket_id: 지금 배정하는 접수. 재배정할 때 이 접수가 원래 담당자의 업무량에 들어가지 않게 뺀다.
        """
        rows = self.db.execute(
            select(SupportGroupMember, User).join(User, User.id == SupportGroupMember.user_id)
            .where(SupportGroupMember.group_id == group_id)
        ).all()
        user_ids = [user.id for _, user in rows]
        if not user_ids:
            return []
        skills = self.skills(user_ids)
        workload = self.workload(user_ids, exclude_ticket_id)
        last = self.last_assigned(user_ids)
        return [
            Member(
                user_id=user.id,
                employee_no=user.employee_no,
                name=user.name,
                is_manager=member.member_role == "MANAGER",
                user_active=user.account_status == "ACTIVE" and user.service_role in ("AGENT", "ADMIN"),
                member_active=member.is_active,
                assignable=member.assignable,
                jira_account_id=member.jira_account_id,
                scenario_ids=frozenset(skills[user.id]),
                rdy=workload[user.id]["RDY"],
                wip=workload[user.id]["WIP"],
                reserved=workload[user.id]["PENDING"],
                last_assigned_at=last.get(user.id),
            )
            for member, user in rows
        ]

    def skills(self, user_ids: list[int]) -> dict[int, set[str]]:
        out: dict[int, set[str]] = defaultdict(set)
        rows = self.db.execute(
            select(MemberSkill.user_id, InquiryType.code)
            .join(InquiryType, InquiryType.id == MemberSkill.inquiry_type_id)
            .where(MemberSkill.user_id.in_(user_ids))
        )
        for user_id, code in rows:
            out[user_id].add(code)
        return out

    def workload(self, user_ids: list[int], exclude_ticket_id: int | None) -> dict[int, dict[str, int]]:
        """사람별 업무량. 예약(assign_status = PENDING)과, 배정이 확인된(ASSIGNED) RDY·WIP 접수 (docs/11 3장)."""
        bucket = case((Ticket.assign_status == "PENDING", "PENDING"), else_=Ticket.work_status)   # 예약 / RDY / WIP
        conditions = [
            Ticket.assignee_id.in_(user_ids),
            or_(Ticket.assign_status == "PENDING",
                and_(Ticket.assign_status == "ASSIGNED", Ticket.work_status.in_(("RDY", "WIP")))),
        ]
        if exclude_ticket_id is not None:
            conditions.append(Ticket.id != exclude_ticket_id)
        out: dict[int, dict[str, int]] = defaultdict(lambda: {"RDY": 0, "WIP": 0, "PENDING": 0})
        for user_id, kind, count in self.db.execute(
            select(Ticket.assignee_id, bucket, func.count()).where(*conditions).group_by(Ticket.assignee_id, bucket)
        ):
            out[user_id][kind] = count
        return out

    def last_assigned(self, user_ids: list[int]) -> dict[int, datetime]:
        """배정 이력 ASSIGN·REASSIGN 의 가장 최근 시각."""
        rows = self.db.execute(
            select(AssignmentLog.assignee_id, func.max(AssignmentLog.created_at))
            .where(AssignmentLog.assignee_id.in_(user_ids), AssignmentLog.event.in_(("ASSIGN", "REASSIGN")))
            .group_by(AssignmentLog.assignee_id)
        )
        return dict(rows.all())
