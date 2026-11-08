import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Annotated, get_args

from fastapi import Depends

from app.agent.flow import FlowResult
from app.agent.flow.correct import cap_questions
from app.agent.sensitive import BLOCKED_NOTICE, mask_notices, mask_secrets
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
    LlmCall,
    Message,
    MessageSource,
    SupportGroup,
    Ticket,
    TicketDraft,
    User,
)
from app.repositories.audit_log import AuditLogRepository, AuditLogRepositoryDep
from app.repositories.inquiry import InquiryRepository, InquiryRepositoryDep
from app.repositories.reference import ReferenceRepositoryDep
from app.repositories.security_alert import SecurityAlertRepository, SecurityAlertRepositoryDep
from app.schemas.common import CountedPage, ItemList, parse_sort
from app.schemas.inquiry import (
    AiTurn,
    Assessment as AssessmentHistory,
    AssessmentView,
    CategoryRef,
    DisplayStatus,
    GroupRef,
    Inquiry as InquiryDetail,
    InquiryListQuery,
    InquirySummary,
    InquiryTypeRef,
    Message as MessageView,
    MessageSource as MessageSourceView,
    Question as QuestionView,
    Session as SessionView,
    SessionResume,
    TicketDraft as TicketDraftView,
    TicketRef,
    UserRef,
)
from app.services.ai_responder import AiResponderDep
from app.services.guide_image import images_of
from app.services.inquiry_status import CLOSED_STATUSES, display_status, next_actions, resume_actions
from app.services.security_alert import detect
from app.utils import datetime_utils
from app.utils.text_utils import first_line_summary
from app.utils.dict_utils import camel_keys

logger = logging.getLogger(__name__)

DEFAULT_TITLE_MAX = 40                 # AI 제목이 생기기 전까지 목록에 보이는 제목


