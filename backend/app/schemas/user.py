from typing import Annotated, Literal

from pydantic import StringConstraints

from app.schemas.auth import DepartmentRef, Me
from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str

ServiceRole = Literal["EMPLOYEE", "AGENT", "ADMIN"]
AccountStatus = Literal["ACTIVE", "LOCKED", "INACTIVE"]

# 형식만 확인한다 (email-validator 의존성 없이)
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class User(Me):
    failed_login_count: int
    locked_until: KstDatetime | None
    password_changed_at: KstDatetime | None
    slack_user_id: str | None
    created_at: KstDatetime
    updated_at: KstDatetime | None


class UserSummary(CamelModel):
    id: int
    employee_no: str
    name: str
    email: str
    department: DepartmentRef | None
    position: str | None
    service_role: str
    account_status: str
    last_login_at: KstDatetime | None


class UserListQuery(PageQuery):
    sort: list[sort_param("name", "employeeNo", "createdAt", "lastLoginAt")] = ["name,asc"]
    q: trimmed_str(max_length=100) | None = None
    department_id: int | None = None
    service_role: list[ServiceRole] = []
    account_status: list[AccountStatus] = []


class UserCreateRequest(CamelModel):
    employee_no: trimmed_str(1, 20)
    name: trimmed_str(1, 50)
    email: Email
    department_id: int | None = None
    position: trimmed_str(1, 20) | None = None
    service_role: ServiceRole
    slack_user_id: trimmed_str(1) | None = None


class UserCreateResponse(CamelModel):
    user: User
    temporary_password: str


class UserUpdateRequest(CamelModel):
    """보낸 필드만 바꾼다. 서비스에서 model_fields_set 으로 구분한다.

    null 을 허용하지 않는 필드는 타입에 None 을 넣지 않고 기본값만 None 으로 둔다.
    생략하면 통과하고, null 을 보내면 422 가 된다.
    """

    name: trimmed_str(1, 50) = None
    email: Email = None
    department_id: int | None = None
    position: trimmed_str(1, 20) | None = None
    service_role: ServiceRole = None
    account_status: Literal["ACTIVE", "INACTIVE"] = None    # LOCKED 는 서버만 설정
    slack_user_id: trimmed_str(1) | None = None
    reason: trimmed_str(1, 500) = None


class TemporaryPasswordRequest(CamelModel):
    reason: trimmed_str(1, 500) | None = None


class TemporaryPasswordResponse(CamelModel):
    temporary_password: str
