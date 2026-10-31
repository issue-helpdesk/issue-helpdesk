from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, or_, select

from app.db.session import DbSession
from app.models import Department, SupportGroup, SupportGroupMember, User

SORT_COLUMNS = {
    "name": User.name,
    "employeeNo": User.employee_no,
    "createdAt": User.created_at,
    "lastLoginAt": User.last_login_at,
}


class UserRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_for_update(self, user_id: int) -> User | None:
        return self.db.get(User, user_id, with_for_update=True)

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user

    def exists_employee_no(self, employee_no: str) -> bool:
        return self.db.scalar(select(User.id).where(User.employee_no == employee_no)) is not None

    def exists_email(self, email: str, exclude_user_id: int | None = None) -> bool:
        query = select(User.id).where(User.email == email)
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        return self.db.scalar(query) is not None

    def find_by_employee_no_for_update(self, employee_no: str) -> User | None:
        return self.db.scalars(select(User).where(User.employee_no == employee_no).with_for_update()).first()

    def search(
        self,
        q: str | None,
        department_id: int | None,
        service_roles: list[str],
        account_statuses: list[str],
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[User, Department | None]], int]:
        conditions = []
        if q:
            conditions.append(or_(
                User.name.icontains(q, autoescape=True),
                User.employee_no.icontains(q, autoescape=True),
                User.email.icontains(q, autoescape=True),
            ))
        if department_id is not None:
            conditions.append(User.department_id == department_id)
        if service_roles:
            conditions.append(User.service_role.in_(service_roles))
        if account_statuses:
            conditions.append(User.account_status.in_(account_statuses))

        total = self.db.scalar(select(func.count()).select_from(User).where(*conditions))
        order_by = [
            (SORT_COLUMNS[field].desc() if desc else SORT_COLUMNS[field].asc()).nulls_last()
            for field, desc in sort
        ]
        rows = self.db.execute(
            select(User, Department)
            .outerjoin(Department, Department.id == User.department_id)
            .where(*conditions)
            .order_by(*order_by, User.id)
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total

    def all_names(self) -> list[str]:
        """직원 이름 전체. AI 에 보내기 전 이름을 치환할 때 쓴다 (docs/10 3.1)."""
        return list(self.db.scalars(select(User.name).distinct()))

    def get_department(self, department_id: int) -> Department | None:
        return self.db.get(Department, department_id)

    def find_active_memberships(self, user_id: int) -> list[tuple[SupportGroupMember, str]]:
        rows = self.db.execute(
            select(SupportGroupMember, SupportGroup.name)
            .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
            .where(SupportGroupMember.user_id == user_id, SupportGroupMember.is_active.is_(True))
            .order_by(SupportGroupMember.group_id)
        )
        return [tuple(row) for row in rows]


UserRepositoryDep = Annotated[UserRepository, Depends(UserRepository)]
