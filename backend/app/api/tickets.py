from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AdminAuth, CurrentAuth
from app.schemas.common import ItemList, Page
from app.schemas.ticket import (
    AssignmentLog,
    AssignmentRequest,
    DraftUpdateRequest,
    DraftUpdateResult,
    IntegrationJob,
    StatusHistory,
    Ticket,
    TicketCreateRequest,
    TicketDraft,
    TicketListQuery,
    TicketSummary,
    TicketUpdateRequest,
)
from app.services.ticket import TicketServiceDep

# 접수 (TK-01~11). 초안 생성은 문의 아래 경로라 prefix 없이 둔다
router = APIRouter(tags=["tickets"])


@router.post("/inquiries/{inquiry_id}/ticket-drafts", response_model=TicketDraft, status_code=status.HTTP_201_CREATED)
def create_draft(inquiry_id: int, auth: CurrentAuth, service: TicketServiceDep) -> TicketDraft:
    return service.create_draft(inquiry_id, auth.user)


@router.get("/ticket-drafts/{draft_id}", response_model=TicketDraft)
def get_draft(draft_id: int, auth: CurrentAuth, service: TicketServiceDep) -> TicketDraft:
    return service.get_draft(draft_id, auth.user)


@router.patch("/ticket-drafts/{draft_id}", response_model=DraftUpdateResult)
def update_draft(
    draft_id: int, body: DraftUpdateRequest, auth: CurrentAuth, service: TicketServiceDep,
) -> DraftUpdateResult:
    return service.update_draft(draft_id, body, auth.user)


@router.post("/tickets", response_model=Ticket, status_code=status.HTTP_201_CREATED)
def confirm_ticket(body: TicketCreateRequest, response: Response, auth: CurrentAuth, service: TicketServiceDep) -> Ticket:
    ticket, created = service.confirm(body, auth.user)
    if not created:
        response.status_code = status.HTTP_200_OK      # 이미 접수된 초안
    return ticket


@router.get("/tickets", response_model=Page[TicketSummary])
def list_tickets(
    query: Annotated[TicketListQuery, Query()], auth: CurrentAuth, service: TicketServiceDep,
) -> Page[TicketSummary]:
    return service.list_tickets(query, auth.user)


@router.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: int, auth: CurrentAuth, service: TicketServiceDep) -> Ticket:
    return service.get_ticket(ticket_id, auth.user)


@router.get("/tickets/{ticket_id}/status-history", response_model=ItemList[StatusHistory])
def status_history(ticket_id: int, auth: CurrentAuth, service: TicketServiceDep) -> ItemList[StatusHistory]:
    return service.status_history(ticket_id, auth.user)


@router.patch("/tickets/{ticket_id}", response_model=Ticket, status_code=status.HTTP_202_ACCEPTED)
def request_transition(
    ticket_id: int, body: TicketUpdateRequest, auth: CurrentAuth, service: TicketServiceDep,
) -> Ticket:
    """요청만 받는다. 반영 결과는 TK-06 으로 확인한다."""
    return service.request_transition(ticket_id, body, auth.user)


@router.put("/tickets/{ticket_id}/assignment", response_model=Ticket)
def assign(ticket_id: int, body: AssignmentRequest, auth: CurrentAuth, service: TicketServiceDep) -> Ticket:
    return service.assign(ticket_id, body, auth.user)


@router.get("/tickets/{ticket_id}/assignment-logs", response_model=ItemList[AssignmentLog])
def assignment_logs(ticket_id: int, auth: CurrentAuth, service: TicketServiceDep) -> ItemList[AssignmentLog]:
    return service.assignment_logs(ticket_id, auth.user)


@router.get("/tickets/{ticket_id}/integration-jobs", response_model=ItemList[IntegrationJob])
def integration_jobs(ticket_id: int, _: AdminAuth, service: TicketServiceDep) -> ItemList[IntegrationJob]:
    return service.integration_jobs(ticket_id)
