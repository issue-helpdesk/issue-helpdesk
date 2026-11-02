from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AgentAuth
from app.schemas.common import Page
from app.schemas.time_off import TimeOff, TimeOffCreateRequest, TimeOffListQuery, TimeOffUpdateRequest
from app.services.time_off import TimeOffServiceDep

router = APIRouter(prefix="/time-off", tags=["time-off"])


@router.get("", response_model=Page[TimeOff])
def list_time_off(query: Annotated[TimeOffListQuery, Query()], auth: AgentAuth, service: TimeOffServiceDep) -> Page[TimeOff]:
    return service.list_time_off(query, auth.user)


@router.post("", response_model=TimeOff, status_code=status.HTTP_201_CREATED)
def create_time_off(body: TimeOffCreateRequest, auth: AgentAuth, service: TimeOffServiceDep) -> TimeOff:
    return service.create(body, auth.user)


@router.patch("/{time_off_id}", response_model=TimeOff)
def update_time_off(time_off_id: int, body: TimeOffUpdateRequest, auth: AgentAuth, service: TimeOffServiceDep) -> TimeOff:
    return service.update(time_off_id, body, auth.user)


@router.delete("/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_off(time_off_id: int, auth: AgentAuth, service: TimeOffServiceDep) -> Response:
    service.delete(time_off_id, auth.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
