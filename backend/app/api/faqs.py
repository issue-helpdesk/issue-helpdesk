from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AdminAuth, CurrentAuth
from app.schemas.common import Page
from app.schemas.faq import Faq, FaqCreateRequest, FaqDetail, FaqListQuery, FaqUpdateRequest
from app.services.faq import FaqServiceDep

router = APIRouter(prefix="/faqs", tags=["faqs"])


@router.get("", response_model=Page[Faq])
def list_faqs(query: Annotated[FaqListQuery, Query()], auth: CurrentAuth, service: FaqServiceDep) -> Page[Faq]:
    return service.list_faqs(query, auth.user)


@router.get("/{faq_id}", response_model=FaqDetail)
def get_faq(faq_id: int, auth: CurrentAuth, service: FaqServiceDep) -> FaqDetail:
    return service.get_faq(faq_id, auth.user)


@router.post("", response_model=Faq, status_code=status.HTTP_201_CREATED)
def create_faq(body: FaqCreateRequest, auth: AdminAuth, service: FaqServiceDep) -> Faq:
    return service.create(body, auth.user)


@router.patch("/{faq_id}", response_model=Faq)
def update_faq(faq_id: int, body: FaqUpdateRequest, auth: AdminAuth, service: FaqServiceDep) -> Faq:
    return service.update(faq_id, body, auth.user)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faq(faq_id: int, auth: AdminAuth, service: FaqServiceDep) -> Response:
    service.delete(faq_id, auth.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
