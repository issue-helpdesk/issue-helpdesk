"""가이드 문서 관리 (DC-01~09). 열람 범위는 현행 버전의 view_scope 로 정한다 (API 04 1장).

파일을 읽어 청크·임베딩으로 만드는 일은 app.rag.ingest.upload 가 하고, 여기서는 저장과 등록까지만 한다.
"""
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.constants import file as file_constants
from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.core.permissions import visible_scopes
from app.db.session import DbSession
from app.models import Category, DocumentVersion, GuideCluster, KnowledgeDocument, SupportGroup, User
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.document import DocumentRepositoryDep
from app.repositories.faq import FaqRepositoryDep
from app.repositories.guide_cluster import GuideClusterRepositoryDep
from app.schemas.common import ItemList, Page, parse_sort
from app.schemas.document import (
    CurrentVersion,
    Document,
    DocumentCreateRequest,
    DocumentListQuery,
    DocumentUpdateRequest,
    DocumentVersion as DocumentVersionView,
    DocumentVersionUpdateRequest,
)
from app.schemas.inquiry import CategoryRef, GroupRef, UserRef
from app.services.document_file import remove_stored, stage_file, to_stored_path
from app.services.document_ingest import IngestSubmitterDep
from app.services.faq import publishable_codes
from app.utils import datetime_utils

TRANSFER_RANK = {"BLOCKED": 0, "MASKED": 1, "ALLOWED": 2}     # 클수록 외부 모델에 넓게 전달된다


