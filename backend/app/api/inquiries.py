from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentAuth
from app.schemas.common import ItemList, Page
from app.schemas.inquiry import (
    AiTurn,
    CloseRequest,
    IdempotencyKey,
    Inquiry,
    InquiryListQuery,
    InquirySummary,
    Message,
    MessageRequest,
    ResolutionRequest,
    Session,
    SessionResume,
)
from app.services.inquiry import InquiryServiceDep

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post("", response_model=AiTurn, status_code=status.HTTP_201_CREATED)
def start_inquiry(
    body: MessageRequest, _key: IdempotencyKey, auth: CurrentAuth, service: InquiryServiceDep,
) -> AiTurn:
    return service.start(body.content, auth.user)


@router.get("", response_model=Page[InquirySummary])
def list_inquiries(
    query: Annotated[InquiryListQuery, Query()], auth: CurrentAuth, service: InquiryServiceDep,
) -> Page[InquirySummary]:
    return service.list_inquiries(query, auth.user)


@router.get("/{inquiry_id}", response_model=Inquiry)
def get_inquiry(inquiry_id: int, auth: CurrentAuth, service: InquiryServiceDep) -> Inquiry:
    return service.get_inquiry(inquiry_id, auth.user)


@router.patch("/{inquiry_id}", response_model=Inquiry)
def close_inquiry(inquiry_id: int, _body: CloseRequest, auth: CurrentAuth, service: InquiryServiceDep) -> Inquiry:
    return service.close(inquiry_id, auth.user)


@router.get("/{inquiry_id}/sessions", response_model=ItemList[Session])
def list_sessions(inquiry_id: int, auth: CurrentAuth, service: InquiryServiceDep) -> ItemList[Session]:
    return service.list_sessions(inquiry_id, auth.user)


@router.post("/{inquiry_id}/sessions", response_model=SessionResume)
def resume_session(inquiry_id: int, auth: CurrentAuth, service: InquiryServiceDep) -> SessionResume:
    return service.resume(inquiry_id, auth.user)


@router.get("/{inquiry_id}/messages", response_model=ItemList[Message])
def list_messages(
    inquiry_id: int,
    auth: CurrentAuth,
    service: InquiryServiceDep,
    session_id: Annotated[int | None, Query(alias="sessionId")] = None,
) -> ItemList[Message]:
    return service.list_messages(inquiry_id, session_id, auth.user)


@router.post("/{inquiry_id}/messages", response_model=AiTurn, status_code=status.HTTP_201_CREATED)
def send_message(
    inquiry_id: int, body: MessageRequest, _key: IdempotencyKey, auth: CurrentAuth, service: InquiryServiceDep,
) -> AiTurn:
    return service.send_message(inquiry_id, body.content, auth.user)


@router.put("/{inquiry_id}/resolution", response_model=AiTurn)
def confirm_resolution(
    inquiry_id: int, body: ResolutionRequest, _key: IdempotencyKey, auth: CurrentAuth, service: InquiryServiceDep,
) -> AiTurn:
    return service.resolve(inquiry_id, body.resolution_result, body.comment, auth.user)
