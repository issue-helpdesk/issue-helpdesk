from datetime import datetime
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import aliased

from app.db.session import DbSession
from app.models import (
    Category,
    Inquiry,
    SupportGroup,
    SupportGroupMember,
    Ticket,
    TicketDraft,
    TicketStatusHistory,
    User,
)

T = TypeVar("T")

Assignee = aliased(User)
NEEDS_ADMIN = or_(Ticket.jira_sync_status == "NEEDS_ADMIN", Ticket.assign_status == "NEEDS_ADMIN",
                  Ticket.transition_status == "NEEDS_ADMIN")
# 업무 상태는 진행 순서로 정렬한다. 생성 전(null)이 가장 앞이다
WORK_STATUS_ORDER = case({"RDY": 1, "WIP": 2, "FIN": 3, "CLS": 4}, value=Ticket.work_status, else_=0)
SORT_COLUMNS = {
    "createdAt": Ticket.created_at,
    "urgency": Ticket.urgency,
    "workStatus": WORK_STATUS_ORDER,
}


class TicketRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, row: T) -> T:
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, ticket_id: int) -> Ticket | None:
        return self.db.get(Ticket, ticket_id)

    def get_draft(self, draft_id: int) -> TicketDraft | None:
        return self.db.get(TicketDraft, draft_id)

    def get_draft_for_update(self, draft_id: int) -> TicketDraft | None:
        # 잠그기 전에 읽어 둔 값이 있어도 잠근 뒤의 값으로 다시 읽는다
        return self.db.get(TicketDraft, draft_id, with_for_update=True, populate_existing=True)

    def search(
        self,
        requester_id: int | None,
        member_id: int | None,
        work_statuses: list[str],
        jira_sync_statuses: list[str],
        assign_statuses: list[str],
        needs_admin: bool | None,
        category_codes: list[str],
        urgencies: list[str],
        group_id: int | None,
        assignee_id: int | None,
        created_from: datetime | None,
        created_before: datetime | None,
        q: str | None,
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Ticket, User, Category | None, SupportGroup | None, User | None]], int]:
        """requester_id: 그 사람이 문의한 접수만. member_id: 그 사람이 활성 구성원인 활성 그룹의 접수만."""
        conditions = []
        if requester_id is not None:
            conditions.append(Inquiry.user_id == requester_id)
        if member_id is not None:
            conditions.append(Ticket.group_id.in_(
                select(SupportGroupMember.group_id)
                .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
                .where(SupportGroupMember.user_id == member_id, SupportGroupMember.is_active.is_(True),
                       SupportGroup.is_active.is_(True))
            ))
        if work_statuses:
            conditions.append(Ticket.work_status.in_(work_statuses))
        if jira_sync_statuses:
            conditions.append(Ticket.jira_sync_status.in_(jira_sync_statuses))
        if assign_statuses:
            conditions.append(Ticket.assign_status.in_(assign_statuses))
        if needs_admin is not None:
            conditions.append(NEEDS_ADMIN if needs_admin else ~NEEDS_ADMIN)
        if category_codes:
            conditions.append(Ticket.category_code.in_(category_codes))
        if urgencies:
            conditions.append(Ticket.urgency.in_(urgencies))
        if group_id is not None:
            conditions.append(Ticket.group_id == group_id)
        if assignee_id is not None:
            conditions.append(Ticket.assignee_id == assignee_id)
        if created_from is not None:
            conditions.append(Ticket.created_at >= created_from)
        if created_before is not None:
            conditions.append(Ticket.created_at < created_before)
        if q:
            conditions.append(or_(
                Ticket.receipt_no.icontains(q, autoescape=True),
                Ticket.jira_key.icontains(q, autoescape=True),
                Ticket.summary.icontains(q, autoescape=True),
            ))

        base = select(Ticket.id).join(Inquiry, Inquiry.id == Ticket.inquiry_id).where(*conditions)
        total = self.db.scalar(select(func.count()).select_from(base.subquery()))
        order_by = [
            (SORT_COLUMNS[field].desc() if desc else SORT_COLUMNS[field].asc()).nulls_last()
            for field, desc in sort
        ]
        rows = self.db.execute(
            select(Ticket, User, Category, SupportGroup, Assignee)
            .join(Inquiry, Inquiry.id == Ticket.inquiry_id)
            .join(User, User.id == Inquiry.user_id)
            .outerjoin(Category, Category.code == Ticket.category_code)
            .outerjoin(SupportGroup, SupportGroup.id == Ticket.group_id)
            .outerjoin(Assignee, Assignee.id == Ticket.assignee_id)
            .where(*conditions)
            .order_by(*order_by, Ticket.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total

    def status_history(self, ticket_id: int) -> list[tuple[TicketStatusHistory, User | None]]:
        rows = self.db.execute(
            select(TicketStatusHistory, User)
            .outerjoin(User, User.id == TicketStatusHistory.actor_id)
            .where(TicketStatusHistory.ticket_id == ticket_id)
            .order_by(TicketStatusHistory.changed_at, TicketStatusHistory.id)
        )
        return [tuple(row) for row in rows]


TicketRepositoryDep = Annotated[TicketRepository, Depends(TicketRepository)]
