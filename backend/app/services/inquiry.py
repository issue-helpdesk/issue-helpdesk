import logging
from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.core.permissions import visible_scopes
from app.db.session import DbSession
from app.models import (
    Category,
    ChatSession,
    Inquiry,
    InquiryType,
    Message,
    SupportGroup,
    User,
)
from app.repositories.inquiry import InquiryRepositoryDep
from app.schemas.common import ItemList, Page, parse_sort
from app.schemas.inquiry import (
    AiTurn,
    CategoryRef,
    GroupRef,
    Inquiry as InquiryDetail,
    InquiryListQuery,
    InquirySummary,
    InquiryTypeRef,
    Message as MessageView,
    MessageSource as MessageSourceView,
    Session as SessionView,
    TicketRef,
    UserRef,
)
from app.services.ai_responder import AiResponderDep
from app.services.inquiry_status import CLOSED_STATUSES, display_status, next_actions
from app.utils import datetime_utils

logger = logging.getLogger(__name__)



class InquiryService:
    def __init__(self, db: DbSession, inquiries: InquiryRepositoryDep, ai: AiResponderDep) -> None:
        self.db = db
        self.inquiries = inquiries
        self.ai = ai

    def start(self, content: str, user: User) -> AiTurn:
        inquiry = self.inquiries.add(Inquiry(user_id=user.id, status="IN_PROGRESS", updated_at=datetime_utils.now()))
        session = self.inquiries.add(ChatSession(inquiry_id=inquiry.id))
        user_message = self.inquiries.add(Message(session_id=session.id, seq=1, sender="USER", content=content))
        self.db.commit()

        ai_message = self.reply(inquiry, session, unavailable_error("INQUIRY_ID", "저장된 문의", inquiry.id))
        return self.ai_turn(inquiry, [user_message, ai_message])

    def send_message(self, inquiry_id: int, content: str, user: User) -> AiTurn:
        inquiry = self.inquiries.get_for_update(inquiry_id)
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        session = self.inquiries.current_session(inquiry.id)
        if inquiry.status in CLOSED_STATUSES or session is None or session.ended_at is not None:
            raise AppError(ErrorCode.INQUIRY_CLOSED)
        if inquiry.status != "IN_PROGRESS" or inquiry.action != "ASK_MORE":
            raise AppError(ErrorCode.INQUIRY_INVALID_STATE, [
                {"reason": "CURRENT_STATUS", "message": "현재 상태", "value": inquiry.status},
            ])

        user_message = self.inquiries.add(Message(
            session_id=session.id, seq=self.inquiries.next_seq(session.id), sender="USER", content=content,
        ))
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()

        ai_message = self.reply(inquiry, session, unavailable_error("MESSAGE_ID", "저장된 메시지", user_message.id))
        return self.ai_turn(inquiry, [user_message, ai_message])

    def reply(self, inquiry: Inquiry, session: ChatSession, unavailable: AppError) -> Message:
        try:
            result = self.ai.respond(inquiry, self.inquiries.messages(session.id))
        except Exception:
            logger.exception("AI 처리 실패 inquiry_id=%s", inquiry.id)
            raise unavailable

        self.inquiries.get_for_update(inquiry.id)
        message = self.inquiries.add(Message(
            session_id=session.id, seq=self.inquiries.next_seq(session.id), sender="AI", content=result.content,
        ))
        inquiry.action = result.action
        if inquiry.title is None:
            inquiry.title = result.title
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()
        return message

    def list_inquiries(self, query: InquiryListQuery, viewer: User) -> Page[InquirySummary]:
        if query.user_id is not None and viewer.service_role != "ADMIN":
            raise AppError(ErrorCode.FORBIDDEN)
        if query.created_from and query.created_to and query.created_from > query.created_to:
            raise AppError(ErrorCode.INVALID_REQUEST)

        rows, total = self.inquiries.search(
            user_id=query.user_id if viewer.service_role == "ADMIN" else viewer.id,
            display_statuses=query.display_status,
            statuses=query.status,
            category_codes=query.category_code,
            urgencies=query.urgency,
            created_from=datetime_utils.kst_start(query.created_from) if query.created_from else None,
            created_before=datetime_utils.kst_start(query.created_to + timedelta(days=1)) if query.created_to else None,
            q=query.q or None,
            sort=parse_sort(query.sort),
            offset=query.offset,
            limit=query.size,
        )
        items = [
            InquirySummary(
                id=inquiry.id,
                user=UserRef.model_validate(user),
                title=inquiry.title,
                status=inquiry.status,
                display_status=shown,
                category=CategoryRef.model_validate(category) if category else None,
                urgency=inquiry.urgency,
                receipt_no=receipt_no,
                created_at=inquiry.created_at,
                updated_at=inquiry.updated_at,
            )
            for inquiry, user, category, receipt_no, shown in rows
        ]
        return Page.of(items, query.page, query.size, total)

    def get_inquiry(self, inquiry_id: int, viewer: User) -> InquiryDetail:
        return self.to_detail(self.find_viewable(inquiry_id, viewer))

    def list_sessions(self, inquiry_id: int, viewer: User) -> ItemList[SessionView]:
        inquiry = self.find_viewable(inquiry_id, viewer)
        return ItemList(items=[SessionView.model_validate(s) for s in self.inquiries.sessions(inquiry.id)])

    def list_messages(self, inquiry_id: int, session_id: int | None, viewer: User) -> ItemList[MessageView]:
        inquiry = self.find_viewable(inquiry_id, viewer)
        if session_id is not None and session_id not in {s.id for s in self.inquiries.sessions(inquiry.id)}:
            raise field_error(ErrorCode.VALIDATION_ERROR, "sessionId", "NOT_FOUND", "이 문의의 상담 세션이 아닙니다.")

        messages = self.inquiries.inquiry_messages(inquiry.id, session_id)
        allowed = visible_scopes(viewer.service_role)
        sources: dict[int, list[MessageSourceView]] = {}
        for source, scope in self.inquiries.sources_with_scope([m.id for m in messages]):
            if scope in allowed:
                sources.setdefault(source.message_id, []).append(MessageSourceView.model_validate(source))
        return ItemList(items=[to_message_view(m, sources.get(m.id, [])) for m in messages])

    def find_viewable(self, inquiry_id: int, viewer: User) -> Inquiry:
        inquiry = self.inquiries.get(inquiry_id)
        if inquiry is None or not self.can_view(inquiry, viewer):
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        return inquiry

    def can_view(self, inquiry: Inquiry, viewer: User) -> bool:
        if inquiry.user_id == viewer.id or viewer.service_role == "ADMIN":
            return True
        if viewer.service_role != "AGENT":
            return False
        ticket = self.inquiries.ticket(inquiry.id)
        return bool(ticket and ticket.group_id and self.inquiries.is_active_group_member(viewer.id, ticket.group_id))

    def ai_turn(self, inquiry: Inquiry, messages: list[Message]) -> AiTurn:
        return AiTurn(
            inquiry=self.to_detail(inquiry),
            messages=[to_message_view(m) for m in messages],
            assessment=None,
            next_actions=next_actions(inquiry),
        )

    def to_detail(self, inquiry: Inquiry) -> InquiryDetail:
        ticket = self.inquiries.ticket(inquiry.id)
        session = self.inquiries.current_session(inquiry.id)
        user = self.inquiries.ref(User, inquiry.user_id)
        category = self.inquiries.ref(Category, inquiry.category_code)
        inquiry_type = self.inquiries.ref(InquiryType, inquiry.inquiry_type_id)
        group = self.inquiries.ref(SupportGroup, inquiry.recommended_group_id)
        return InquiryDetail(
            id=inquiry.id,
            user_id=inquiry.user_id,
            user=UserRef.model_validate(user),
            title=inquiry.title,
            status=inquiry.status,
            display_status=display_status(inquiry, ticket),
            category_code=inquiry.category_code,
            category=CategoryRef.model_validate(category) if category else None,
            inquiry_type_id=inquiry.inquiry_type_id,
            inquiry_type=InquiryTypeRef.model_validate(inquiry_type) if inquiry_type else None,
            urgency=inquiry.urgency,
            action=inquiry.action,
            recommended_group_id=inquiry.recommended_group_id,
            recommended_group=GroupRef.model_validate(group) if group else None,
            resolution_result=inquiry.resolution_result,
            current_session_id=session.id if session else None,
            active_draft_id=self.inquiries.active_draft_id(inquiry.id),
            ticket=TicketRef.model_validate(ticket) if ticket else None,
            created_at=inquiry.created_at,
            updated_at=inquiry.updated_at,
            closed_at=inquiry.closed_at,
        )


InquiryServiceDep = Annotated[InquiryService, Depends(InquiryService)]


def to_message_view(message: Message, sources: list[MessageSourceView] | None = None) -> MessageView:
    return MessageView(
        id=message.id,
        session_id=message.session_id,
        seq=message.seq,
        sender=message.sender,
        content=message.content,
        sources=sources or [],
        created_at=message.created_at,
    )


def unavailable_error(reason: str, message: str, value: int) -> AppError:
    return AppError(ErrorCode.AI_UNAVAILABLE, [{"reason": reason, "message": message, "value": value}])
