from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import ColumnElement, and_, func, or_, select, update

from app.db.session import DbSession
from app.models import Notification, Ticket


def visible(recipient_id: int) -> ColumnElement[bool]:
    """본인 알림. 재배정된 뒤의 배정 알림은 지금 담당자가 아니므로 보이지 않는다."""
    return and_(Notification.recipient_id == recipient_id,
                or_(Notification.kind != "ASSIGNED", Ticket.assignee_id == recipient_id))


class NotificationRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def get(self, notification_id: int, recipient_id: int) -> tuple[Notification, Ticket] | None:
        row = self.db.execute(
            select(Notification, Ticket).join(Ticket, Ticket.id == Notification.ticket_id)
            .where(Notification.id == notification_id, visible(recipient_id))
        ).first()
        return tuple(row) if row else None

    def search(self, recipient_id: int, unread_only: bool, offset: int, size: int) -> tuple[list, int]:
        where = [visible(recipient_id)]
        if unread_only:
            where.append(Notification.read_at.is_(None))
        base = select(Notification, Ticket).join(Ticket, Ticket.id == Notification.ticket_id).where(*where)
        total = self.db.scalar(select(func.count()).select_from(base.subquery()))
        rows = self.db.execute(base.order_by(Notification.id.desc()).offset(offset).limit(size)).all()
        return rows, total

    def unread(self, recipient_id: int) -> list[int]:
        """안 읽은 알림의 접수 id. 한 줄이 알림 한 건이다."""
        return list(self.db.scalars(
            select(Notification.ticket_id).join(Ticket, Ticket.id == Notification.ticket_id)
            .where(visible(recipient_id), Notification.read_at.is_(None))
        ))

    def mark_ticket_read(self, recipient_id: int, ticket_id: int, now: datetime) -> int:
        return self.db.execute(
            update(Notification)
            .where(Notification.recipient_id == recipient_id, Notification.ticket_id == ticket_id,
                   Notification.read_at.is_(None))
            .values(read_at=now).execution_options(synchronize_session=False)
        ).rowcount


NotificationRepositoryDep = Annotated[NotificationRepository, Depends(NotificationRepository)]
