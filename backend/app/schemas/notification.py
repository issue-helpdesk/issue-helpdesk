from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, PageQuery


class Notification(CamelModel):
    id: int
    kind: Literal["ASSIGNED", "FIN"]
    ticket_id: int
    inquiry_id: int
    receipt_no: str
    summary: str | None
    read_at: KstDatetime | None
    created_at: KstDatetime


class NotificationListQuery(PageQuery):
    unread_only: bool = False


class UnreadSummary(CamelModel):
    count: int
    ticket_ids: list[int]           # 안 읽은 알림이 있는 접수. 목록의 표시·필터에 쓴다


class NotificationReadByTicketRequest(CamelModel):
    ticket_id: int


class NotificationReadResult(CamelModel):
    updated_count: int
