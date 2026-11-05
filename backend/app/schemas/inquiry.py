from datetime import date
from typing import Annotated, Literal

from fastapi import Header

from app.schemas.common import CamelModel, GuideImage, KstDatetime, PageQuery, sort_param, trimmed_str

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]

InquiryStatus = Literal["IN_PROGRESS", "AI_RESOLVED", "UNCONFIRMED", "CLOSED_UNRESOLVED", "RECEIVED", "HANDED_OFF"]
DisplayStatus = Literal["unconfirmed", "in_progress", "ai_resolved", "unresolved", "received", "assigned", "progress",
                        "awaiting_confirm", "resolved"]
Urgency = Literal["P1", "P2", "P3", "P4"]


class CategoryRef(CamelModel):
    code: str
    name: str


class InquiryTypeRef(CamelModel):
    id: int
    code: str
    name: str


class GroupRef(CamelModel):
    id: int
    name: str


class UserRef(CamelModel):
    id: int
    employee_no: str
    name: str


class TicketRef(CamelModel):
    id: int
    receipt_no: str
    jira_key: str | None
    work_status: str | None


class Inquiry(CamelModel):
    id: int
    user_id: int
    user: UserRef
    title: str | None
    status: str
    display_status: str
    category_code: str | None
    category: CategoryRef | None
    inquiry_type_id: int | None
    inquiry_type: InquiryTypeRef | None
    urgency: str | None
    action: str | None
    recommended_group_id: int | None
    recommended_group: GroupRef | None
    resolution_result: str | None
    current_session_id: int | None
    active_draft_id: int | None
    ticket: TicketRef | None
    created_at: KstDatetime
    updated_at: KstDatetime | None
    closed_at: KstDatetime | None


class InquirySummary(CamelModel):
    id: int
    user: UserRef
    title: str | None
    status: str
    display_status: str
    category: CategoryRef | None
    urgency: str | None
    receipt_no: str | None
    created_at: KstDatetime
    updated_at: KstDatetime | None


class InquiryListQuery(PageQuery):
    sort: list[sort_param("createdAt", "updatedAt", "urgency")] = ["createdAt,desc"]
    display_status: list[DisplayStatus] = []
    status: list[InquiryStatus] = []
    category_code: list[trimmed_str(1, 20)] = []
    urgency: list[Urgency] = []
    created_from: date | None = None
    created_to: date | None = None
    q: trimmed_str(max_length=100) | None = None
    user_id: int | None = None


class Session(CamelModel):
    id: int
    inquiry_id: int
    started_at: KstDatetime
    ended_at: KstDatetime | None
    end_reason: str | None


class MessageSource(CamelModel):
    id: int
    source_kind: str
    doc_code: str | None
    version: str | None
    location: str | None
    excerpt: str | None
    rank: int | None
    images: list[GuideImage] = []           # 본문에 나오는 그림. 파일은 DC-11


class Question(CamelModel):
    label: str | None = None                # 답을 글로 묶을 때 붙이는 이름. 이 칸이 생기기 전 저장된 질문은 null
    text: str
    options: list[str]                      # 비어 있으면 입력창으로 보여 주는 질문
    allow_text: bool = False                # 선택지와 함께 직접 입력도 받는가


class TicketDraft(CamelModel):
    id: int
    inquiry_id: int
    session_id: int
    summary: str | None
    target_system: str | None
    symptom: str | None
    occurred_at: str | None
    category_code: str | None
    category: CategoryRef | None
    inquiry_type_id: int | None
    inquiry_type: InquiryTypeRef | None
    urgency: Urgency | None
    urgency_reason: str | None
    business_impact: str | None
    tried_actions: str | None
    recommended_group_id: int | None
    recommended_group: GroupRef | None
    status: str
    created_at: KstDatetime
    updated_at: KstDatetime | None


class Message(CamelModel):
    id: int
    session_id: int
    seq: int
    sender: str
    kind: str                               # TEXT / CHOICE / NOTICE / DRAFT_CARD / TICKET_CARD
    code: str | None = None                 # CHOICE 가 누른 버튼. 문구는 화면이 정한다
    content: str | None                     # 사용자 글·AI 답변·가림 안내만 값이 있다
    sources: list[MessageSource] = []
    questions: list[Question] = []          # 이 AI 메시지가 물은 추가 질문. 본문에는 인사말만 저장된다
    draft: TicketDraft | None = None        # DRAFT_CARD 의 초안. 목록 조회(IQ-07)에서만 채운다
    created_at: KstDatetime


class AssessmentView(CamelModel):
    missing_items: list[str]
    urgent_signal: bool
    category_code: str | None
    inquiry_type_id: int | None
    urgency: str | None
    urgency_reason: str | None
    action: str | None
    questions: list[Question] = []


class AiTurn(CamelModel):
    inquiry: Inquiry
    messages: list[Message]
    assessment: AssessmentView | None
    next_actions: list[str]


class MessageRequest(CamelModel):
    content: trimmed_str(1, 4000)


class CloseRequest(CamelModel):
    status: Literal["CLOSED_UNRESOLVED"]


class ResolutionRequest(CamelModel):
    resolution_result: Literal["RESOLVED", "UNRESOLVED"]    # NO_RESPONSE 는 예약값이라 받지 않는다
    comment: trimmed_str(1, 4000) | None = None           # UNRESOLVED 일 때만 저장한다


class Assessment(CamelModel):
    id: int
    inquiry_id: int
    facts: dict | None
    missing_items: list[str]
    urgent_signal: bool
    category_code: str | None
    inquiry_type_id: int | None
    urgency: str | None
    urgency_reason: str | None
    action: str | None
    ai_output: dict | None              # AI 원래 판단. 안전 기본값·근거 전체 차단이면 null
    override_reasons: list[dict]        # 규칙이 바꾼 내역
    created_at: KstDatetime


class SessionResume(CamelModel):
    session: Session
    inquiry: Inquiry
    next_actions: list[str]
