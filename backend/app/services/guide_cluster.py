"""해결 사례 가이드화 묶음 관리 (GC, 기획_해결사례_가이드화 6단계). 묶음은 주간 분석이 만들고 여기서는 조회·검토한다.

현행 전환 때의 묶음 검사·APPLIED 연결은 DocumentService.update_version (DC-09) 이 한다.
문서 조립은 app.rag.case_guide.assemble 이 하고, 어떤 묶음을 어느 버전에 넣을지는 여기서 정한다 (GC-06).
거절·반영 표시는 묶음과 소속 티켓의 상태를 함께 바꾸고 audit_logs(target_type = guide_cluster)에 남긴다.
"""
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.models import Category, DocumentVersion, GuideCluster, KnowledgeDocument, User
from app.rag.case_guide import CaseGuideError
from app.rag.case_guide.assemble import assemble
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.document import DocumentRepositoryDep
from app.repositories.guide_cluster import GuideClusterRepositoryDep
from app.schemas.common import Page
from app.services.document_file import stored_file
from app.services.document_ingest import IngestSubmitterDep
from app.utils import datetime_utils
from app.schemas.guide_cluster import (
    DocumentRef,
    GuideClusterDetail,
    GuideClusterListQuery,
    GuideClusterRegisterResponse,
    GuideClusterSummary,
    GuideClusterTicket,
    VersionRef,
)
from app.schemas.inquiry import CategoryRef, UserRef

REGISTRABLE_JUDGMENTS = ("ADD_ITEM", "CHANGE", "SEC_MANUAL")     # 새 가이드는 조립 함수가 아직 지원하지 않는다


def guide_assembler() -> Callable[..., dict]:
    return assemble


GuideAssemblerDep = Annotated[Callable[..., dict], Depends(guide_assembler)]


