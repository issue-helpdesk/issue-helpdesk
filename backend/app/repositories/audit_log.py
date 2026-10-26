from typing import Annotated

from fastapi import Depends

from app.db.session import DbSession
from app.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, event_type: str, target_type: str, target_id: int, result: str | None = None,
            actor_id: int | None = None) -> None:
        self.db.add(AuditLog(event_type=event_type, target_type=target_type, target_id=target_id,
                             actor_id=actor_id, result=result))


AuditLogRepositoryDep = Annotated[AuditLogRepository, Depends(AuditLogRepository)]