class DocumentService:
    def __init__(
        self,
        db: DbSession,
        documents: DocumentRepositoryDep,
        faqs: FaqRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        submit_ingest: IngestSubmitterDep,
        guide_clusters: GuideClusterRepositoryDep,
    ) -> None:
        self.db = db
        self.documents = documents
        self.faqs = faqs
        self.audit_logs = audit_logs
        self.submit_ingest = submit_ingest
        self.guide_clusters = guide_clusters

    def list_documents(self, query: DocumentListQuery, viewer: User) -> Page[Document]:
        """DC-01. ADMIN 이 아니면 활성이고 현행 버전이 열람 범위 안인 문서만."""
        is_admin = viewer.service_role == "ADMIN"
        if not is_admin and (query.is_active is not None or query.include_inactive is not None
                             or query.has_current_version is not None):
            raise AppError(ErrorCode.FORBIDDEN)
        is_active = query.is_active
        if is_active is None and not query.include_inactive:
            is_active = True
        rows, total = self.documents.search(
            doc_types=query.doc_type,
            category_codes=query.category_code,
            q=query.q or None,
            is_active=is_active if is_admin else True,
            has_current=query.has_current_version,
            scopes=None if is_admin else visible_scopes(viewer.service_role),
            sort=parse_sort(query.sort),
            offset=query.offset,
            limit=query.size,
        )
        items = [to_document(d, v, c, g, is_admin) for d, v, c, g in rows]
        return Page.of(items, query.page, query.size, total)

    def create(self, body: DocumentCreateRequest) -> Document:
        """DC-02. 메타정보만 만든다. 파일은 DC-07 로 올린다."""
        self.check_category(body.doc_type, body.category_code)
        self.check_group(body.owner_group_id)
        try:
            document = self.documents.add(KnowledgeDocument(
                doc_code=body.doc_code, doc_type=body.doc_type, title=body.title, category_code=body.category_code,
                owner_group_id=body.owner_group_id,
            ))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise field_error(ErrorCode.DOCUMENT_CODE_DUPLICATE, "docCode", "DUPLICATE")
        return self.view(document, is_admin=True)

    def get_document(self, document_id: int, viewer: User) -> Document:
        """DC-03. 범위 밖은 제목·번호도 드러내지 않게 없는 것처럼 404."""
        is_admin = viewer.service_role == "ADMIN"
        document = self.documents.get(document_id)
        if document is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        current = self.documents.current_version(document.id)
        if not is_admin and (not document.is_active or current is None
                             or current.view_scope not in visible_scopes(viewer.service_role)):
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        return self.view(document, is_admin)

    def update(self, document_id: int, body: DocumentUpdateRequest, user: User) -> Document:
        """DC-04. 보낸 필드만 바꾼다. 활성·비활성 전환도 여기서 한다."""
        document = self.lock_document(document_id)
        sent = body.model_fields_set
        if "category_code" in sent:
            self.check_category(document.doc_type, body.category_code)
        if "owner_group_id" in sent:
            self.check_group(body.owner_group_id)
        for name in sent - {"is_active"}:
            setattr(document, name, getattr(body, name))
        if "is_active" in sent and body.is_active is not None and body.is_active != document.is_active:
            if body.is_active:
                document.is_active = True
                self.audit_logs.add("DOCUMENT_ACTIVATE", "document", document.id, result=document.doc_code, actor_id=user.id)
            else:
                self.deactivate(document, user)
        self.db.commit()
        return self.view(document, is_admin=True)

    def deactivate(self, document: KnowledgeDocument, user: User) -> None:
        """행은 지우지 않고 검색·답변 대상에서 뺀다."""
        document.is_active = False
        self.audit_logs.add("DOCUMENT_DEACTIVATE", "document", document.id, result=document.doc_code, actor_id=user.id)
        self.recheck_faqs(document.id, user)

    def list_versions(self, document_id: int) -> ItemList[DocumentVersionView]:
        """DC-06."""
        if self.documents.get(document_id) is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        return ItemList(items=self.version_views(self.documents.versions(document_id)))

    def upload_version(
        self, document_id: int, file: BinaryIO, filename: str | None, version: str, view_scope: str,
        transfer_policy: str, user: User,
    ) -> DocumentVersionView:
        """DC-07. 내용 확인·중복 검사 → 파일 저장 → 버전 행(PENDING) 커밋 → 백그라운드 적재. 현행 전환은 자동으로 하지 않는다."""
        if self.documents.get(document_id) is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        suffix, file_format = file_format_of(filename)
        staged = stage_file(file, document_id, suffix)
        path = None
        try:
            self.check_duplicate(staged.sha256)
            path = staged.keep()
            row = self.documents.add(DocumentVersion(
                document_id=document_id, version=version, file_path=to_stored_path(path), file_format=file_format,
                file_sha256=staged.sha256, view_scope=view_scope, transfer_policy=transfer_policy,
                is_current=False, ingest_status="PENDING", registered_by=user.id,
            ))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            path.unlink(missing_ok=True)
            self.check_duplicate(staged.sha256)         # 같은 파일이 동시에 올라왔다
            raise field_error(ErrorCode.DOCUMENT_VERSION_DUPLICATE, "version", "DUPLICATE")
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)            # 행이 없는 파일이 남지 않게 한다
            raise
        finally:
            staged.discard()
        self.submit_ingest(row.id)
        return self.version_views([row])[0]

    def retry_version(
        self, document_id: int, version_id: int, file: BinaryIO | None, filename: str | None, user: User,
    ) -> DocumentVersionView:
        """DC-10. FAILED 버전을 다시 적재한다. 파일을 함께 보내면 교체하고, 안 보내면 같은 파일로 다시 시도한다."""
        self.check_retryable(self.find_version(document_id, version_id))
        staged = None
        if file is not None:
            suffix, file_format = file_format_of(filename)
            staged = stage_file(file, document_id, suffix)
        path, old_path = None, None
        try:
            self.lock_document(document_id)
            row = self.documents.version(document_id, version_id, for_update=True)
            self.check_retryable(row)
            if staged is not None and staged.sha256 != row.file_sha256:     # 같은 내용이면 교체할 것이 없다
                self.check_duplicate(staged.sha256)
                path = staged.keep()
                old_path = row.file_path
                row.file_path, row.file_format, row.file_sha256 = to_stored_path(path), file_format, staged.sha256
            row.ingest_status, row.ingest_error = "PENDING", None
            self.audit_logs.add("DOCUMENT_VERSION_RETRY", "document", document_id, actor_id=user.id,
                                result=f"{row.version} {'파일 교체' if path else '같은 파일'}")
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            path.unlink(missing_ok=True)
            self.check_duplicate(staged.sha256)
            raise
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
        finally:
            if staged is not None:
                staged.discard()
        remove_stored(old_path)                         # 커밋 뒤에 지운다. 지우지 못해도 다음 시작 때 로그로 보인다
        self.submit_ingest(row.id)
        return self.version_views([row])[0]

    def check_retryable(self, row: DocumentVersion) -> None:
        if row.ingest_status != "FAILED":
            raise AppError(ErrorCode.DOCUMENT_VERSION_NOT_RETRYABLE, [
                {"reason": "INGEST_STATUS", "message": "적재 상태", "value": row.ingest_status},
            ])

    def check_duplicate(self, sha256: str) -> None:
        found = self.documents.by_file_hash(sha256)
        if found is not None:
            version, document = found
            raise AppError(ErrorCode.DOCUMENT_FILE_DUPLICATE, [
                {"field": "file", "reason": "DUPLICATE", "message": ErrorCode.DOCUMENT_FILE_DUPLICATE.message,
                 "value": {"documentId": document.id, "docCode": document.doc_code, "versionId": version.id,
                           "version": version.version, "ingestStatus": version.ingest_status}},
            ])

    def find_version(self, document_id: int, version_id: int) -> DocumentVersion:
        if self.documents.get(document_id) is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        row = self.documents.version(document_id, version_id)
        if row is None:
            raise AppError(ErrorCode.DOCUMENT_VERSION_NOT_FOUND)
        return row

    def get_version(self, document_id: int, version_id: int) -> DocumentVersionView:
        """DC-08."""
        return self.version_views([self.find_version(document_id, version_id)])[0]

    def update_version(
        self, document_id: int, version_id: int, body: DocumentVersionUpdateRequest, user: User,
    ) -> DocumentVersionView:
        """DC-09. 현행 전환·정책 변경. 열람 범위나 현행이 바뀌면 관련 FAQ 를 같은 트랜잭션에서 다시 본다."""
        self.lock_document(document_id)
        row = self.documents.version(document_id, version_id, for_update=True)
        if row is None:
            raise AppError(ErrorCode.DOCUMENT_VERSION_NOT_FOUND)
        sent = body.model_fields_set
        if body.is_current is None and "is_current" in sent:
            raise field_error(ErrorCode.VALIDATION_ERROR, "isCurrent", "INVALID_VALUE")
        activating = body.is_current is True and not row.is_current
        if activating and row.ingest_status != "DONE":
            raise AppError(ErrorCode.DOCUMENT_VERSION_NOT_READY, [
                {"reason": "INGEST_STATUS", "message": "적재 상태", "value": row.ingest_status},
            ])
        clusters = self.check_guide_clusters(row) if activating else []

        scope_changed = self.change_policy(row, body, user)
        if activating:
            self.activate(row, user)
            self.guide_clusters.mark_applied([c for c in clusters if c.status == "REVIEWING"])
        if activating or (scope_changed and row.is_current):
            self.recheck_faqs(document_id, user)
        self.db.commit()
        return self.version_views([row])[0]

    def check_guide_clusters(self, row: DocumentVersion) -> list[GuideCluster]:
        """해결 사례 묶음을 등록한 버전이면 전환 전에 본다 (기획_해결사례_가이드화 6단계). 일반 업로드 버전은 묶음이 없다.

        거절한 묶음이 있거나, 묶음을 만든 기준 버전이 지금 현행과 다르면 막는다. 현행 전환은 가이드 전체를 바꾸므로
        그사이 현행에 들어간 수정이 사라지지 않게 한다. 기준 버전은 검토 중인 묶음만 본다: 이미 반영된 버전으로
        되돌리는 것은 관리자의 되돌리기라 막지 않는다. 새 가이드 묶음은 기준 버전이 없어 건너뛴다.
        잠금 순서는 문서 → 버전 → 묶음이다. 묶음을 거절·수정하는 쪽도 같은 순서로 잠근다.
        """
        clusters = self.guide_clusters.registered_to(row.id)
        if rejected := [c.id for c in clusters if c.status == "REJECTED"]:
            raise AppError(ErrorCode.DOCUMENT_VERSION_HAS_REJECTED_CLUSTER, [
                {"reason": "REJECTED_CLUSTER", "message": "거절한 묶음", "value": rejected},
            ])
        current = self.documents.current_version(row.document_id)
        current_id = current.id if current else None
        if stale := [c.id for c in clusters if c.status == "REVIEWING" and c.base_version_id is not None
                      and c.base_version_id != current_id]:
            raise AppError(ErrorCode.DOCUMENT_VERSION_BASE_CHANGED, [
                {"reason": "BASE_VERSION_CHANGED", "message": "기준 버전이 현행과 다른 묶음", "value": stale},
            ])
        return clusters

    def change_policy(self, row: DocumentVersion, body: DocumentVersionUpdateRequest, user: User) -> bool:
        """정책을 바꾸고 운영 기록을 남긴다. 돌려주는 값은 열람 범위가 바뀌었는지."""
        sent = body.model_fields_set
        old_scope, old_policy = row.view_scope, row.transfer_policy
        new_scope = body.view_scope if "view_scope" in sent and body.view_scope is not None else old_scope
        new_policy = body.transfer_policy if "transfer_policy" in sent and body.transfer_policy is not None else old_policy
        if (new_scope, new_policy) == (old_scope, old_policy):
            return False
        if TRANSFER_RANK[new_policy] > TRANSFER_RANK[old_policy] and not body.reason:
            raise field_error(ErrorCode.VALIDATION_ERROR, "reason", "REQUIRED", "외부 전송 정책을 완화하는 사유를 입력해 주세요.")
        row.view_scope, row.transfer_policy = new_scope, new_policy
        self.audit_logs.add("DOCUMENT_POLICY_CHANGE", "document", row.document_id, actor_id=user.id,
                            result=f"{row.version} {old_scope}/{old_policy} → {new_scope}/{new_policy}",
                            reason=body.reason or None)
        return new_scope != old_scope

    def activate(self, row: DocumentVersion, user: User) -> None:
        """기존 현행 → false, 이 버전 → true. 기록 형식은 적재의 activate() 와 같다."""
        old = self.documents.current_version(row.document_id)
        if old is not None:
            old.is_current = False
            self.db.flush()                 # 현행은 문서마다 하나라는 제약 때문에 먼저 내린다
        row.is_current = True
        row.activated_at = row.activated_at or datetime_utils.now()
        self.audit_logs.add("DOCUMENT_VERSION_ACTIVATE", "document", row.document_id, actor_id=user.id,
                            result=f"{old.version if old else '없음'} → {row.version}")

    def recheck_faqs(self, document_id: int, user: User) -> None:
        """이 문서와 연결된 게시 FAQ 가운데 조건을 잃은 것을 비게시로 바꾼다 (API 04 게시·출처 정책). 문서와 무관한 FAQ 는 보지 않는다."""
        self.db.flush()
        codes = self.documents.faq_codes(document_id)
        if not codes:
            return
        faqs = self.documents.active_faqs_for_update(codes)
        publishable = publishable_codes(self.faqs.links())
        for faq in faqs:
            if faq.faq_code not in publishable:
                faq.is_active = False
                faq.updated_by, faq.updated_at = user.id, datetime_utils.now()
                self.audit_logs.add("FAQ_AUTO_UNPUBLISH", "faq", faq.id, result=faq.faq_code, actor_id=user.id,
                                    reason=f"문서 {document_id} 변경으로 공개 출처 없음")

    def lock_document(self, document_id: int) -> KnowledgeDocument:
        document = self.documents.get_for_update(document_id)
        if document is None:
            raise AppError(ErrorCode.DOCUMENT_NOT_FOUND)
        return document

    def check_category(self, doc_type: str, code: str | None) -> None:
        if doc_type == "STANDARD":
            if code is not None:
                raise field_error(ErrorCode.VALIDATION_ERROR, "categoryCode", "NOT_ALLOWED", "공통 기준 문서에는 분류를 넣지 않습니다.")
        elif code is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "categoryCode", "REQUIRED", "분류를 선택해 주세요.")
        elif self.documents.ref(Category, code) is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "categoryCode", "NOT_FOUND", "존재하지 않는 분류입니다.")

    def check_group(self, group_id: int | None) -> None:
        if group_id is not None and self.documents.ref(SupportGroup, group_id) is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "ownerGroupId", "NOT_FOUND", "존재하지 않는 담당 그룹입니다.")

    def view(self, document: KnowledgeDocument, is_admin: bool) -> Document:
        return to_document(document, self.documents.current_version(document.id),
                           self.documents.ref(Category, document.category_code),
                           self.documents.ref(SupportGroup, document.owner_group_id), is_admin)

    def version_views(self, rows: list[DocumentVersion]) -> list[DocumentVersionView]:
        counts = self.documents.chunk_counts([r.id for r in rows])
        users = self.documents.users({r.registered_by for r in rows if r.registered_by is not None})
        return [to_version(r, counts.get(r.id, 0), users.get(r.registered_by)) for r in rows]


