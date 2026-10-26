from typing import Annotated

from fastapi import Depends

from app.models import User
from app.repositories.user import UserRepositoryDep
from app.schemas.auth import DepartmentRef, Me, SupportGroupMembership


class UserService:
    def __init__(self, users: UserRepositoryDep) -> None:
        self.users = users

    def get_me(self, user: User) -> Me:
        department = self.users.get_department(user.department_id) if user.department_id else None
        return Me(
            id=user.id,
            employee_no=user.employee_no,
            name=user.name,
            email=user.email,
            department_id=user.department_id,
            department=DepartmentRef.model_validate(department) if department else None,
            position=user.position,
            service_role=user.service_role,
            account_status=user.account_status,
            password_change_required=user.password_changed_at is None,
            last_login_at=user.last_login_at,
            support_groups=[
                SupportGroupMembership(
                    group_id=m.group_id, group_name=name, member_role=m.member_role, assignable=m.assignable,
                )
                for m, name in self.users.find_active_memberships(user.id)
            ],
        )


UserServiceDep = Annotated[UserService, Depends(UserService)]
