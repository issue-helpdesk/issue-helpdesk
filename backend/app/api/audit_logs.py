from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth
from app.schemas.audit_log import AuditLog, AuditLogQuery
from app.schemas.common import Page
from app.services.audit_log import AuditLogServiceDep

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=Page[AuditLog])
def list_audit_logs(query: Annotated[AuditLogQuery, Query()], _: AdminAuth, service: AuditLogServiceDep) -> Page[AuditLog]:
    return service.list_logs(query)
