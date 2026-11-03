from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.audit_log import AuditLogRepositoryDep
from app.schemas.audit_log import AuditLog, AuditLogQuery
from app.schemas.common import Page, parse_sort
from app.schemas.inquiry import UserRef
from app.utils import datetime_utils


class AuditLogService:
    def __init__(self, audit_logs: AuditLogRepositoryDep) -> None:
        self.audit_logs = audit_logs

    def list_logs(self, query: AuditLogQuery) -> Page[AuditLog]:
        """OP-04."""
        if query.target_id is not None and query.target_type is None:
            raise AppError(ErrorCode.INVALID_REQUEST)
        if query.created_from and query.created_to and query.created_from > query.created_to:
            raise AppError(ErrorCode.INVALID_REQUEST)
        rows, total = self.audit_logs.search(
            event_types=query.event_type,
            target_type=query.target_type,
            target_id=query.target_id,
            actor_id=query.actor_id,
            created_from=datetime_utils.kst_start(query.created_from) if query.created_from else None,
            created_before=datetime_utils.kst_start(query.created_to + timedelta(days=1)) if query.created_to else None,
            newest_first=parse_sort(query.sort)[0][1],
            offset=query.offset,
            limit=query.size,
        )
        items = [
            AuditLog(
                id=log.id,
                event_type=log.event_type,
                target_type=log.target_type,
                target_id=log.target_id,
                actor_id=log.actor_id,
                actor=UserRef.model_validate(actor) if actor else None,
                result=log.result,
                reason=log.reason,
                created_at=log.created_at,
            )
            for log, actor in rows
        ]
        return Page.of(items, query.page, query.size, total)


AuditLogServiceDep = Annotated[AuditLogService, Depends(AuditLogService)]
