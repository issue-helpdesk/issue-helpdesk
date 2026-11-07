from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth
from app.schemas.common import Page
from app.schemas.security_alert import SecurityAlertView, SecurityCounts, SecurityOriginal, SecurityQuery, SecurityReason
from app.services.security_alert import SecurityAlertServiceDep

router = APIRouter(prefix='/security-alerts', tags=['security-alerts'])


@router.get('', response_model=Page[SecurityAlertView])
def list_alerts(query: Annotated[SecurityQuery, Query()], _: AdminAuth, service: SecurityAlertServiceDep):
    return service.list(query)


@router.get('/counts', response_model=SecurityCounts)
def counts(_: AdminAuth, service: SecurityAlertServiceDep):
    return service.counts()


@router.get('/{alert_id}', response_model=SecurityAlertView)
def get_alert(alert_id: int, _: AdminAuth, service: SecurityAlertServiceDep):
    return service.view(service.find(alert_id))


@router.post('/{alert_id}/review', response_model=SecurityAlertView)
def start_review(alert_id: int, auth: AdminAuth, service: SecurityAlertServiceDep):
    return service.start(alert_id, auth.user)


@router.post('/{alert_id}/close', response_model=SecurityAlertView)
def close_alert(alert_id: int, body: SecurityReason, auth: AdminAuth, service: SecurityAlertServiceDep):
    return service.close(alert_id, auth.user, body.reason)


@router.post('/{alert_id}/original', response_model=SecurityOriginal)
def view_context(alert_id: int, body: SecurityReason, auth: AdminAuth, service: SecurityAlertServiceDep):
    return service.context(alert_id, auth.user, body.reason)
