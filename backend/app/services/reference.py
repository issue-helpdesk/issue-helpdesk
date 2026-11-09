from collections import defaultdict
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.db.session import DbSession
from app.models import User
from app.repositories.reference import ReferenceRepositoryDep
from app.schemas.common import ItemList
from app.schemas.inquiry import GroupRef, InquiryTypeRef, UserRef
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
from app.services.time_off import current_absentees


class ReferenceService:
    def __init__(self, db: DbSession, references: ReferenceRepositoryDep) -> None:
        self.db = db
        self.references = references

    def list_categories(self) -> ItemList[Category]:
        return ItemList(items=[Category.model_validate(c) for c in self.references.list_categories()])

    def list_inquiry_types(self, query: InquiryTypeQuery) -> ItemList[InquiryType]:
        unknown = set(query.category_code) - self.references.find_category_codes(query.category_code)
        if unknown:
            raise field_error(ErrorCode.VALIDATION_ERROR, "categoryCode", "NOT_FOUND",
                              f"존재하지 않는 분류입니다: {', '.join(sorted(unknown))}")
        rows = self.references.list_inquiry_types(query.category_code, query.is_active)
        return ItemList(items=[
            InquiryType(
                id=t.id,
                code=t.code,
                category_code=t.category_code,
                name=t.name,
                request_kind=t.request_kind,
                default_urgency=t.default_urgency,
                default_group_id=t.default_group_id,
                default_group=GroupRef.model_validate(group),
                is_active=t.is_active,
            )
            for t, group in rows
        ])

    def list_support_groups(self, query: ActiveQuery) -> ItemList[SupportGroup]:
        groups = self.references.list_support_groups(query.is_active)
        return ItemList(items=[SupportGroup.model_validate(g) for g in groups])

    def list_group_members(self, group_id: int, query: GroupMemberQuery, viewer: User) -> ItemList[GroupMember]:
        group = self.references.get_support_group(group_id)
        if group is None:
            raise AppError(ErrorCode.NOT_FOUND)
        is_admin = viewer.service_role == "ADMIN"
        if not is_admin and not self.references.is_group_manager(group_id, viewer.id):
            raise AppError(ErrorCode.FORBIDDEN)

        assignable_only = bool(query.assignable)
        if assignable_only and not group.is_active:
            return ItemList(items=[])    # 비활성 그룹에는 배정할 수 없다
        rows = self.references.list_group_members(group_id, assignable_only, query.inquiry_type_id)

        user_ids = [user.id for _, user in rows]
        skills = defaultdict(list)
        for user_id, inquiry_type in self.references.find_skills(user_ids) if user_ids else []:
            skills[user_id].append(InquiryTypeRef.model_validate(inquiry_type))
        open_counts = self.references.count_open_tickets(user_ids) if user_ids else {}
        absent = current_absentees(self.db)

        return ItemList(items=[
            GroupMember(
                user_id=user.id,
                user=UserRef.model_validate(user),
                position=user.position,
                member_role=member.member_role,
                assignable=member.assignable,
                has_jira_account=bool((member.jira_account_id or "").strip()),
                jira_account_id=member.jira_account_id if is_admin else None,
                is_active=member.is_active,
                skills=skills[user.id],
                open_ticket_count=open_counts.get(user.id, 0),
                on_leave=user.id in absent,
            )
            for member, user in rows
        ])

    def list_departments(self, query: ActiveQuery) -> ItemList[Department]:
        departments = self.references.list_departments(query.is_active)
        return ItemList(items=[Department.model_validate(d) for d in departments])


ReferenceServiceDep = Annotated[ReferenceService, Depends(ReferenceService)]