def file_format_of(filename: str | None) -> tuple[str, str]:
    suffix = Path(filename or "").suffix.lower()
    file_format = file_constants.FILE_FORMATS.get(suffix)
    if file_format is None:
        raise field_error(ErrorCode.DOCUMENT_FILE_FORMAT_UNSUPPORTED, "file", "INVALID_VALUE")
    return suffix, file_format


def to_document(document: KnowledgeDocument, current: DocumentVersion | None, category: Category | None,
                group: SupportGroup | None, is_admin: bool) -> Document:
    return Document(
        id=document.id,
        doc_code=document.doc_code,
        doc_type=document.doc_type,
        title=document.title,
        category_code=document.category_code,
        category=CategoryRef.model_validate(category) if category else None,
        owner_group_id=document.owner_group_id,
        owner_group=GroupRef.model_validate(group) if group else None,
        is_active=document.is_active,
        current_version=CurrentVersion(
            id=current.id,
            version=current.version,
            file_format=current.file_format,
            view_scope=current.view_scope if is_admin else None,
            transfer_policy=current.transfer_policy if is_admin else None,
            registered_at=current.registered_at,
        ) if current else None,
        created_at=document.created_at,
    )


def to_version(row: DocumentVersion, chunk_count: int, registrar: User | None) -> DocumentVersionView:
    return DocumentVersionView(
        id=row.id,
        document_id=row.document_id,
        version=row.version,
        file_format=row.file_format,
        view_scope=row.view_scope,
        transfer_policy=row.transfer_policy,
        activated_at=row.activated_at,
        is_current=row.is_current,
        version_state="CURRENT" if row.is_current else "EXPIRED" if row.activated_at else "DRAFT",
        ingest_status=row.ingest_status,
        ingest_error=row.ingest_error,
        chunk_count=chunk_count,
        registered_by=row.registered_by,
        registered_by_user=UserRef.model_validate(registrar) if registrar else None,
        registered_at=row.registered_at,
    )


DocumentServiceDep = Annotated[DocumentService, Depends(DocumentService)]
