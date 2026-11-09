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
from app.rag.case_guide.open_basis import open_basis
from app.rag.case_guide.rebase import rebase
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.document import DocumentRepositoryDep
from app.repositories.guide_analysis_run import GuideAnalysisRunRepositoryDep
from app.repositories.guide_cluster import GuideClusterRepositoryDep
from app.schemas.common import Page
from app.services.document_file import stored_file
from app.services.document_ingest import IngestSubmitterDep
from app.utils import datetime_utils
from app.schemas.guide_cluster import (
    DocumentRef,
    GuideAnalysisStatus,
    GuideClusterConflict,
    GuideClusterDetail,
    GuideClusterDetailWithWarnings,
    GuideClusterListQuery,
    GuideClusterSummary,
    GuideClusterTicket,
    VersionRef,
)
from app.schemas.inquiry import CategoryRef, UserRef

REBASABLE_JUDGMENTS = ("ADD_ITEM", "CHANGE", "SEC_MANUAL")      # 새 가이드는 기준 현행이 없다
REGISTRABLE_JUDGMENTS = (*REBASABLE_JUDGMENTS, "NEW_GUIDE")     # 매뉴얼 후보는 초안이 없다


def guide_assembler() -> Callable[..., dict]:
    return assemble


def guide_rebaser() -> Callable[..., dict]:
    return rebase


def guide_basis_opener() -> Callable[..., dict]:
    return open_basis


GuideAssemblerDep = Annotated[Callable[..., dict], Depends(guide_assembler)]
GuideBasisOpenerDep = Annotated[Callable[..., dict], Depends(guide_basis_opener)]
GuideRebaserDep = Annotated[Callable[..., dict], Depends(guide_rebaser)]


