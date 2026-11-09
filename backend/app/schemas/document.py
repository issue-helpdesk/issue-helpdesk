from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import CamelModel, GuideImage, KstDatetime, PageQuery, sort_param, trimmed_str
from app.schemas.inquiry import CategoryRef, GroupRef, UserRef

DocType = Literal["GUIDE", "MANUAL", "STANDARD"]
ViewScope = Literal["ALL", "AGENT", "ADMIN"]
TransferPolicy = Literal["ALLOWED", "MASKED", "BLOCKED"]
Title = trimmed_str(1, 200)


class CurrentVersion(CamelModel):
    id: int
    version: str
    file_format: str | None
    view_scope: str | None          # ADMIN 만 값을 준다
    transfer_policy: str | None     # ADMIN 만 값을 준다
    registered_at: KstDatetime


class IngestSummary(CamelModel):
    """DC-01 문서별 적재 요약. 모든 버전을 센다."""
    failed: int
    pending: int
    last_ingest_error: str | None    # 가장 최근에 올린 실패 버전의 사유


class Document(CamelModel):
    id: int
    doc_code: str
    doc_type: str
    title: str
    category_code: str | None
    category: CategoryRef | None
    owner_group_id: int | None
    owner_group: GroupRef | None
    is_active: bool
    current_version: CurrentVersion | None
    ingest_summary: IngestSummary | None = None     # DC-01 의 ADMIN 응답에만 값을 준다
    created_at: KstDatetime


class DocumentContent(CamelModel):
    """DC-12·13 가이드 본문. content 의 '[그림] 설명' 줄은 images 의 caption 과 짝지어 DC-11 로 받는다."""
    document_id: int
    version_id: int
    version: str
    content: str
    images: list[GuideImage]


class DocumentVersion(CamelModel):
    id: int
    document_id: int
    version: str
    file_format: str | None
    view_scope: str
    transfer_policy: str
    activated_at: KstDatetime | None
    is_current: bool
    version_state: Literal["CURRENT", "DRAFT", "EXPIRED"]
    ingest_status: str
    ingest_error: str | None
    chunk_count: int
    registered_by: int | None
    registered_by_user: UserRef | None
    registered_at: KstDatetime


class DocumentListQuery(PageQuery):
    sort: list[sort_param("docCode", "title", "createdAt")] = ["docCode,asc"]
    doc_type: list[DocType] = []
    category_code: list[trimmed_str(1, 20)] = []
    q: trimmed_str(max_length=100) | None = None
    is_active: bool | None = None               # ADMIN 만. 기본 true
    include_inactive: bool | None = None        # ADMIN 만. true 면 비활성 문서도 준다. isActive 를 함께 보내면 isActive 를 따른다
    has_current_version: bool | None = None     # ADMIN 만


class DocumentCreateRequest(CamelModel):
    doc_code: Annotated[str, Field(pattern=r"^IT-[A-Z]{2,4}-\d{3}(-M)?$")]
    doc_type: DocType
    title: Title
    category_code: trimmed_str(1, 20) | None = None
    owner_group_id: int | None = None


# 보낸 필드만 바꾼다. docCode·docType 은 모르는 필드라 NOT_ALLOWED 가 된다
class DocumentUpdateRequest(CamelModel):
    title: Title = None
    category_code: trimmed_str(1, 20) | None = None
    owner_group_id: int | None = None
    is_active: bool = None


# 보낸 필드만 바꾼다. 현행을 끄기만 하는 요청은 받지 않는다
class DocumentVersionUpdateRequest(CamelModel):
    is_current: Literal[True] = None
    view_scope: ViewScope = None
    transfer_policy: TransferPolicy = None
    reason: trimmed_str(max_length=500) | None = None      # 외부 전송을 넓힐 때 필수
