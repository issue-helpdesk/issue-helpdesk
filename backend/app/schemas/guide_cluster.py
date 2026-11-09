from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, KstDatetime, PageQuery, trimmed_str
from app.schemas.document import TransferPolicy, ViewScope
from app.schemas.inquiry import CategoryRef, UserRef

Judgment = Literal["ADD_ITEM", "CHANGE", "NEW_GUIDE", "MANUAL_CANDIDATE", "SEC_MANUAL"]
ClusterStatus = Literal["REVIEWING", "APPLIED", "REJECTED"]


class GuideClusterListQuery(PageQuery):
    category_code: list[trimmed_str(1, 20)] = []
    judgment: list[Judgment] = []
    status: list[ClusterStatus] = []            # 없으면 전체


class DocumentRef(CamelModel):
    id: int
    doc_code: str
    title: str


class VersionRef(CamelModel):
    id: int
    version: str
    is_current: bool
    ingest_status: str                          # 등록한 버전의 검색 준비 상태 (PENDING·DONE·FAILED)


class GuideClusterSummary(CamelModel):
    """GC-01 목록 한 줄."""
    id: int
    category: CategoryRef
    judgment: str
    status: str
    title: str
    ticket_count: int
    target_document: DocumentRef | None         # 새 가이드는 문서 등록 전까지 없다
    registered_version: VersionRef | None       # 등록 전이면 없다
    created_at: KstDatetime                     # 분석일
    updated_at: KstDatetime | None


class GuideClusterTicket(CamelModel):
    """근거 티켓. 관리자가 해결 방법이 맞는지 확인하는 데 쓴다."""
    ticket_id: int
    receipt_no: str
    summary: str
    symptom: str | None
    target_system: str | None
    resolution_note: str | None
    closed_at: KstDatetime | None


class GuideClusterConflict(CamelModel):
    """다시 맞추기에서 나온 충돌. 관리자가 새 원문과 비교해 초안을 고쳐 저장하면 풀린다."""
    section: str
    kind: str
    message: str
    old_md: str                                 # 초안을 만들 때의 원문
    new_md: str                                 # 지금 현행의 원문


class GuideClusterDetail(GuideClusterSummary):
    """GC-02 상세. 등록 검사용 초안 기준(draft_basis)은 변경할 항목의 위치·원문만 내려 준다."""
    draft_md: str | None
    target_section: str | None                  # 변경(CHANGE)할 항목 번호. 다른 판단은 없다
    target_md: str | None                       # 변경할 항목의 초안 기준 원문. 화면의 "기존 내용"
    conflicts: list[GuideClusterConflict]       # 아직 풀리지 않은 충돌. 있으면 등록이 막힌다
    draft_revision: int                         # 초안 수정 저장 때 함께 보낸다 (다른 관리자 변경 확인)
    review_info: dict
    compared_items: list
    base_version: VersionRef | None             # 초안을 만든 기준 버전
    current_version: VersionRef | None          # 넣을 문서의 지금 현행
    base_changed: bool                          # 검토 중인데 기준 버전이 현행과 다름. 등록·현행 전환이 막힌다
    reject_reason: str | None
    reviewed_by: UserRef | None
    reviewed_at: KstDatetime | None
    tickets: list[GuideClusterTicket]


MD_MAX_LENGTH = 1_000_000                       # 가이드 md 는 수십 KB 다. 비정상적으로 큰 본문만 막는다


class GuideClusterDraftUpdateRequest(CamelModel):
    draft_md: str = Field(min_length=1, max_length=MD_MAX_LENGTH)
    draft_revision: int = Field(ge=0)           # GC-02 에서 받은 값. 다르면 다른 관리자가 먼저 고친 것


class GuideClusterRejectRequest(CamelModel):
    reason: trimmed_str(1, 500)


class GuideClusterRegisterRequest(CamelModel):
    draft_revision: int = Field(ge=0)           # GC-02 에서 받은 값. 다르면 관리자가 본 초안과 등록할 초안이 다르다
    view_scope: ViewScope                       # 이어 쓰는 버전이면 버전 전체에 적용된다
    transfer_policy: TransferPolicy             # 서버가 대신 채우지 않는다


class GuideClusterRebaseRequest(CamelModel):
    draft_revision: int = Field(ge=0)           # GC-02 에서 받은 값. 성공하면 1 오르므로 응답 값을 이어서 쓴다


class GuideClusterDetailWithWarnings(GuideClusterDetail):
    """GC-06·07. 상세 + 경고 (개인정보로 보이는 글 등). 저장하지 않으므로 이 응답에서만 볼 수 있다."""
    warnings: list[str]
