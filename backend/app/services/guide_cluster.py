"""해결 사례 가이드화 묶음 관리 (GC, 기획_해결사례_가이드화 6단계). 묶음은 주간 분석이 만들고 여기서는 조회·검토한다.

현행 전환 때의 묶음 검사·APPLIED 연결은 DocumentService.update_version (DC-09) 이 한다.
거절·반영 표시는 묶음과 소속 티켓의 상태를 함께 바꾸고 audit_logs(target_type = guide_cluster)에 남긴다.
"""
from typing import Annotated

from fastapi import Depends

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.models import Category, DocumentVersion, GuideCluster, KnowledgeDocument, User
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.document import DocumentRepositoryDep
from app.repositories.guide_cluster import GuideClusterRepositoryDep
from app.schemas.common import Page
from app.utils import datetime_utils
from app.schemas.guide_cluster import (
    DocumentRef,
    GuideClusterDetail,
    GuideClusterListQuery,
    GuideClusterSummary,
    GuideClusterTicket,
    VersionRef,
)
from app.schemas.inquiry import CategoryRef, UserRef


class GuideClusterService:
    def __init__(
        self,
        db: DbSession,
        clusters: GuideClusterRepositoryDep,
        documents: DocumentRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
    ) -> None:
        self.db = db
        self.clusters = clusters
        self.documents = documents
        self.audit_logs = audit_logs

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
        return GuideClusterDetail(
            **dict(head),                       # 필드 값 그대로 (직렬화하지 않음)
            draft_md=c.draft_md,
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

    def lock_reviewing(self, cluster_id: int) -> GuideCluster:
        """넣을 문서 → 묶음 순으로 잠그고 검토 중인지 본다. DC-09(문서 → 버전 → 묶음)와 순서가 같아 교착되지 않는다."""
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
