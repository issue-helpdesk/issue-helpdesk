from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import and_, func, or_, select

from app.db.session import DbSession
from app.models import AuditLog, Ticket, User


class AuditLogRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, event_type: str, target_type: str, target_id: int, result: str | None = None, actor_id: int | None = None, reason: str | None = None) -> None:
        from app.repositories.security_alert import record_security_event

        record_security_event(self.db, event_type, target_type, target_id, result, actor_id)
        self.db.add(AuditLog(event_type=event_type, target_type=target_type, target_id=target_id, actor_id=actor_id, result=result, reason=reason))

    def search(
        self,
        *,
        event_types: list[str],
        target_type: str | None,
        target_id: int | None,
        actor_id: int | None,
        created_from: datetime | None,
        created_before: datetime | None,
        newest_first: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[AuditLog, User | None, int | None, str | None]], int]:
        conditions = []
        if event_types:
            conditions.append(AuditLog.event_type.in_(event_types))
        if target_type is not None:
            conditions.append(AuditLog.target_type == target_type)
        if target_id is not None:
            conditions.append(AuditLog.target_id == target_id)
        if actor_id is not None:
            conditions.append(AuditLog.actor_id == actor_id)
        if created_from is not None:
            conditions.append(AuditLog.created_at >= created_from)
        if created_before is not None:
            conditions.append(AuditLog.created_at < created_before)
        total = self.db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
        order = (AuditLog.created_at.desc(), AuditLog.id.desc()) if newest_first else (AuditLog.created_at.asc(), AuditLog.id.asc())
        ticket_link = or_(
            and_(AuditLog.target_type == "ticket", Ticket.id == AuditLog.target_id),
            and_(AuditLog.target_type == "inquiry", Ticket.inquiry_id == AuditLog.target_id),
        )
        rows = self.db.execute(
            select(AuditLog, User, Ticket.id, Ticket.receipt_no)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .outerjoin(Ticket, ticket_link)
            .where(*conditions)
            .order_by(*order).offset(offset).limit(limit)
        )
        return [tuple(r) for r in rows], total



AuditLogRepositoryDep = Annotated[AuditLogRepository, Depends(AuditLogRepository)]
