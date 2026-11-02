from datetime import date
from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str
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
    mask_notice: str | None = None       # 고친 글에서 민감정보를 가렸으면 초안 카드 위 안내 (docs/10 6.1 MASK_NOTICE_DRAFT)


WorkStatus = Literal["RDY", "WIP", "FIN", "CLS"]
JiraSyncStatus = Literal["PENDING", "VERIFYING", "SYNCED", "NEEDS_ADMIN"]
AssignStatus = Literal["PENDING", "ASSIGNED", "NEEDS_ADMIN"]
TicketScope = Literal["REQUESTER", "ASSIGNED", "ALL"]


class TicketListQuery(PageQuery):
    view: TicketScope | None = None          # 없으면 권한별 기본값 (EMPLOYEE REQUESTER, AGENT ASSIGNED, ADMIN ALL)
    sort: list[sort_param("createdAt", "urgency", "workStatus")] = ["createdAt,desc"]
    work_status: list[WorkStatus] = []
    jira_sync_status: list[JiraSyncStatus] = []
    assign_status: list[AssignStatus] = []
    needs_admin: bool | None = None
    category_code: list[trimmed_str(1, 20)] = []
    urgency: list[Urgency] = []
    group_id: int | None = None
    assignee_id: int | None = None
    created_from: date | None = None
    created_to: date | None = None
    q: trimmed_str(max_length=100) | None = None


class TicketSummary(CamelModel):
    id: int
    receipt_no: str
    jira_key: str | None
    inquiry_id: int
    requester: UserRef
    summary: str
    category: CategoryRef | None
    urgency: Urgency | None
    group: GroupRef | None
    assignee: UserRef | None
    jira_sync_status: str
    assign_status: str
    work_status: str | None
    requested_work_status: str | None
    transition_status: str
    work_status_confirmed_at: KstDatetime | None
    needs_admin: bool
    display_status: str
    created_at: KstDatetime


class StatusHistory(CamelModel):
    id: int
    ticket_id: int
    from_status: str | None
    to_status: str
    source: str
    actor_id: int | None
    actor: UserRef | None
    reason: str | None
    changed_at: KstDatetime


class TicketUpdateRequest(CamelModel):
    work_status: Literal["WIP", "FIN", "CLS"] | None = None
    resolution_note: trimmed_str(1, 4000) | None = None      # 담당 그룹·ADMIN 만. 이것만 보내면 처리 결과만 수정
    reason: trimmed_str(1, 2000) | None = None               # FIN → WIP(미해결)일 때 남은 증상


class AssignmentRequest(CamelModel):
    group_id: int
    assignee_id: int | None                                  # 필수. null 이면 그 그룹에서 자동배정
    reason: trimmed_str(max_length=500) | None = None        # 비면 ASSIGNMENT_REASON_REQUIRED


class AssignmentLog(CamelModel):
    id: int
    ticket_id: int
    event: str
    group_id: int | None
    group: GroupRef | None
    assignee_id: int | None
    assignee: UserRef | None
    rule_id: int | None
    reason: str | None
    actor_id: int | None
    actor: UserRef | None
    created_at: KstDatetime


class IntegrationJob(CamelModel):
    id: int
    ticket_id: int
    job_type: str
    retry_of_job_id: int | None
    status: str
    attempts: int
    next_retry_at: KstDatetime | None
    last_error: str | None
    idempotency_key: str
    created_at: KstDatetime
    updated_at: KstDatetime | None


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
