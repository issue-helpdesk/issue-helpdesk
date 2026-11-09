from typing import Annotated

from fastapi import Depends
from sqlalchemy import exists, func, select

from app.db.session import DbSession
from app.models import Category, Department, InquiryType, MemberSkill, SupportGroup, SupportGroupMember, User
from app.repositories.assignment import AssignmentRepository


class ReferenceRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def list_categories(self) -> list[Category]:
        return list(self.db.scalars(select(Category).order_by(Category.code)))

    def find_category_codes(self, codes: list[str]) -> set[str]:
        return set(self.db.scalars(select(Category.code).where(Category.code.in_(codes))))

    def list_inquiry_types(self, category_codes: list[str], is_active: bool) -> list[tuple[InquiryType, SupportGroup]]:
        query = (
            select(InquiryType, SupportGroup)
            .join(SupportGroup, SupportGroup.id == InquiryType.default_group_id)
            .where(InquiryType.is_active.is_(is_active))
            .order_by(InquiryType.code)
        )
        if category_codes:
            query = query.where(InquiryType.category_code.in_(category_codes))
        return [tuple(row) for row in self.db.execute(query)]

    def get_inquiry_type_by_code(self, code: str) -> InquiryType | None:
        return self.db.scalar(select(InquiryType).where(InquiryType.code == code))

    def triage_group_id(self) -> int | None:
        """서비스데스크(확인 그룹). 활성 그룹 중 is_triage 인 것."""
        return self.db.scalar(
            select(SupportGroup.id)
            .where(SupportGroup.is_triage.is_(True), SupportGroup.is_active.is_(True))
            .order_by(SupportGroup.id)
        )

    def list_support_groups(self, is_active: bool) -> list[SupportGroup]:
        return list(self.db.scalars(
            select(SupportGroup).where(SupportGroup.is_active.is_(is_active)).order_by(SupportGroup.name, SupportGroup.id)
        ))

    def get_support_group(self, group_id: int) -> SupportGroup | None:
        return self.db.get(SupportGroup, group_id)

    def is_group_manager(self, group_id: int, user_id: int) -> bool:
        """활성 그룹의 활성 구성원이면서 member_role 이 MANAGER 인지. 서비스 역할은 호출하는 쪽에서 확인한다."""
        return self.db.scalar(
            select(SupportGroupMember.user_id)
            .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
            .where(
                SupportGroupMember.group_id == group_id,
                SupportGroupMember.user_id == user_id,
                SupportGroupMember.member_role == "MANAGER",
                SupportGroupMember.is_active.is_(True),
                SupportGroup.is_active.is_(True),
            )
        ) is not None

    def list_group_members(
        self, group_id: int, assignable_only: bool, inquiry_type_id: int | None,
    ) -> list[tuple[SupportGroupMember, User]]:
        query = (
            select(SupportGroupMember, User)
            .join(User, User.id == SupportGroupMember.user_id)
            .where(SupportGroupMember.group_id == group_id)
            .order_by(User.name, User.id)
        )
        if assignable_only:
            # TK-09 배정 자격 (docs/api/03 TK-09). 그룹 활성 여부는 서비스에서 확인한다
            query = query.where(
                User.account_status == "ACTIVE",
                User.service_role.in_(("AGENT", "ADMIN")),
                SupportGroupMember.is_active.is_(True),
                SupportGroupMember.assignable.is_(True),
                func.trim(SupportGroupMember.jira_account_id) != "",
            )
        if inquiry_type_id is not None:
            query = query.where(exists().where(
                MemberSkill.user_id == SupportGroupMember.user_id,
                MemberSkill.inquiry_type_id == inquiry_type_id,
            ))
        return [tuple(row) for row in self.db.execute(query)]

    def find_skills(self, user_ids: list[int]) -> list[tuple[int, InquiryType]]:
        rows = self.db.execute(
            select(MemberSkill.user_id, InquiryType)
            .join(InquiryType, InquiryType.id == MemberSkill.inquiry_type_id)
            .where(MemberSkill.user_id.in_(user_ids))
            .order_by(InquiryType.code)
        )
        return [tuple(row) for row in rows]

    def count_open_tickets(self, user_ids: list[int]) -> dict[int, int]:
        """담당자별 업무량. 자동배정과 같은 기준이고 (docs/11 3장), 그룹과 관계없이 그 사람의 전체 업무량이다."""
        workload = AssignmentRepository(self.db).workload(user_ids, None)
        return {user_id: sum(counts.values()) for user_id, counts in workload.items()}

    def list_departments(self, is_active: bool) -> list[Department]:
        return list(self.db.scalars(
            select(Department).where(Department.is_active.is_(is_active)).order_by(Department.name, Department.id)
        ))


ReferenceRepositoryDep = Annotated[ReferenceRepository, Depends(ReferenceRepository)]
