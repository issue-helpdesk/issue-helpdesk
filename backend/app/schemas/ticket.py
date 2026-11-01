from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, trimmed_str
from app.schemas.inquiry import CategoryRef, GroupRef, InquiryTypeRef, Urgency, UserRef


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


# 보낸 필드만 바꾼다. urgency·urgencyReason·recommendedGroupId 는 모르는 필드라 NOT_ALLOWED 가 된다
class DraftUpdateRequest(CamelModel):
    summary: trimmed_str(1, 2000) = None
    target_system: trimmed_str(1, 100) | None = None
    symptom: trimmed_str(1, 2000) | None = None
    occurred_at: trimmed_str(1, 200) | None = None
    business_impact: trimmed_str(1, 2000) | None = None
    tried_actions: trimmed_str(1, 2000) | None = None
    inquiry_type_id: int | None = None
    status: Literal["CANCELLED"] = None


class DraftChange(CamelModel):
    field: str
    before: str | int | None
    after: str | int | None
    reason: str | None


class DraftUpdateResult(CamelModel):
    draft: TicketDraft
    changes: list[DraftChange]


class TicketCreateRequest(CamelModel):
    draft_id: int
    draft_updated_at: KstDatetime | None     # 필수. 사용자가 확인한 초안의 updatedAt, 수정한 적 없으면 null


class Ticket(CamelModel):
    id: int
    receipt_no: str
    draft_id: int
    inquiry_id: int
    session_id: int
    requester: UserRef
    summary: str
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
    group_id: int | None
    group: GroupRef | None
    assignee_id: int | None
    assignee: UserRef | None
    jira_key: str | None
    jira_url: str | None
    jira_sync_status: str
    assign_status: str
    work_status: str | None
    requested_work_status: str | None
    transition_status: str
    work_status_confirmed_at: KstDatetime | None
    resolution_confirmed_at: KstDatetime | None
    needs_admin: bool
    display_status: str
    resolution_note: str | None
    created_at: KstDatetime
    finished_at: KstDatetime | None
    closed_at: KstDatetime | None
