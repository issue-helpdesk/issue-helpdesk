from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, PageQuery, trimmed_str
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


class GuideClusterDetail(GuideClusterSummary):
    """GC-02 상세. 등록 검사용 초안 기준(draft_basis)은 내려 주지 않는다."""
    draft_md: str | None
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


class GuideClusterRejectRequest(CamelModel):
    reason: trimmed_str(1, 500)
