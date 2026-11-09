"""화면 알림 (NT-01~04). 만드는 곳은 Jira 반영이 확인되는 저장 지점이다 (jira_assign·jira_transition·jira_webhook)."""
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.models import Notification as NotificationRow, Ticket, User
from app.repositories.notification import NotificationRepositoryDep
from app.schemas.common import Page
from app.schemas.notification import (
    Notification,
    NotificationListQuery,
    NotificationReadByTicketRequest,
    NotificationReadResult,
    UnreadSummary,
)
from app.utils import datetime_utils


class NotificationService:
    def __init__(self, db: DbSession, notifications: NotificationRepositoryDep) -> None:
        self.db = db
        self.notifications = notifications

    def list_notifications(self, query: NotificationListQuery, viewer: User) -> Page[Notification]:
        rows, total = self.notifications.search(viewer.id, query.unread_only, query.offset, query.size)
        return Page.of([to_view(n, t) for n, t in rows], query.page, query.size, total)

    def unread_summary(self, viewer: User) -> UnreadSummary:
        ticket_ids = self.notifications.unread(viewer.id)
        return UnreadSummary(count=len(ticket_ids), ticket_ids=sorted(set(ticket_ids)))

    def mark_read(self, notification_id: int, viewer: User) -> Notification:
        row = self.notifications.get(notification_id, viewer.id)
        if row is None:
            raise AppError(ErrorCode.NOTIFICATION_NOT_FOUND)
        notification, ticket = row
        if notification.read_at is None:        # 처음 읽은 시각을 남긴다
            notification.read_at = datetime_utils.now()
            self.db.commit()
        return to_view(notification, ticket)

    def mark_ticket_read(self, body: NotificationReadByTicketRequest, viewer: User) -> NotificationReadResult:
        updated = self.notifications.mark_ticket_read(viewer.id, body.ticket_id, datetime_utils.now())
        self.db.commit()
        return NotificationReadResult(updated_count=updated)


def to_view(notification: NotificationRow, ticket: Ticket) -> Notification:
    return Notification(id=notification.id, kind=notification.kind, ticket_id=ticket.id, inquiry_id=ticket.inquiry_id,
                        receipt_no=ticket.receipt_no, summary=ticket.summary, read_at=notification.read_at,
                        created_at=notification.created_at)


NotificationServiceDep = Annotated[NotificationService, Depends(NotificationService)]