class GuideClusterService:
    def __init__(
        self,
        db: DbSession,
        clusters: GuideClusterRepositoryDep,
        documents: DocumentRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        assembler: GuideAssemblerDep,
        rebaser: GuideRebaserDep,
        basis_opener: GuideBasisOpenerDep,
        submit_ingest: IngestSubmitterDep,
        analysis_runs: GuideAnalysisRunRepositoryDep,
    ) -> None:
        self.analysis_runs = analysis_runs
        self.db = db
        self.clusters = clusters
        self.documents = documents
        self.audit_logs = audit_logs
        self.assembler = assembler
        self.rebaser = rebaser
        self.basis_opener = basis_opener
        self.submit_ingest = submit_ingest

    def list_clusters(self, query: GuideClusterListQuery) -> Page[GuideClusterSummary]:
        """GC-01."""
        rows, total = self.clusters.search(query.category_code, query.judgment, query.status, query.offset, query.size)
        items = [summary(c, cat, doc, reg, n) for c, cat, doc, reg, n in rows]
        return Page.of(items, query.page, query.size, total)

    def analysis_status(self) -> GuideAnalysisStatus:
        """GC-09."""
        succeeded, latest = self.analysis_runs.latest_succeeded(), self.analysis_runs.latest()
        return GuideAnalysisStatus(
            last_analyzed_at=succeeded.started_at if succeeded else None,
            next_analysis_at=datetime_utils.kst_next_week_start(datetime_utils.now()),
            last_run_status=latest.status if latest else None,
        )

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
            conflicts=[GuideClusterConflict(section=i["section"], kind=i["kind"], message=i["message"],
                                            old_md=i["old_md"], new_md=i["new_md"]) for i in unresolved_conflicts(c)],
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
        넣을 문서 변경은 초안 기준을 새로 잡아야 해서 GC-08 이 한다. 운영 기록은 남기지 않는다 (상태 변경이 아님).
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
    ) -> GuideClusterDetailWithWarnings:
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
        return GuideClusterDetailWithWarnings(**dict(self.get_cluster(c.id)), warnings=out["warnings"])

    def rebase(self, cluster_id: int, draft_revision: int, user: User) -> GuideClusterDetailWithWarnings:
        """GC-07. 현행이 바뀐 묶음의 초안 기준을 지금 현행으로 맞춘다.

        초안 글은 건드리지 않는다. 등록한 파일은 옛 기준이라 등록 연결을 끊고, 다음 등록(GC-06)에서 새 기준으로 조립한다.
        변경 항목이 현행에서 달라졌으면 충돌을 기록한다: 기록한 번호와 지금 draft_revision 이 같은 동안 등록이 막히고,
        관리자가 초안을 고쳐 저장(GC-05)해 번호가 오르면 풀린다.
        """
        c = self.lock_reviewing(cluster_id)
        self.check_draft_ready(c, draft_revision, REBASABLE_JUDGMENTS)
        try:
            out = self.rebaser(self.db.connection().connection.driver_connection, c.target_document_id,
                               {**self.assemble_input(c), "draft_revision": c.draft_revision})
        except CaseGuideError as e:
            self.db.rollback()
            raise AppError(ErrorCode.GUIDE_CLUSTER_REBASE_FAILED, [
                {"reason": "REBASE", "message": problem} for problem in e.problems
            ])
        old_base, basis, revision = c.base_version_id, out["draft_basis"], c.draft_revision + 1
        if out["conflicts"]:
            basis["conflicts"]["revision"] = revision
        c.draft_basis, c.base_version_id, c.draft_revision = basis, basis["base_version_id"], revision
        c.registered_version_id, c.updated_at = None, datetime_utils.now()
        self.audit_logs.add("GUIDE_CLUSTER_REBASE", "guide_cluster", c.id, actor_id=user.id,
                            result=f"{c.judgment} 기준 버전 {old_base} → {c.base_version_id}, 충돌 {len(out['conflicts'])}건")
        self.db.commit()
        return GuideClusterDetailWithWarnings(**dict(self.get_cluster(c.id)), warnings=out["warnings"])

    def change_target(
        self, cluster_id: int, document_id: int, target_section: str | None, draft_revision: int, user: User,
    ) -> GuideClusterDetailWithWarnings:
        """GC-08. 넣을 문서를 바꾸거나 새 가이드 묶음에 문서를 연결한다. 초안 글은 바꾸지 않는다.

        변경(CHANGE) 묶음을 옮기면 충돌로 기록한다: 조각은 옛 항목을 고쳐 쓴 글이라 그대로 등록하면 새 항목을 덮어쓴다.
        관리자가 새 원문을 보고 고쳐 저장(GC-05)하면 풀린다. draft_revision 을 올리므로, 넣을 문서가 바뀌는 사이
        옛 문서만 잠근 다른 요청(GC-05·06·07)은 번호 검사에서 걸린다.
        """
        c = self.lock_reviewing(cluster_id, also_document=document_id)
        document = self.documents.get(document_id)
        if document is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        self.check_target_changeable(c, document_id, target_section, draft_revision)
        revision = c.draft_revision + 1
        if c.judgment == "NEW_GUIDE":
            self.check_new_guide_document(document)
            basis, warnings = c.draft_basis, []
        else:
            basis, warnings = self.open_target_basis(c, document_id, target_section, revision)
        old_document = c.target_document_id
        c.target_document_id, c.draft_basis, c.draft_revision = document_id, basis, revision
        c.base_version_id, c.updated_at = (basis or {}).get("base_version_id"), datetime_utils.now()
        self.audit_logs.add("GUIDE_CLUSTER_TARGET_CHANGE", "guide_cluster", c.id, actor_id=user.id,
                            result=f"{c.judgment} 문서 {old_document} → {document_id}"
                                   + (f" 항목 {target_section}" if c.judgment == "CHANGE" else ""))
        self.db.commit()
        return GuideClusterDetailWithWarnings(**dict(self.get_cluster(c.id)), warnings=warnings)

    def check_target_changeable(
        self, c: GuideCluster, document_id: int, target_section: str | None, draft_revision: int,
    ) -> None:
        if c.registered_version_id is not None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_LOCKED, [
                {"reason": "REGISTERED", "message": "등록한 버전", "value": c.registered_version_id},
            ])
        if c.judgment not in REGISTRABLE_JUDGMENTS:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "JUDGMENT", "message": "묶음 판단", "value": c.judgment},
            ])
        if draft_revision != c.draft_revision:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_CONFLICT, [
                {"field": "draftRevision", "reason": "STALE", "message": "지금 초안 번호", "value": c.draft_revision},
            ])
        same_section = c.judgment != "CHANGE" or target_section == (c.draft_basis or {}).get("target_section")
        if document_id == c.target_document_id and same_section:        # 기준만 새로 잡히면 다시 맞추기의 충돌 검사를 건너뛴다
            raise AppError(ErrorCode.GUIDE_CLUSTER_TARGET_UNCHANGED)

    def check_new_guide_document(self, document: KnowledgeDocument) -> None:
        """조립 함수도 거부하지만, 초안을 다 쓴 뒤 등록에서 실패하지 않게 연결할 때 막는다."""
        problems = []
        if document.doc_type != "GUIDE":
            problems.append("임직원용 가이드만 연결할 수 있습니다")
        if self.documents.versions(document.id):
            problems.append("새 가이드는 버전이 하나도 없는 문서에만 연결할 수 있습니다")
        if problems:
            raise AppError(ErrorCode.GUIDE_CLUSTER_TARGET_INVALID, [{"reason": "TARGET", "message": p} for p in problems])

    def open_target_basis(
        self, c: GuideCluster, document_id: int, target_section: str | None, revision: int,
    ) -> tuple[dict, list[str]]:
        old_md = (c.draft_basis or {}).get("target_md") or ""
        try:
            out = self.basis_opener(self.db.connection().connection.driver_connection, c.judgment,
                                    document_id=document_id, target_section=target_section,
                                    receipts_=self.assemble_input(c)["receipts"])
        except CaseGuideError as e:
            self.db.rollback()
            raise AppError(ErrorCode.GUIDE_CLUSTER_TARGET_INVALID, [
                {"reason": "TARGET", "message": problem} for problem in e.problems
            ])
        basis = out["draft_basis"]
        if c.judgment == "CHANGE":
            basis["conflicts"] = {"revision": revision, "items": [{
                "section": target_section, "kind": "TARGET_MOVED", "old_md": old_md, "new_md": basis["target_md"],
                "message": f"넣을 위치가 {target_section}(으)로 바뀌었습니다. 새 항목과 비교해 초안을 고쳐 저장해 주세요",
            }]}
        return basis, out["warnings"]

    def check_registrable(self, c: GuideCluster, draft_revision: int) -> None:
        self.check_draft_ready(c, draft_revision, REGISTRABLE_JUDGMENTS)
        if c.target_document_id is None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "NO_TARGET", "message": "넣을 문서를 먼저 연결해 주세요"},
            ])
        if c.judgment == "NEW_GUIDE":                   # 기준 버전이 없다. 그사이 현행이 생겼으면 조립 함수가 거부한다
            return
        current = self.documents.current_version(c.target_document_id)
        if current is None or c.base_version_id != current.id:
            raise AppError(ErrorCode.GUIDE_CLUSTER_BASE_CHANGED, [
                {"reason": "BASE_VERSION_CHANGED", "message": "지금 현행 버전", "value": current.id if current else None},
            ])
        if conflicts := unresolved_conflicts(c):
            raise AppError(ErrorCode.GUIDE_CLUSTER_CONFLICT_UNRESOLVED, [
                {"reason": "CONFLICT", "message": i["message"], "value": i["section"]} for i in conflicts
            ])

    def check_draft_ready(self, c: GuideCluster, draft_revision: int, judgments: tuple[str, ...]) -> None:
        if c.judgment not in judgments:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "JUDGMENT", "message": "묶음 판단", "value": c.judgment},
            ])
        if not (c.draft_md and c.draft_basis):
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REGISTRABLE, [
                {"reason": "NO_DRAFT", "message": "초안이 아직 만들어지지 않았습니다"},
            ])
        if draft_revision != c.draft_revision:
            raise AppError(ErrorCode.GUIDE_CLUSTER_DRAFT_CONFLICT, [
                {"field": "draftRevision", "reason": "STALE", "message": "지금 초안 번호", "value": c.draft_revision},
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

    def lock_reviewing(self, cluster_id: int, also_document: int | None = None) -> GuideCluster:
        """넣을 문서 → 묶음 순으로 잠그고 검토 중인지 본다. DC-09(문서 → 버전 → 묶음)와 순서가 같아 교착되지 않는다.
        묶음 행을 잠그므로 같은 묶음에 대한 저장·거절·반영 표시가 한 번에 하나씩 된다."""
        c = self.clusters.get(cluster_id)
        if c is None:
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_FOUND)
        for document_id in sorted({c.target_document_id, also_document} - {None}):     # 문서 둘을 잠그는 요청끼리 교착되지 않게
            self.documents.get_for_update(document_id)
        c = self.clusters.get_for_update(cluster_id)
        if c.status != "REVIEWING":
            raise AppError(ErrorCode.GUIDE_CLUSTER_NOT_REVIEWING, [
                {"reason": "STATUS", "message": "묶음 상태", "value": c.status},
            ])
        return c

    def review(self, c: GuideCluster, status: str, user: User) -> None:
        self.clusters.change_status([c], status)
        c.reviewed_by, c.reviewed_at = user.id, datetime_utils.now()


def unresolved_conflicts(c: GuideCluster) -> list[dict]:
    """아직 풀리지 않은 충돌. 기록한 번호가 지금 draft_revision 과 같으면 관리자가 초안을 고쳐 저장하지 않은 것이다."""
    conflicts = (c.draft_basis or {}).get("conflicts") or {}
    return conflicts.get("items") or [] if conflicts.get("revision") == c.draft_revision else []


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
