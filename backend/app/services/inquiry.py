import logging
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends

from app.agent.flow import FlowResult
from app.agent.sensitive import BLOCKED_NOTICE, mask_secrets
from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.core.permissions import visible_scopes
from app.db.session import DbSession
from app.models import (
    Category,
    ChatSession,
    Inquiry,
    InquiryAssessment,
    InquiryType,
    Message,
    SupportGroup,
    User,
)
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.inquiry import InquiryRepositoryDep
from app.repositories.reference import ReferenceRepositoryDep
from app.schemas.common import ItemList, Page, parse_sort
from app.schemas.inquiry import (
    AiTurn,
    AssessmentView,
    CategoryRef,
    GroupRef,
    Inquiry as InquiryDetail,
    InquiryListQuery,
    InquirySummary,
    InquiryTypeRef,
    Message as MessageView,
    MessageSource as MessageSourceView,
    Session as SessionView,
    SessionResume,
    TicketRef,
    UserRef,
)
from app.services.ai_responder import AiResponderDep
from app.services.inquiry_status import CLOSED_STATUSES, display_status, next_actions, resume_actions
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

RESOLVED_NOTICE = "해결로 종료되었습니다."


class InquiryService:
    def __init__(
        self,
        db: DbSession,
        inquiries: InquiryRepositoryDep,
        references: ReferenceRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        ai: AiResponderDep,
    ) -> None:
        self.db = db
        self.inquiries = inquiries
        self.references = references
        self.audit_logs = audit_logs
        self.ai = ai

    def start(self, content: str, user: User) -> AiTurn:
        inquiry = self.inquiries.add(Inquiry(user_id=user.id, status="IN_PROGRESS", updated_at=datetime_utils.now()))
        session = self.inquiries.add(ChatSession(inquiry_id=inquiry.id))
        user_message = self.inquiries.add(Message(
            session_id=session.id, seq=1, sender="USER", content=mask_secrets(content).text,
        ))
        self.db.commit()

        ai_message, assessment = self.reply(inquiry, session, user,
                                            unavailable_error("INQUIRY_ID", "저장된 문의", inquiry.id))
        return self.ai_turn(inquiry, [user_message, ai_message], assessment)

    def send_message(self, inquiry_id: int, content: str, user: User) -> AiTurn:
        inquiry = self.find_own(inquiry_id, user, for_update=True)
        session = self.inquiries.current_session(inquiry.id)
        if inquiry.status in CLOSED_STATUSES or session is None or session.ended_at is not None:
            raise AppError(ErrorCode.INQUIRY_CLOSED)
        if inquiry.status != "IN_PROGRESS" or inquiry.action != "ASK_MORE":
            raise invalid_state(inquiry)

        user_message = self.add_message(session, "USER", mask_secrets(content).text)
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()

        ai_message, assessment = self.reply(inquiry, session, user,
                                            unavailable_error("MESSAGE_ID", "저장된 메시지", user_message.id))
        return self.ai_turn(inquiry, [user_message, ai_message], assessment)

    def reply(
        self, inquiry: Inquiry, session: ChatSession, user: User, unavailable: AppError,
    ) -> tuple[Message, InquiryAssessment]:
        """판단 흐름을 돌려 판단 이력·AI 메시지·문의의 현재 판단값을 저장한다 (IQ-01 처리 2·3).

        모델 오류·외부 전송 제한·근거 부족은 흐름이 담당자 연결 제안(ESCALATE)으로 돌려준다.
        그 밖의 예외(검색 실패, 모델 설정 없음 등)만 503 으로 응답한다.
        """
        try:
            result = self.ai.respond(inquiry, user, self.inquiries.messages(session.id))
        except Exception:
            logger.exception("AI 처리 실패 inquiry_id=%s", inquiry.id)
            raise unavailable

        self.inquiries.get_for_update(inquiry.id)
        out = result.output
        inquiry_type = self.references.get_inquiry_type_by_code(out.inquiry_type_code) if out.inquiry_type_code else None
        assessment = self.inquiries.add(InquiryAssessment(
            inquiry_id=inquiry.id,
            facts=out.facts.model_dump(mode="json"),
            missing_items=out.missing_items,
            urgent_signal=out.urgent_signal,
            category_code=out.category_code,
            inquiry_type_id=inquiry_type.id if inquiry_type else None,
            urgency=result.urgency,
            urgency_reason=urgency_reason(result),
            action=out.action,
            ai_output=result.ai_output,
            override_reasons=list(result.override_reasons),
        ))
        message = self.add_message(session, "AI", BLOCKED_NOTICE if result.failure == "ALL_BLOCKED" else out.reply)
        inquiry.category_code = assessment.category_code
        inquiry.inquiry_type_id = assessment.inquiry_type_id
        inquiry.urgency = assessment.urgency
        inquiry.action = assessment.action
        # 세부 유형의 기본 그룹. 범위 밖이거나 세부 유형을 모르면 서비스데스크가 확인한다 (09 T08, 03 TK-09)
        if out.action == "OUT_OF_SCOPE" or inquiry_type is None:
            inquiry.recommended_group_id = self.references.triage_group_id()
        else:
            inquiry.recommended_group_id = inquiry_type.default_group_id
        if inquiry.title is None:
            inquiry.title = out.title
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()
        return message, assessment

    def close(self, inquiry_id: int, user: User) -> InquiryDetail:
        """IQ-04. 담당자 연결 거절·상담 끝내기. 해결과 구분해 CLOSED_UNRESOLVED 로 남긴다."""
        inquiry = self.find_own(inquiry_id, user, for_update=True)
        if inquiry.status != "IN_PROGRESS":
            raise invalid_state(inquiry)

        now = datetime_utils.now()
        inquiry.status = "CLOSED_UNRESOLVED"
        inquiry.closed_at = inquiry.updated_at = now
        end_session(self.inquiries.current_session(inquiry.id), now)
        for draft in self.inquiries.editing_drafts(inquiry.id):
            draft.status, draft.updated_at = "CANCELLED", now
        if any(a.urgent_signal for a in self.inquiries.assessments(inquiry.id)):
            self.audit_logs.add("URGENT_CLOSED", "inquiry", inquiry.id, result=inquiry.status, actor_id=user.id)
        self.db.commit()
        return self.to_detail(inquiry)

    def resolve(self, inquiry_id: int, result: str, comment: str | None, user: User) -> AiTurn:
        """IQ-09. AI 답변의 해결 여부. AI 를 다시 부르지 않는다.

        UNRESOLVED 는 문의를 열어 둔 채 결과만 남긴다. 다음은 담당자 연결(TK-01) 또는 종료(IQ-04)다.
        """
        inquiry = self.find_own(inquiry_id, user, for_update=True)
        if inquiry.status == "AI_RESOLVED" and result == "RESOLVED":
            return AiTurn(inquiry=self.to_detail(inquiry), messages=[], assessment=None,
                          next_actions=next_actions(inquiry))
        session = self.inquiries.current_session(inquiry.id)
        if (display_status(inquiry, self.inquiries.ticket(inquiry.id)) != "unconfirmed"
                or session is None or session.ended_at is not None):
            raise invalid_state(inquiry)

        now = datetime_utils.now()
        inquiry.resolution_result = result
        inquiry.updated_at = now
        if result == "RESOLVED":
            inquiry.status = "AI_RESOLVED"
            inquiry.closed_at = now
            end_session(session, now)
            messages = [self.add_message(session, "SYSTEM", RESOLVED_NOTICE)]
        else:
            messages = [self.add_message(session, "USER", mask_secrets(comment).text)] if comment else []
        self.db.commit()
        return AiTurn(inquiry=self.to_detail(inquiry), messages=[to_message_view(m) for m in messages],
                      assessment=None, next_actions=next_actions(inquiry))

    def resume(self, inquiry_id: int, user: User) -> SessionResume:
        """IQ-06. 기존 세션을 그대로 돌려주고 지금 할 수 있는 행동만 알려준다. 아무것도 저장하지 않는다."""
        inquiry = self.find_own(inquiry_id, user)
        session = self.inquiries.current_session(inquiry.id)
        actions = resume_actions(inquiry, self.inquiries.ticket(inquiry.id))
        if not actions or session is None:
            raise invalid_state(inquiry)
        return SessionResume(session=SessionView.model_validate(session), inquiry=self.to_detail(inquiry),
                             next_actions=actions)

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

    def find_own(self, inquiry_id: int, user: User, for_update: bool = False) -> Inquiry:
        inquiry = self.inquiries.get_for_update(inquiry_id) if for_update else self.inquiries.get(inquiry_id)
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        return inquiry

    def add_message(self, session: ChatSession, sender: str, content: str) -> Message:
        return self.inquiries.add(Message(
            session_id=session.id, seq=self.inquiries.next_seq(session.id), sender=sender, content=content,
        ))

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

    def ai_turn(self, inquiry: Inquiry, messages: list[Message], assessment: InquiryAssessment) -> AiTurn:
        return AiTurn(
            inquiry=self.to_detail(inquiry),
            messages=[to_message_view(m) for m in messages],
            assessment=AssessmentView.model_validate(assessment),
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


def urgency_reason(result: FlowResult) -> str | None:
    """긴급도를 서버 규칙이 정했으면 그 이유, 아니면 AI 가 든 이유."""
    rules = [o["reason"] for o in result.override_reasons if o["field"] == "urgency"]
    return " ".join(rules or result.output.rationale.urgency_reasons) or None


def end_session(session: ChatSession | None, now: datetime) -> None:
    if session is not None and session.ended_at is None:
        session.ended_at, session.end_reason = now, "USER_END"


def invalid_state(inquiry: Inquiry) -> AppError:
    return AppError(ErrorCode.INQUIRY_INVALID_STATE, [
        {"reason": "CURRENT_STATUS", "message": "현재 상태", "value": inquiry.status},
    ])


def unavailable_error(reason: str, message: str, value: int) -> AppError:
    return AppError(ErrorCode.AI_UNAVAILABLE, [{"reason": reason, "message": message, "value": value}])
