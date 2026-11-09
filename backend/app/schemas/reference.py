from pydantic import ConfigDict

from app.schemas.common import CamelModel
from app.schemas.inquiry import GroupRef, InquiryTypeRef, UserRef


class Category(CamelModel):
    code: str
    name: str
    description: str | None


class InquiryType(CamelModel):
    id: int
    code: str
    category_code: str
    name: str
    request_kind: str
    default_urgency: str
    default_group_id: int
    default_group: GroupRef
    is_active: bool


class SupportGroup(CamelModel):
    id: int
    name: str
    department_id: int | None
    description: str | None
    is_triage: bool
    is_active: bool


class GroupMember(CamelModel):
    user_id: int
    user: UserRef
    position: str | None
    member_role: str
    assignable: bool
    has_jira_account: bool
    jira_account_id: str | None    # ADMIN 만 값을 준다
    is_active: bool
    skills: list[InquiryTypeRef]
    open_ticket_count: int
    on_leave: bool                  # 지금 연차·반차 중. assignable 필터와 별개로 목록에는 나온다


class Department(CamelModel):
    id: int
    name: str
    parent_id: int | None
    is_active: bool


# 기준 정보 목록 Query. 모르는 파라미터는 무시한다 (PageQuery 와 같음)
class ActiveQuery(CamelModel):
    model_config = ConfigDict(extra="ignore")

    is_active: bool = True


class InquiryTypeQuery(ActiveQuery):
    category_code: list[str] = []


class GroupMemberQuery(CamelModel):
    model_config = ConfigDict(extra="ignore")

    assignable: bool | None = None
    inquiry_type_id: int | None = None
