from typing import Annotated

from pydantic import Field

from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str
from app.schemas.inquiry import CategoryRef, UserRef

Keywords = Annotated[list[trimmed_str(1, 30)], Field(max_length=20)]


class Faq(CamelModel):
    id: int
    faq_code: str
    category_code: str
    category: CategoryRef
    question: str
    answer: str
    keywords: list[str]
    is_active: bool
    updated_by: UserRef | None              # ADMIN 만 값을 준다
    created_at: KstDatetime
    updated_at: KstDatetime | None


class FaqSource(CamelModel):
    document_id: int
    doc_code: str
    title: str
    version: str
    location: str | None


class FaqDetail(Faq):
    sources: list[FaqSource]


class FaqListQuery(PageQuery):
    sort: list[sort_param("faqCode", "updatedAt")] = ["faqCode,asc"]
    category_code: list[trimmed_str(1, 20)] = []
    q: trimmed_str(max_length=100) | None = None
    is_active: bool | None = None           # ADMIN 만


class FaqCreateRequest(CamelModel):
    faq_code: Annotated[str, Field(pattern=r"^FAQ-\d{3,}$")] | None = None    # 없으면 다음 번호
    category_code: trimmed_str(1, 20)
    question: trimmed_str(1, 500)
    answer: trimmed_str(1, 4000)
    keywords: Keywords = []
    is_active: bool = True


# 보낸 필드만 바꾼다. faqCode 는 모르는 필드라 NOT_ALLOWED 가 된다
class FaqUpdateRequest(CamelModel):
    category_code: trimmed_str(1, 20) = None
    question: trimmed_str(1, 500) = None
    answer: trimmed_str(1, 4000) = None
    keywords: Keywords = None
    is_active: bool = None
