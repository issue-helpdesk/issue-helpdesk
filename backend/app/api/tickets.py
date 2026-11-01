from fastapi import APIRouter, Response, status

from app.api.deps import CurrentAuth
from app.schemas.ticket import DraftUpdateRequest, DraftUpdateResult, Ticket, TicketCreateRequest, TicketDraft
from app.services.ticket import TicketServiceDep

# 접수 (TK-01~04). 초안 생성은 문의 아래 경로라 prefix 없이 둔다
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
