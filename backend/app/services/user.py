from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.core.security import generate_temporary_password, hash_password
from app.db.session import DbSession
from app.models import User
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.auth_session import AuthSessionRepositoryDep
from app.repositories.user import UserRepositoryDep
from app.utils import datetime_utils
from app.schemas.auth import DepartmentRef, Me, SupportGroupMembership
from app.schemas.common import Page, parse_sort
from app.schemas.user import (
    User as UserDetail,
    TemporaryPasswordResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserListQuery,
    UserSummary,
    UserUpdateRequest,
)


class UserService:
    def __init__(
        self,
        db: DbSession,
        users: UserRepositoryDep,
        sessions: AuthSessionRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
    ) -> None:
        self.db = db
        self.users = users
        self.sessions = sessions
        self.audit_logs = audit_logs

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

    def list_users(self, query: UserListQuery) -> Page[UserSummary]:
        rows, total = self.users.search(
            q=query.q or None,
            department_id=query.department_id,
            service_roles=query.service_role,
            account_statuses=query.account_status,
            sort=parse_sort(query.sort),
            offset=query.offset,
            limit=query.size,
        )
        items = [
            UserSummary(
                id=user.id,
                employee_no=user.employee_no,
                name=user.name,
                email=user.email,
                department=DepartmentRef.model_validate(department) if department else None,
                position=user.position,
                service_role=user.service_role,
                account_status=user.account_status,
                last_login_at=user.last_login_at,
            )
            for user, department in rows
        ]
        return Page.of(items, query.page, query.size, total)

    def create_user(self, body: UserCreateRequest, actor: User) -> UserCreateResponse:
        self.check_department(body.department_id)
        self.check_duplicates(body.employee_no, body.email)

        temporary_password = generate_temporary_password()
        try:
            user = self.users.add(User(
                **body.model_dump(),
                account_status="ACTIVE",
                password_hash=hash_password(temporary_password),
                password_changed_at=None,
            ))
            self.audit_logs.add("USER_CREATE", "user", user.id, result=user.service_role, actor_id=actor.id)
            self.db.commit()
        except IntegrityError:
            # 앞의 확인과 저장 사이에 같은 사번·이메일이 먼저 저장된 경우
            self.db.rollback()
            self.check_duplicates(body.employee_no, body.email)
            raise
        return UserCreateResponse(user=self.to_detail(user), temporary_password=temporary_password)

    def update_user(self, user_id: int, body: UserUpdateRequest, actor: User) -> UserDetail:
        user = self.users.get_for_update(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND)

        changes = {
            field: value
            for field, value in body.model_dump(include=body.model_fields_set - {"reason"}).items()
            if getattr(user, field) != value
        }
        role_changed = "service_role" in changes
        status_changed = "account_status" in changes
        if "department_id" in changes:
            self.check_department(changes["department_id"])
        if (role_changed or status_changed) and user.id == actor.id:
            raise AppError(ErrorCode.USER_SELF_CHANGE_NOT_ALLOWED)
        if (role_changed or status_changed) and body.reason is None:
            raise AppError(ErrorCode.USER_STATUS_REASON_REQUIRED, [
                {"field": "reason", "reason": "REQUIRED", "message": ErrorCode.USER_STATUS_REASON_REQUIRED.message},
            ])
        if "email" in changes:
            self.check_duplicates(None, changes["email"], exclude_user_id=user.id)
        if not changes:
            return self.to_detail(user)

        was_locked = user.account_status == "LOCKED"
        for field, value in changes.items():
            setattr(user, field, value)
        if was_locked and user.account_status == "ACTIVE":
            unlock(user)
        user.updated_at = datetime_utils.now()
        if role_changed:
            self.audit_logs.add("USER_ROLE_CHANGE", "user", user.id, result=user.service_role, actor_id=actor.id,
                                reason=body.reason)
        if status_changed:
            self.audit_logs.add("USER_STATUS_CHANGE", "user", user.id, result=user.account_status, actor_id=actor.id,
                                reason=body.reason)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            self.check_duplicates(None, changes.get("email"), exclude_user_id=user_id)
            raise
        return self.to_detail(user)

    def reset_password(self, user_id: int, reason: str | None, actor: User) -> TemporaryPasswordResponse:
        user = self.users.get_for_update(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND)

        now = datetime_utils.now()
        temporary_password = generate_temporary_password()
        user.password_hash = hash_password(temporary_password)
        user.password_changed_at = None
        user.updated_at = now
        if user.account_status == "LOCKED":
            unlock(user)
        self.sessions.revoke_all(user.id, "PASSWORD_RESET", now)
        self.audit_logs.add("PASSWORD_RESET", "user", user.id, result=user.account_status, actor_id=actor.id,
                            reason=reason)
        self.db.commit()
        return TemporaryPasswordResponse(temporary_password=temporary_password)

    def check_department(self, department_id: int | None) -> None:
        if department_id is None:
            return
        department = self.users.get_department(department_id)
        if department is None or not department.is_active:
            raise AppError(ErrorCode.VALIDATION_ERROR, [
                {"field": "departmentId", "reason": "NOT_FOUND", "message": "존재하지 않는 부서입니다."},
            ])

    def check_duplicates(self, employee_no: str | None, email: str | None, exclude_user_id: int | None = None) -> None:
        if employee_no is not None and self.users.exists_employee_no(employee_no):
            raise duplicate_error(ErrorCode.USER_EMPLOYEE_NO_DUPLICATE, "employeeNo")
        if email is not None and self.users.exists_email(email, exclude_user_id):
            raise duplicate_error(ErrorCode.USER_EMAIL_DUPLICATE, "email")

    def get_user(self, user_id: int) -> UserDetail:
        user = self.users.get(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND)
        return self.to_detail(user)

    def to_detail(self, user: User) -> UserDetail:
        return UserDetail(
            **dict(self.get_me(user)),
            failed_login_count=user.failed_login_count,
            locked_until=user.locked_until,
            password_changed_at=user.password_changed_at,
            slack_user_id=user.slack_user_id,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


UserServiceDep = Annotated[UserService, Depends(UserService)]


def unlock(user: User) -> None:
    user.account_status = "ACTIVE"
    user.failed_login_count = 0
    user.locked_until = None


def duplicate_error(code: ErrorCode, field: str) -> AppError:
    return AppError(code, [{"field": field, "reason": "DUPLICATE", "message": code.message}])
