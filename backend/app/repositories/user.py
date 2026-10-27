from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.db.session import DbSession
from app.models import Department, SupportGroup, SupportGroupMember, User


class UserRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def find_by_employee_no_for_update(self, employee_no: str) -> User | None:
        return self.db.scalars(select(User).where(User.employee_no == employee_no).with_for_update()).first()

    def get_department(self, department_id: int) -> Department | None:
        return self.db.get(Department, department_id)

    def find_active_memberships(self, user_id: int) -> list[tuple[SupportGroupMember, str]]:
        """(소속, 그룹 이름) 목록."""
        rows = self.db.execute(
            select(SupportGroupMember, SupportGroup.name)
            .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
            .where(SupportGroupMember.user_id == user_id, SupportGroupMember.is_active.is_(True))
            .order_by(SupportGroupMember.group_id)
        )
        return [tuple(row) for row in rows]


UserRepositoryDep = Annotated[UserRepository, Depends(UserRepository)]
