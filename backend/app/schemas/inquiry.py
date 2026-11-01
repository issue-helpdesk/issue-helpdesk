from datetime import date
from typing import Annotated, Literal

from fastapi import Header

from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str

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


class Message(CamelModel):
    id: int
    session_id: int
    seq: int
    sender: str
    content: str
    sources: list[MessageSource] = []
    created_at: KstDatetime


class AssessmentView(CamelModel):
    missing_items: list[str]
    urgent_signal: bool
    category_code: str | None
    inquiry_type_id: int | None
    urgency: str | None
    urgency_reason: str | None
    action: str | None


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


class SessionResume(CamelModel):
    session: Session
    inquiry: Inquiry
    next_actions: list[str]