class GuideClusterService:
    def __init__(
        self,
        db: DbSession,
        clusters: GuideClusterRepositoryDep,
        documents: DocumentRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        assembler: GuideAssemblerDep,
        submit_ingest: IngestSubmitterDep,
    ) -> None:
        self.db = db
        self.clusters = clusters
        self.documents = documents
        self.audit_logs = audit_logs
        self.assembler = assembler
        self.submit_ingest = submit_ingest

    def list_clusters(self, query: GuideClusterListQuery) -> Page[GuideClusterSummary]:
        """GC-01."""
        rows, total = self.clusters.search(query.category_code, query.judgment, query.status, query.offset, query.size)
        items = [summary(c, cat, doc, reg, n) for c, cat, doc, reg, n in rows]
        return Page.of(items, query.page, query.size, total)

    def get_cluster(self, cluster_id: int) -> GuideClusterDetail:
        """GC-02."""
        c = self.clusters.get(cluster_id)
        if c is None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_FOUND)
        tickets = self.clusters.tickets(c.id)
        document = self.documents.get(c.target_document_id) if c.target_document_id else None
        current = self.documents.current_version(c.target_document_id) if c.target_document_id else None
        base = self.db.get(DocumentVersion, c.base_version_id) if c.base_version_id else None
        registered = self.db.get(DocumentVersion, c.registered_version_id) if c.registered_version_id else None
        reviewer = self.db.get(User, c.reviewed_by) if c.reviewed_by else None
        head = summary(c, self.db.get(Category, c.category_code), document, registered, len(tickets))
        basis = c.draft_basis or {}
        return GuideClusterDetail(
            **dict(head),                       # 필드 값 그대로 (직렬화하지 않음)
            draft_md=c.draft_md,
            target_section=basis.get("target_section"),
            target_md=basis.get("target_md"),
            draft_revision=c.draft_revision,
            review_info=c.review_info,
            compared_items=c.compared_items,
            base_version=version_ref(base),
            current_version=version_ref(current),
            base_changed=(c.status == "REVIEWING" and c.base_version_id is not None
                          and c.base_version_id != (current.id if current else None)),
            reject_reason=c.reject_reason,
            reviewed_by=UserRef(id=reviewer.id, employee_no=reviewer.employee_no, name=reviewer.name) if reviewer else None,
            reviewed_at=c.reviewed_at,
            tickets=[GuideClusterTicket(ticket_id=t.id, receipt_no=t.receipt_no, summary=t.summary, symptom=t.symptom,
                                        target_system=t.target_system, resolution_note=t.resolution_note,
                                        closed_at=t.closed_at) for t in tickets],
        )


    def save_draft(self, cluster_id: int, draft_md: str, draft_revision: int) -> GuideClusterDetail:
        """GC-05. 초안 글 저장. 보낸 draft_revision 이 지금 값과 같을 때만 저장하고 1 올린다 (다른 관리자 변경 확인).

        검토 중이고 등록하지 않은 묶음만 된다: 등록한 뒤 고치면 등록한 파일과 초안이 달라진다.
        넣을 문서 변경은 초안을 다시 만들어야 해서 여기서 하지 않는다. 운영 기록은 남기지 않는다 (상태 변경이 아님).
        """
        c = self.lock_reviewing(cluster_id)
        if c.registered_version_id is not None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_LOCKED, [
                {"reason": "REGISTERED", "message": "등록한 버전", "value": c.registered_version_id},
            ])
        if c.judgment == "MANUAL_CANDIDATE":
            raise AppError(ErrorCode.GUIDE_CLUSTER_NO_DRAFT)
        if draft_revision != c.draft_revision:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_CONFLICT, [
                {"field": "draftRevision", "reason": "STALE", "message": "지금 초안 번호", "value": c.draft_revision},
            ])
        c.draft_md, c.draft_revision, c.updated_at = draft_md, c.draft_revision + 1, datetime_utils.now()
        self.db.commit()
        return self.get_cluster(c.id)

    def reject(self, cluster_id: int, reason: str, user: User) -> GuideClusterDetail:
        """GC-03. 검토 중인 묶음을 거절한다. 등록한 뒤라도 현행 전환 전이면 된다.

        등록 버전(registered_version_id)은 지우지 않는다: 그 버전의 현행 전환을 DC-09 가 막는다.
        거절한 항목을 빼고 다시 등록하면 그때 비운다.
        """
        c = self.lock_reviewing(cluster_id)
        c.reject_reason = reason            # 상태보다 먼저: 거절은 사유가 있어야 한다 (DB CHECK)
        self.review(c, "REJECTED", user)
        self.audit_logs.add("GUIDE_CLUSTER_REJECT", "guide_cluster", c.id, actor_id=user.id,
                            result=f"{c.judgment} REVIEWING → REJECTED", reason=reason)
        self.db.commit()
        return self.get_cluster(c.id)

    def mark_applied(self, cluster_id: int, user: User) -> GuideClusterDetail:
        """GC-04. 관리자가 직접 반영한 묶음을 반영 표시한다 (주로 매뉴얼 후보, 일반 업로드로 반영한 경우).

        등록한 묶음은 현행 전환(DC-09)으로만 반영한다. 여기서 표시하면 거절·기준 버전 검사를 거치지 않기 때문이다.
        """
        c = self.lock_reviewing(cluster_id)
        if c.registered_version_id is not None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_REGISTERED, [
                {"reason": "REGISTERED", "message": "등록한 버전", "value": c.registered_version_id},
            ])
        self.review(c, "APPLIED", user)
        self.audit_logs.add("GUIDE_CLUSTER_APPLY", "guide_cluster", c.id, actor_id=user.id,
                            result=f"{c.judgment} REVIEWING → APPLIED")
        self.db.commit()
        return self.get_cluster(c.id)

    def register(
        self, cluster_id: int, draft_revision: int, view_scope: str, transfer_policy: str, user: User,
    ) -> GuideClusterRegisterResponse:
        """GC-06. 묶음을 현행이 아닌 가이드 버전으로 등록한다. 상태는 검토 중 그대로이고 현행 전환(DC-09)에서 APPLIED 가 된다.

        같은 문서에 이어 쓸 대기 버전이 있으면 [그 버전 묶음(거절 제외) + 이번 묶음] 으로 현행부터 다시 조립한다.
        조립 함수는 commit 하지 않으므로 세션의 연결을 넘겨 버전 행과 묶음 연결을 한 트랜잭션으로 저장한다.
        문서 행 잠금이 같은 문서의 등록·거절·현행 전환·적재 기록을 한 번에 하나씩 지나게 한다.
        """
        c = self.lock_reviewing(cluster_id)
        self.check_registrable(c, draft_revision)
        version_id, linked = self.registration_target(c)
        rejected = [x for x in linked if x.status == "REJECTED"]
        included = sorted({x.id: x for x in [*linked, c] if x.status != "REJECTED"}.values(), key=lambda x: x.id)
        try:
            out = self.assembler(
                self.db.connection().connection.driver_connection, c.target_document_id,
                [self.assemble_input(x) for x in included], version_id,
                view_scope=view_scope, transfer_policy=transfer_policy, actor_id=user.id,
            )
        except CaseGuideError as e:
            self.db.rollback()                  # 조립 함수가 잡은 문서 잠금도 함께 푼다
            raise AppError(ErrorCode.GUIDE_CLUSTER_ASSEMBLE_FAILED, [
                {"reason": "ASSEMBLE", "message": problem} for problem in e.problems
            ])
        try:
            self.link_version(included, rejected, out)
            self.audit_logs.add("GUIDE_CLUSTER_REGISTER", "guide_cluster", c.id, actor_id=user.id,
                                result=f"{c.judgment} → {out['version']}")
            self.db.commit()
        except Exception:
            self.db.rollback()
            stored_file(out["file_path"]).unlink(missing_ok=True)   # 행이 없는 파일이 남지 않게 한다
            raise
        self.submit_ingest(out["version_id"])
        return GuideClusterRegisterResponse(**dict(self.get_cluster(c.id)), warnings=out["warnings"])

    def check_registrable(self, c: GuideCluster, draft_revision: int) -> None:
        if c.judgment not in REGISTRABLE_JUDGMENTS:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "JUDGMENT", "message": "묶음 판단", "value": c.judgment},
            ])
        if not (c.draft_md and c.draft_basis and c.target_document_id):
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "NO_DRAFT", "message": "초안이 아직 만들어지지 않았습니다"},
            ])
        if draft_revision != c.draft_revision:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_CONFLICT, [
                {"field": "draftRevision", "reason": "STALE", "message": "지금 초안 번호", "value": c.draft_revision},
            ])
        current = self.documents.current_version(c.target_document_id)
        if current is None or c.base_version_id != current.id:
            raise AppError(ErrorCode.GUIDE_CLUSTER_BASE_CHANGED, [
                {"reason": "BASE_VERSION_CHANGED", "message": "지금 현행 버전", "value": current.id if current else None},
            ])

    def registration_target(self, c: GuideCluster) -> tuple[int | None, list[GuideCluster]]:
        """(이어 쓸 버전 id, 그 버전의 묶음). 이어 쓸 버전이 없으면 (None, []) 이고 조립 함수가 다음 번호로 새 버전을 만든다."""
        if c.registered_version_id is not None:
            linked = self.clusters.registered_to(c.registered_version_id)
            if not any(x.status == "REJECTED" for x in linked):
                raise AppError(ErrorCode.GUIDE_CLUSTER_REGISTERED, [
                    {"reason": "REGISTERED", "message": "등록한 버전", "value": c.registered_version_id},
                ])
            return c.registered_version_id, linked
        for version in self.clusters.pending_versions(c.target_document_id):
            linked = self.clusters.registered_to(version.id)
            if all(x.base_version_id == c.base_version_id for x in linked):     # 기준이 지난 버전에 이어 쓰면 조립이 거부된다
                return version.id, linked
        return None, []

    def assemble_input(self, c: GuideCluster) -> dict:
        return {"id": c.id, "judgment": c.judgment, "draft_md": c.draft_md, "draft_basis": c.draft_basis,
                "receipts": [t.receipt_no for t in self.clusters.tickets(c.id)]}

    def link_version(self, included: list[GuideCluster], rejected: list[GuideCluster], out: dict) -> None:
        """거절한 묶음은 조립에서 빠졌으니 연결을 비운다. 항목 번호는 같은 버전을 다시 조립할 때 유지하려고 저장한다."""
        now = datetime_utils.now()
        for x in rejected:
            x.registered_version_id, x.updated_at = None, now
        for x in included:
            x.registered_version_id, x.updated_at = out["version_id"], now
            if section_no := out["sections"].get(x.id):
                x.draft_basis = {**x.draft_basis, "section_no": section_no}     # JSONB 는 새 값을 넣어야 저장된다

    def lock_reviewing(self, cluster_id: int) -> GuideCluster:
        """넣을 문서 → 묶음 순으로 잠그고 검토 중인지 본다. DC-09(문서 → 버전 → 묶음)와 순서가 같아 교착되지 않는다.
        묶음 행을 잠그므로 같은 묶음에 대한 저장·거절·반영 표시가 한 번에 하나씩 된다."""
        c = self.clusters.get(cluster_id)
        if c is None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_FOUND)
        if c.target_document_id is not None:
            self.documents.get_for_update(c.target_document_id)
        c = self.clusters.get_for_update(cluster_id)
        if c.status != "REVIEWING":
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REVIEWING, [
                {"reason": "STATUS", "message": "묶음 상태", "value": c.status},
            ])
        return c

    def review(self, c: GuideCluster, status: str, user: User) -> None:
        self.clusters.change_status([c], status)
        c.reviewed_by, c.reviewed_at = user.id, datetime_utils.now()


def summary(c: GuideCluster, category: Category, document: KnowledgeDocument | None,
            registered: DocumentVersion | None, ticket_count: int) -> GuideClusterSummary:
    return GuideClusterSummary(
        id=c.id,
        category=CategoryRef(code=category.code, name=category.name),
        judgment=c.judgment,
        status=c.status,
        title=c.title,
        ticket_count=ticket_count,
        target_document=DocumentRef(id=document.id, doc_code=document.doc_code, title=document.title) if document else None,
        registered_version=version_ref(registered),
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def version_ref(row: DocumentVersion | None) -> VersionRef | None:
    if row is None:
        return None
    return VersionRef(id=row.id, version=row.version, is_current=row.is_current, ingest_status=row.ingest_status)


GuideClusterServiceDep = Annotated[GuideClusterService, Depends(GuideClusterService)]
