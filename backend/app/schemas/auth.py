from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, KstDatetime, trimmed_str


class DepartmentRef(CamelModel):
    id: int
    name: str


class SupportGroupMembership(CamelModel):
    group_id: int
    group_name: str
    member_role: str
    assignable: bool


class Me(CamelModel):
    id: int
    employee_no: str
    name: str
    email: str
    department_id: int | None
    department: DepartmentRef | None
    position: str | None
    service_role: str
    account_status: str
    password_change_required: bool
    last_login_at: KstDatetime | None
    support_groups: list[SupportGroupMembership]


class LoginRequest(CamelModel):
    employee_no: trimmed_str(1, 20)
    password: str = Field(min_length=1, max_length=64)     # 원문 그대로 검사한다


class TokenResponse(CamelModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user: Me


class PasswordChangeRequest(CamelModel):
    current_password: str = Field(min_length=1, max_length=64)
    new_password: str      # 길이·조합은 비밀번호 규칙에서 AUTH_PASSWORD_POLICY_VIOLATION 으로 알린다
