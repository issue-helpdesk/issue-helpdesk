from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAuth
from app.schemas.common import Page
from app.schemas.notification import (
    Notification,
    NotificationListQuery,
    NotificationReadByTicketRequest,
    NotificationReadResult,
    UnreadSummary,
)
from app.services.notification import NotificationServiceDep

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[Notification])
def list_notifications(
    query: Annotated[NotificationListQuery, Query()], auth: CurrentAuth, service: NotificationServiceDep,
) -> Page[Notification]:
    return service.list_notifications(query, auth.user)


@router.get("/unread-count", response_model=UnreadSummary)
def unread_count(auth: CurrentAuth, service: NotificationServiceDep) -> UnreadSummary:
    return service.unread_summary(auth.user)


@router.put("/{notification_id}/read", response_model=Notification)
def mark_read(notification_id: int, auth: CurrentAuth, service: NotificationServiceDep) -> Notification:
    return service.mark_read(notification_id, auth.user)


@router.post("/read", response_model=NotificationReadResult)
def mark_ticket_read(
    body: NotificationReadByTicketRequest, auth: CurrentAuth, service: NotificationServiceDep,
) -> NotificationReadResult:
    return service.mark_ticket_read(body, auth.user)
