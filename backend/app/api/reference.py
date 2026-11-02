from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth, AgentAuth, CurrentAuth
from app.schemas.common import ItemList
from app.schemas.reference import (
    ActiveQuery,
    Category,
    Department,
    GroupMember,
    GroupMemberQuery,
    InquiryType,
    InquiryTypeQuery,
    SupportGroup,
)
from app.services.reference import ReferenceServiceDep

# 기준 정보 (RF-01~05). 경로가 리소스마다 달라 prefix 없이 둔다
router = APIRouter(tags=["reference"])


@router.get("/categories", response_model=ItemList[Category])
def list_categories(_: CurrentAuth, service: ReferenceServiceDep) -> ItemList[Category]:
    return service.list_categories()


@router.get("/inquiry-types", response_model=ItemList[InquiryType])
def list_inquiry_types(
    query: Annotated[InquiryTypeQuery, Query()], _: CurrentAuth, service: ReferenceServiceDep,
) -> ItemList[InquiryType]:
    return service.list_inquiry_types(query)


@router.get("/support-groups", response_model=ItemList[SupportGroup])
def list_support_groups(
    query: Annotated[ActiveQuery, Query()], _: AgentAuth, service: ReferenceServiceDep,
) -> ItemList[SupportGroup]:
    return service.list_support_groups(query)


@router.get("/support-groups/{group_id}/members", response_model=ItemList[GroupMember])
def list_group_members(
    group_id: int, query: Annotated[GroupMemberQuery, Query()], auth: AgentAuth, service: ReferenceServiceDep,
) -> ItemList[GroupMember]:
    return service.list_group_members(group_id, query, auth.user)


@router.get("/departments", response_model=ItemList[Department])
def list_departments(
    query: Annotated[ActiveQuery, Query()], _: AdminAuth, service: ReferenceServiceDep,
) -> ItemList[Department]:
    return service.list_departments(query)