class InquiryService:
    def __init__(
        self,
        db: DbSession,
        inquiries: InquiryRepositoryDep,
        references: ReferenceRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        alerts: SecurityAlertRepositoryDep,
        ai: AiResponderDep,
    ) -> None:
        self.db = db
        self.inquiries = inquiries
        self.references = references
        self.audit_logs = audit_logs
        self.alerts = alerts
        self.ai = ai

    def start(self, content: str, user: User) -> AiTurn:
        inquiry = self.inquiries.add(Inquiry(user_id=user.id, status="IN_PROGRESS", updated_at=datetime_utils.now()))
        session = self.inquiries.add(ChatSession(inquiry_id=inquiry.id))
        user_messages = self.add_user_message(inquiry, session, user, content)
        inquiry.title = first_line_summary(user_messages[0].content, DEFAULT_TITLE_MAX) or None
        self.db.commit()

        ai_message, assessment, questions = self.reply(inquiry, session, user,
                                                       unavailable_error("INQUIRY_ID", "저장된 문의", inquiry.id))
        return self.ai_turn(inquiry, [*user_messages, ai_message], assessment, questions, user)

    def send_message(self, inquiry_id: int, content: str, user: User) -> AiTurn:
        inquiry = self.find_own(inquiry_id, user, for_update=True)
        session = self.inquiries.current_session(inquiry.id)
        if inquiry.status in CLOSED_STATUSES or session is None or session.ended_at is not None:
            raise AppError(ErrorCode.INQUIRY_CLOSED)
        if inquiry.status != "IN_PROGRESS" or inquiry.action != "ASK_MORE":
            raise invalid_state(inquiry)

        user_messages = self.add_user_message(inquiry, session, user, content)
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()

        ai_message, assessment, questions = self.reply(inquiry, session, user,
                                                       unavailable_error("MESSAGE_ID", "저장된 메시지", user_messages[0].id))
        return self.ai_turn(inquiry, [*user_messages, ai_message], assessment, questions, user)

    def reply(
        self, inquiry: Inquiry, session: ChatSession, user: User, unavailable: AppError,
    ) -> tuple[Message, InquiryAssessment, list[QuestionView]]:
        """판단 흐름을 돌려 판단 이력·AI 메시지·문의의 현재 판단값을 저장한다 (IQ-01 처리 2·3).

        모델 오류·외부 전송 제한·근거 부족은 흐름이 담당자 연결 제안(ESCALATE)으로 돌려준다.
        그 밖의 예외(검색 실패, 모델 설정 없음 등)만 503 으로 응답한다.
        """
        try:
            result = self.ai.respond(inquiry, user, self.inquiries.conversation(session.id))
        except Exception:
            logger.exception("AI 처리 실패 inquiry_id=%s", inquiry.id)
            raise unavailable

        self.inquiries.get_for_update(inquiry.id)
        out = result.output
        first_judgement = inquiry.action is None
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
        message = self.inquiries.add_message(session.id, "AI", BLOCKED_NOTICE if result.failure == "ALL_BLOCKED" else out.reply)
        self.record_ai_run(inquiry, message, result)
        inquiry.category_code = assessment.category_code
        inquiry.inquiry_type_id = assessment.inquiry_type_id
        inquiry.urgency = assessment.urgency
        inquiry.action = assessment.action
        # 세부 유형의 기본 그룹. 범위 밖이거나 세부 유형을 모르면 서비스데스크가 확인한다 (09 T08, 03 TK-09)
        if out.action == "OUT_OF_SCOPE" or inquiry_type is None:
            inquiry.recommended_group_id = self.references.triage_group_id()
        else:
            inquiry.recommended_group_id = inquiry_type.default_group_id
        if first_judgement or inquiry.title is None:     # 기본 제목은 첫 판단 때 바꾼다. 그 뒤로는 제목을 유지한다
            inquiry.title = out.title
        inquiry.updated_at = datetime_utils.now()
        self.db.commit()
        return message, assessment, [QuestionView.model_validate(q.model_dump()) for q in out.questions]

    def close(self, inquiry_id: int, user: User) -> InquiryDetail:
        """IQ-04. 담당자 연결 거절·상담 끝내기. 해결과 구분해 CLOSED_UNRESOLVED 로 남긴다."""
        inquiry = self.find_own(inquiry_id, user, for_update=True)
        if inquiry.status != "IN_PROGRESS":
            raise invalid_state(inquiry)

        close_unresolved(self.inquiries, self.audit_logs, self.alerts, inquiry, user, "NO_CONNECT")
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
            messages = [self.inquiries.add_choice(session.id, "RESOLVED")]
        else:
            messages = [self.inquiries.add_choice(session.id, "UNRESOLVED")]
            if comment:
                messages += self.add_user_message(inquiry, session, user, comment)
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

    def list_inquiries(self, query: InquiryListQuery, viewer: User) -> CountedPage[InquirySummary]:
        if query.user_id is not None and viewer.service_role != "ADMIN":
            raise AppError(ErrorCode.FORBIDDEN)
        if query.created_from and query.created_to and query.created_from > query.created_to:
            raise AppError(ErrorCode.INVALID_REQUEST)

        rows, total, status_counts = self.inquiries.search(
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
        last_ai = self.inquiries.last_ai_message_ids([row[0].id for row in rows])
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
                last_ai_message_id=last_ai.get(inquiry.id),
                created_at=inquiry.created_at,
                updated_at=inquiry.updated_at,
            )
            for inquiry, user, category, receipt_no, shown in rows
        ]
        return CountedPage.counted(items, query.page, query.size, total, status_counts, get_args(DisplayStatus))

    def get_inquiry(self, inquiry_id: int, viewer: User) -> InquiryDetail:
        return self.to_detail(self.find_viewable(inquiry_id, viewer))

    def list_assessments(self, inquiry_id: int) -> ItemList[AssessmentHistory]:
        """IQ-10. AI 원래 판단과 규칙이 바꾼 내역. 저장된 JSON 키는 응답 규칙에 맞춰 camelCase 로 준다."""
        if self.inquiries.get(inquiry_id) is None:
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        return ItemList(items=[
            AssessmentHistory(
                id=a.id,
                inquiry_id=a.inquiry_id,
                facts=camel_keys(a.facts),
                missing_items=a.missing_items or [],
                urgent_signal=a.urgent_signal,
                category_code=a.category_code,
                inquiry_type_id=a.inquiry_type_id,
                urgency=a.urgency,
                urgency_reason=a.urgency_reason,
                action=a.action,
                ai_output=camel_keys(a.ai_output),
                override_reasons=camel_keys(a.override_reasons),
                created_at=a.created_at,
            )
            for a in self.inquiries.assessments(inquiry_id)
        ])

    def list_sessions(self, inquiry_id: int, viewer: User) -> ItemList[SessionView]:
        inquiry = self.find_viewable(inquiry_id, viewer)
        return ItemList(items=[SessionView.model_validate(s) for s in self.inquiries.sessions(inquiry.id)])

    def list_messages(self, inquiry_id: int, session_id: int | None, viewer: User) -> ItemList[MessageView]:
        inquiry = self.find_viewable(inquiry_id, viewer)
        if session_id is not None and session_id not in {s.id for s in self.inquiries.sessions(inquiry.id)}:
            raise field_error(ErrorCode.VALIDATION_ERROR, "sessionId", "NOT_FOUND", "이 문의의 상담 세션이 아닙니다.")

        messages = self.inquiries.inquiry_messages(inquiry.id, session_id)
        # 짝은 문의 전체 순서로 찾으므로 세션으로 거른 목록으로 세면 안 된다
        everything = messages if session_id is None else self.inquiries.inquiry_messages(inquiry.id, None)
        questions = questions_by_message(everything, self.inquiries.assessments(inquiry.id))
        sources = self.visible_sources(messages, viewer)
        drafts = {d.id: draft_view(self.inquiries, d)
                  for d in self.inquiries.drafts({m.draft_id for m in messages if m.draft_id})}
        return ItemList(items=[to_message_view(m, sources.get(m.id, []), questions.get(m.id, []), drafts.get(m.draft_id))
                               for m in messages])

    def visible_sources(self, messages: list[Message], viewer: User) -> dict[int, list[MessageSourceView]]:
        """메시지별 출처. 보는 사람의 역할로 열람 범위 밖 출처는 뺀다 (청크_메타데이터.md 4장).

        문서 출처는 조각마다 한 줄로 저장되므로 같은 문서·버전·위치를 한 항목으로 합친다. 값은 순위가 가장 앞선 줄을
        따르고, 본문은 서로 다른 것만 이어 붙이며 그림은 모은다. 과거 사례는 문서 번호·위치가 없어 합치지 않는다.
        """
        allowed = visible_scopes(viewer.service_role)
        rows = [source for source, scope in self.inquiries.sources_with_scope([m.id for m in messages]) if scope in allowed]
        metas = self.inquiries.chunk_metas([s.chunk_id for s in rows if s.chunk_id is not None])

        def unit(s: MessageSource) -> tuple:
            if s.source_kind == "DOCUMENT":
                return s.message_id, s.doc_code, s.version, s.location
            return s.message_id, s.id

        units: dict[tuple, list[MessageSource]] = {}
        for source in rows:
            units.setdefault(unit(source), []).append(source)
        sources: dict[int, list[MessageSourceView]] = {}
        for pieces in units.values():
            first = pieces[0]
            excerpts = dict.fromkeys(p.excerpt for p in pieces if p.excerpt)
            view = MessageSourceView.model_validate(first).model_copy(update={
                "excerpt": "\n\n".join(excerpts) or first.excerpt,
                "images": images_of(metas.get(p.chunk_id) for p in pieces),
            })
            sources.setdefault(first.message_id, []).append(view)
        return sources

    def find_own(self, inquiry_id: int, user: User, for_update: bool = False) -> Inquiry:
        inquiry = self.inquiries.get_for_update(inquiry_id) if for_update else self.inquiries.get(inquiry_id)
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        return inquiry

    def add_user_message(self, inquiry: Inquiry, session: ChatSession, user: User, content: str) -> list[Message]:
        """사용자 글을 가려서 저장한다. 가렸으면 안내 SYSTEM 메시지와 SENSITIVE_INPUT 기록도 남긴다 (docs/10 5.2·6.1).

        가리다 오류가 나면 아무것도 저장하지 않고 500 이 된다 (docs/10 3.3).
        """
        masked = mask_secrets(content)
        messages = [self.inquiries.add_message(session.id, "USER", masked.text)]
        messages += [self.inquiries.add_notice(session.id, notice) for notice in mask_notices(masked)]
        record_sensitive_input(self.audit_logs, self.alerts, inquiry.id, user, masked.counts)
        return messages

    def record_ai_run(self, inquiry: Inquiry, message: Message, result: FlowResult) -> None:
        """모델 호출·답변 출처·차단·실패를 남긴다 (06 G장, docs/10 5.2, 09 3.3). 원문은 남기지 않는다.

        근거가 모두 전송 금지라 답변을 막았으면 보안 알림도 만든다 (06 security_alerts BLOCKED_DOC_QUERY).
        """
        inquiry_id = inquiry.id
        for call in result.llm_calls:
            self.inquiries.add(LlmCall(inquiry_id=inquiry_id, **asdict(call)))
        for row in result.sources:
            self.inquiries.add(MessageSource(message_id=message.id, **row))
        for event_type, outcome, reason in ai_audit_events(result):
            self.audit_logs.add(event_type, "inquiry", inquiry_id, result=outcome, reason=reason)
        if result.failure == "ALL_BLOCKED":
            detect(self.alerts, "BLOCKED_DOC_QUERY", inquiry.user_id, "inquiry", inquiry_id)

    def find_viewable(self, inquiry_id: int, viewer: User) -> Inquiry:
        inquiry = self.inquiries.get(inquiry_id)
        if inquiry is None or not self.can_view(inquiry, viewer):
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        return inquiry

    def can_view(self, inquiry: Inquiry, viewer: User) -> bool:
        return can_view_inquiry(self.inquiries, inquiry, self.inquiries.ticket(inquiry.id), viewer)

    def ai_turn(
        self, inquiry: Inquiry, messages: list[Message], assessment: InquiryAssessment,
        questions: list[QuestionView], viewer: User,
    ) -> AiTurn:
        sources = self.visible_sources(messages, viewer)
        return AiTurn(
            inquiry=self.to_detail(inquiry),
            messages=[to_message_view(m, sources.get(m.id, []), questions if m.sender == "AI" else [])
                      for m in messages],
            assessment=AssessmentView.model_validate(assessment).model_copy(update={"questions": questions}),
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


def to_message_view(
    message: Message, sources: list[MessageSourceView] | None = None, questions: list[QuestionView] | None = None,
    draft: TicketDraftView | None = None,
) -> MessageView:
    return MessageView(
        id=message.id,
        session_id=message.session_id,
        seq=message.seq,
        sender=message.sender,
        kind=message.kind,
        code=message.code,
        content=message.content,
        sources=sources or [],
        questions=questions or [],
        draft=draft,
        created_at=message.created_at,
    )


def draft_view(inquiries: InquiryRepository, draft: TicketDraft) -> TicketDraftView:
    category = inquiries.ref(Category, draft.category_code)
    inquiry_type = inquiries.ref(InquiryType, draft.inquiry_type_id)
    group = inquiries.ref(SupportGroup, draft.recommended_group_id)
    return TicketDraftView(
        id=draft.id,
        inquiry_id=draft.inquiry_id,
        session_id=draft.session_id,
        summary=draft.summary,
        target_system=draft.target_system,
        symptom=draft.symptom,
        occurred_at=draft.occurred_at,
        category_code=draft.category_code,
        category=CategoryRef.model_validate(category) if category else None,
        inquiry_type_id=draft.inquiry_type_id,
        inquiry_type=InquiryTypeRef.model_validate(inquiry_type) if inquiry_type else None,
        urgency=draft.urgency,
        urgency_reason=draft.urgency_reason,
        business_impact=draft.business_impact,
        tried_actions=draft.tried_actions,
        recommended_group_id=draft.recommended_group_id,
        recommended_group=GroupRef.model_validate(group) if group else None,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def questions_by_message(
    messages: list[Message], assessments: list[InquiryAssessment],
) -> dict[int, list[QuestionView]]:
    """AI 메시지별 추가 질문. messages 는 문의의 전체 메시지다.

    AI 메시지는 reply() 에서만 판단 이력과 함께 저장되므로 문의 안에서 n번째끼리 짝이다.
    개수가 다르면 짝을 알 수 없으니 주지 않는다.
    """
    ai_messages = [m for m in messages if m.sender == "AI"]
    if len(ai_messages) != len(assessments):
        return {}
    return {m.id: stored_questions(a) for m, a in zip(ai_messages, assessments)}


def stored_questions(assessment: InquiryAssessment) -> list[QuestionView]:
    """판단 이력의 추가 질문. ai_output 은 보정 전 값이라 최종 action 을 보고 상한도 다시 적용한다."""
    if assessment.action != "ASK_MORE" or not assessment.ai_output:
        return []
    return [QuestionView.model_validate(q) for q in cap_questions(assessment.ai_output.get("questions", []))]


def urgency_reason(result: FlowResult) -> str | None:
    """긴급도를 서버 규칙이 정했으면 그 이유, 아니면 AI 가 든 이유."""
    rules = [o["reason"] for o in result.override_reasons if o["field"] == "urgency"]
    return " ".join(rules or result.output.rationale.urgency_reasons) or None


def record_sensitive_input(
    audit_logs: AuditLogRepository, alerts: SecurityAlertRepository, inquiry_id: int, actor: User, counts: dict[str, int],
) -> None:
    """가린 유형마다 한 줄 (docs/10 5.2). 값과 원문은 남기지 않고 개수만 남긴다.

    가린 게 있으면 입력한 사람 기준으로 보안 알림 하나를 만들거나 합친다 (06 security_alerts SENSITIVE_INPUT).
    """
    for kind, count in counts.items():
        audit_logs.add("SENSITIVE_INPUT", "inquiry", inquiry_id, result=kind, actor_id=actor.id, reason=f"{count}건")
    if counts:
        detect(alerts, "SENSITIVE_INPUT", actor.id, "inquiry", inquiry_id, counts)


def ai_audit_events(result: FlowResult) -> list[tuple[str, str, str | None]]:
    """(event_type, result, reason) 목록. 시스템이 한 일이라 actor 는 비운다 (docs/10 5.2, 09 3.3)."""
    events = []
    if result.evidence is not None:
        events += [("BLOCK", "DOC_BLOCKED", code) for code in result.evidence.blocked]
        events += [("FAIL", "FILTER_FAILED", f"④ 검색 근거 {code}") for code in result.evidence.failed]
    if result.failure == "ALL_BLOCKED":
        events.append(("BLOCK", "ALL_BLOCKED", None))
    elif result.failure == "AI_FAILED" and result.error_code == "FILTER_FAILED":
        events.append(("FAIL", "FILTER_FAILED", "④ 외부 모델 호출 직전"))
    elif result.failure == "AI_FAILED":
        events.append(("FAIL", "AI_FAILED", result.error_code))
    return events


def can_view_inquiry(inquiries: InquiryRepository, inquiry: Inquiry, ticket: Ticket | None, viewer: User) -> bool:
    """본인·ADMIN, 또는 접수 담당 그룹의 활성 구성원 (IQ-03, TK-06). 문의와 접수가 같은 규칙을 쓴다."""
    if inquiry.user_id == viewer.id or viewer.service_role == "ADMIN":
        return True
    if viewer.service_role != "AGENT":
        return False
    return bool(ticket and ticket.group_id and inquiries.is_active_group_member(viewer.id, ticket.group_id))


def close_unresolved(
    inquiries: InquiryRepository, audit_logs: AuditLogRepository, alerts: SecurityAlertRepository,
    inquiry: Inquiry, actor: User, choice: str,
) -> None:
    """접수 없이 미해결로 닫는다 (IQ-04 종료, TK-03 초안 취소). choice 는 누른 버튼의 code. 커밋은 호출자가 한다."""
    now = datetime_utils.now()
    inquiry.status = "CLOSED_UNRESOLVED"
    inquiry.closed_at = inquiry.updated_at = now
    session = inquiries.current_session(inquiry.id)
    if session is not None:
        inquiries.add_choice(session.id, choice)
    end_session(session, now)
    for draft in inquiries.editing_drafts(inquiry.id):
        draft.status, draft.updated_at = "CANCELLED", now
    if any(a.urgent_signal for a in inquiries.assessments(inquiry.id)):
        audit_logs.add("URGENT_CLOSED", "inquiry", inquiry.id, result=inquiry.status, actor_id=actor.id)
        detect(alerts, "URGENT_CLOSED", inquiry.user_id, "inquiry", inquiry.id)    # 대상은 문의자 (AUDIT-04)


def end_session(session: ChatSession | None, now: datetime, reason: str = "USER_END") -> None:
    if session is not None and session.ended_at is None:
        session.ended_at, session.end_reason = now, reason


def invalid_state(inquiry: Inquiry) -> AppError:
    return AppError(ErrorCode.INQUIRY_INVALID_STATE, [
        {"reason": "CURRENT_STATUS", "message": "현재 상태", "value": inquiry.status},
    ])


def unavailable_error(reason: str, message: str, value: int) -> AppError:
    return AppError(ErrorCode.AI_UNAVAILABLE, [{"reason": reason, "message": message, "value": value}])
