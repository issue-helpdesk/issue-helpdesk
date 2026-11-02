from datetime import datetime
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy import and_, func, or_, select

from app.db.session import DbSession
from app.models import (
    Category,
    ChatSession,
    DocumentVersion,
    Inquiry,
    InquiryAssessment,
    KnowledgeDocument,
    LegacyInquiry,
    Message,
    MessageSource,
    SupportGroup,
    SupportGroupMember,
    Ticket,
    TicketDraft,
    User,
)
from app.services.inquiry_status import display_status_column

T = TypeVar("T")

SORT_COLUMNS = {
    "createdAt": Inquiry.created_at,
    "updatedAt": Inquiry.updated_at,
    "urgency": Inquiry.urgency,
}


class InquiryRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, row: T) -> T:
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, inquiry_id: int) -> Inquiry | None:
        return self.db.get(Inquiry, inquiry_id)

    def get_for_update(self, inquiry_id: int) -> Inquiry | None:
        return self.db.get(Inquiry, inquiry_id, with_for_update=True)

    def ref(self, model: type[T], key) -> T | None:
        return self.db.get(model, key) if key is not None else None

    def search(
        self,
        user_id: int | None,
        display_statuses: list[str],
        statuses: list[str],
        category_codes: list[str],
        urgencies: list[str],
        created_from: datetime | None,
        created_before: datetime | None,
        q: str | None,
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Inquiry, User, Category | None, str | None, str]], int]:
        display = display_status_column()
        conditions = []
        if user_id is not None:
            conditions.append(Inquiry.user_id == user_id)
        if display_statuses:
            conditions.append(display.in_(display_statuses))
        if statuses:
            conditions.append(Inquiry.status.in_(statuses))
        if category_codes:
            conditions.append(Inquiry.category_code.in_(category_codes))
        if urgencies:
            conditions.append(Inquiry.urgency.in_(urgencies))
        if created_from is not None:
            conditions.append(Inquiry.created_at >= created_from)
        if created_before is not None:
            conditions.append(Inquiry.created_at < created_before)
        if q:
            cited = (
                select(MessageSource.id)
                .join(Message, Message.id == MessageSource.message_id)
                .join(ChatSession, ChatSession.id == Message.session_id)
                .where(ChatSession.inquiry_id == Inquiry.id, MessageSource.doc_code.icontains(q, autoescape=True))
                .exists()
            )
            conditions.append(or_(
                Inquiry.title.icontains(q, autoescape=True),
                Ticket.receipt_no.icontains(q, autoescape=True),
                cited,
            ))

        base = select(Inquiry.id).outerjoin(Ticket, Ticket.inquiry_id == Inquiry.id).where(*conditions)
        total = self.db.scalar(select(func.count()).select_from(base.subquery()))
        order_by = [
            (SORT_COLUMNS[field].desc() if desc else SORT_COLUMNS[field].asc()).nulls_last()
            for field, desc in sort
        ]
        rows = self.db.execute(
            select(Inquiry, User, Category, Ticket.receipt_no, display)
            .join(User, User.id == Inquiry.user_id)
            .outerjoin(Category, Category.code == Inquiry.category_code)
            .outerjoin(Ticket, Ticket.inquiry_id == Inquiry.id)
            .where(*conditions)
            .order_by(*order_by, Inquiry.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total

    def current_session(self, inquiry_id: int) -> ChatSession | None:
        return self.db.scalars(
            select(ChatSession)
            .where(ChatSession.inquiry_id == inquiry_id)
            .order_by(ChatSession.started_at.desc(), ChatSession.id.desc())
        ).first()

    def next_seq(self, session_id: int) -> int:
        last = self.db.scalar(select(func.max(Message.seq)).where(Message.session_id == session_id))
        return (last or 0) + 1

    def messages(self, session_id: int) -> list[Message]:
        return list(self.db.scalars(select(Message).where(Message.session_id == session_id).order_by(Message.seq)))

    def assessments(self, inquiry_id: int) -> list[InquiryAssessment]:
        """이 문의의 판단 이력. 오래된 것부터."""
        return list(self.db.scalars(
            select(InquiryAssessment).where(InquiryAssessment.inquiry_id == inquiry_id).order_by(InquiryAssessment.id)
        ))

    def sessions(self, inquiry_id: int) -> list[ChatSession]:
        return list(self.db.scalars(
            select(ChatSession)
            .where(ChatSession.inquiry_id == inquiry_id)
            .order_by(ChatSession.started_at, ChatSession.id)
        ))

    def inquiry_messages(self, inquiry_id: int, session_id: int | None) -> list[Message]:
        query = (
            select(Message)
            .join(ChatSession, ChatSession.id == Message.session_id)
            .where(ChatSession.inquiry_id == inquiry_id)
            .order_by(ChatSession.started_at, ChatSession.id, Message.seq)
        )
        if session_id is not None:
            query = query.where(Message.session_id == session_id)
        return list(self.db.scalars(query))

    def sources_with_scope(self, message_ids: list[int]) -> list[tuple[MessageSource, str | None]]:
        if not message_ids:
            return []
        rows = self.db.execute(
            select(MessageSource, func.coalesce(DocumentVersion.view_scope, LegacyInquiry.view_scope))
            .outerjoin(KnowledgeDocument, KnowledgeDocument.doc_code == MessageSource.doc_code)
            .outerjoin(DocumentVersion, and_(
                DocumentVersion.document_id == KnowledgeDocument.id,
                DocumentVersion.version == MessageSource.version,
            ))
            .outerjoin(LegacyInquiry, LegacyInquiry.id == MessageSource.legacy_inquiry_id)
            .where(MessageSource.message_id.in_(message_ids))
            .order_by(MessageSource.message_id, MessageSource.rank, MessageSource.id)
        )
        return [tuple(row) for row in rows]

    def active_draft_id(self, inquiry_id: int) -> int | None:
        return self.db.scalar(
            select(TicketDraft.id).where(TicketDraft.inquiry_id == inquiry_id, TicketDraft.status == "EDITING")
        )

    def editing_drafts(self, inquiry_id: int) -> list[TicketDraft]:
        return list(self.db.scalars(
            select(TicketDraft).where(TicketDraft.inquiry_id == inquiry_id, TicketDraft.status == "EDITING")
        ))

    def ticket(self, inquiry_id: int) -> Ticket | None:
        return self.db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry_id)).first()

    def is_active_group_member(self, user_id: int, group_id: int) -> bool:
        return self.db.scalar(
            select(SupportGroupMember.user_id)
            .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
            .where(
                SupportGroupMember.group_id == group_id,
                SupportGroupMember.user_id == user_id,
                SupportGroupMember.is_active.is_(True),
                SupportGroup.is_active.is_(True),
            )
        ) is not None


InquiryRepositoryDep = Annotated[InquiryRepository, Depends(InquiryRepository)]
