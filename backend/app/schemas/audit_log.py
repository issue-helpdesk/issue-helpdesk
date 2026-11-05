from datetime import date

from pydantic import Field

from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str
from app.schemas.inquiry import UserRef


class AuditLogQuery(PageQuery):
    size: int = Field(50, ge=1, le=100)
    sort: list[sort_param("createdAt")] = ["createdAt,desc"]
    event_type: list[trimmed_str(1, 50)] = []
    target_type: trimmed_str(1, 50) | None = None
    target_id: int | None = None
    actor_id: int | None = None
    created_from: date | None = None
    created_to: date | None = None


class AuditLog(CamelModel):
    id: int
    event_type: str
    target_type: str | None
    target_id: int | None
    ticket_id: int | None
    receipt_no: str | None
    actor_id: int | None
    actor: UserRef | None
    result: str | None
    reason: str | None
    created_at: KstDatetime
