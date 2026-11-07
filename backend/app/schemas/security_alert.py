from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, PageQuery, trimmed_str
from app.schemas.inquiry import UserRef


class SecurityHistory(CamelModel):
    kind: str
    actor: UserRef | None
    reason: str | None
    created_at: KstDatetime


class SecurityAlertView(CamelModel):
    id: int
    alert_type: str
    severity: Literal['HIGH', 'MEDIUM', 'LOW']
    status: Literal['NEW', 'IN_REVIEW', 'CLOSED']
    subject: UserRef
    subject_department_name: str | None
    target_type: str
    target_id: int
    summary: str
    rule: str
    detail: dict[str, int]
    occurrence_count: int
    first_detected_at: KstDatetime
    last_detected_at: KstDatetime
    has_original: bool
    reviewer: UserRef | None
    review_started_at: KstDatetime | None
    closed_by: UserRef | None
    closed_at: KstDatetime | None
    close_reason: str | None
    history: list[SecurityHistory] = []


class SecurityQuery(PageQuery):
    status: Literal['NEW', 'IN_REVIEW', 'CLOSED'] | None = None
    alert_type: str | None = None


class SecurityReason(CamelModel):
    reason: trimmed_str(min_length=1, max_length=500)


class SecurityCounts(CamelModel):
    new: int
    in_review: int
    closed: int
    open_high: int
    total: int


class SecurityMessage(CamelModel):
    id: int
    content: str
    created_at: KstDatetime


class SecurityOriginal(CamelModel):
    messages: list[SecurityMessage]
