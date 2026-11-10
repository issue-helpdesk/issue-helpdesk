from datetime import datetime
from typing import Annotated, NamedTuple

from fastapi import Depends
from sqlalchemy import func, select

from app.db.session import DbSession
from app.models import Category, Inquiry, LlmCall, SupportGroup, SupportGroupMember, Ticket, TicketStatusHistory, User
from app.repositories.ticket import NEEDS_ADMIN
from app.services.inquiry_status import display_status_column


class InquiryRow(NamedTuple):
    created_at: datetime
    status: str
    category_code: str | None
    display_status: str


class TicketRow(NamedTuple):
    created_at: datetime
    category_code: str | None
    urgency: str | None
    group_id: int | None
    assignee_id: int | None
    work_status: str | None
    needs_admin: bool


class LlmRow(NamedTuple):
    created_at: datetime
    purpose: str
    model: str
    adapter: str
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    success: bool


class MemberRow(NamedTuple):
    group_id: int
    user_id: int
    name: str


class DashboardRepository:
    """집계할 칸만 읽는다. 기간을 나누는 일은 KST 기준이라 서비스에서 한다."""

    def __init__(self, db: DbSession) -> None:
        self.db = db

    def inquiries(self, start: datetime, before: datetime) -> list[InquiryRow]:
        rows = self.db.execute(
            select(Inquiry.created_at, Inquiry.status, Inquiry.category_code, display_status_column())
            .outerjoin(Ticket, Ticket.inquiry_id == Inquiry.id)
            .where(Inquiry.created_at >= start, Inquiry.created_at < before)
        )
        return [InquiryRow(*r) for r in rows]

    def tickets(self, start: datetime, before: datetime) -> list[TicketRow]:
        rows = self.db.execute(
            select(Ticket.created_at, Ticket.category_code, Ticket.urgency, Ticket.group_id, Ticket.assignee_id,
                   Ticket.work_status, NEEDS_ADMIN)
            .where(Ticket.created_at >= start, Ticket.created_at < before)
        )
        return [TicketRow(*r) for r in rows]

    def wip_since(self) -> dict[tuple[int, int], datetime]:
        """(그룹, 담당자)별로 지금 처리 중(WIP)인 접수 가운데 WIP 가 가장 오래된 시작 시각.

        선택 기간과 무관하다. 기간 밖에서 접수돼 아직 처리 중인 건도 센다. 시작 시각은 가장 최근에 WIP 가 된 이력이고,
        이력이 없으면 접수 시각으로 대신한다. 업무량(assignment.workload)과 같게 배정이 확인된(ASSIGNED) 접수만 본다.
        """
        entered = (select(TicketStatusHistory.ticket_id, func.max(TicketStatusHistory.changed_at).label("at"))
                   .where(TicketStatusHistory.to_status == "WIP")
                   .group_by(TicketStatusHistory.ticket_id).subquery())
        rows = self.db.execute(
            select(Ticket.group_id, Ticket.assignee_id, func.min(func.coalesce(entered.c.at, Ticket.created_at)))
            .outerjoin(entered, entered.c.ticket_id == Ticket.id)
            .where(Ticket.work_status == "WIP", Ticket.assign_status == "ASSIGNED",
                   Ticket.group_id.is_not(None), Ticket.assignee_id.is_not(None))
            .group_by(Ticket.group_id, Ticket.assignee_id)
        )
        return {(group_id, user_id): since for group_id, user_id, since in rows}

    def llm_calls(self, start: datetime, before: datetime) -> list[LlmRow]:
        rows = self.db.execute(
            select(LlmCall.created_at, LlmCall.purpose, LlmCall.model, LlmCall.adapter, LlmCall.latency_ms,
                   LlmCall.input_tokens, LlmCall.output_tokens, LlmCall.success)
            .where(LlmCall.created_at >= start, LlmCall.created_at < before)
        )
        return [LlmRow(*r) for r in rows]

    def categories(self) -> dict[str, str]:
        return dict(self.db.execute(select(Category.code, Category.name).order_by(Category.code)).all())

    def groups(self) -> dict[int, tuple[str, bool]]:
        rows = self.db.execute(select(SupportGroup.id, SupportGroup.name, SupportGroup.is_active).order_by(SupportGroup.id))
        return {i: (name, active) for i, name, active in rows}

    def active_members(self) -> list[MemberRow]:
        rows = self.db.execute(
            select(SupportGroupMember.group_id, User.id, User.name)
            .join(User, User.id == SupportGroupMember.user_id)
            .where(SupportGroupMember.is_active.is_(True))
        )
        return [MemberRow(*r) for r in rows]

    def user_names(self, user_ids: set[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        return dict(self.db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all())


DashboardRepositoryDep = Annotated[DashboardRepository, Depends(DashboardRepository)]
