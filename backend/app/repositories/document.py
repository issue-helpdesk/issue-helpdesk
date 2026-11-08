from typing import Annotated

from fastapi import Depends
from sqlalchemy import and_, cast, func, or_, select, Text

from app.db.session import DbSession
from app.models import Category, DocumentChunk, DocumentVersion, Faq, FaqSourceDocument, KnowledgeDocument, SupportGroup, User

SORT_COLUMNS = {
    "docCode": KnowledgeDocument.doc_code,
    "title": KnowledgeDocument.title,
    "createdAt": KnowledgeDocument.created_at,
}
CURRENT_JOIN = and_(DocumentVersion.document_id == KnowledgeDocument.id, DocumentVersion.is_current.is_(True))


class DocumentRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, row):
        self.db.add(row)
        self.db.flush()
        return row

    def ref(self, model, key):
        return self.db.get(model, key) if key is not None else None

    def get(self, document_id: int) -> KnowledgeDocument | None:
        return self.db.get(KnowledgeDocument, document_id)

    def get_for_update(self, document_id: int) -> KnowledgeDocument | None:
        """잠금 순서는 문서 → 버전 → FAQ 다 (적재·FAQ 게시와 같다)."""
        return self.db.get(KnowledgeDocument, document_id, with_for_update=True, populate_existing=True)

    def current_version(self, document_id: int) -> DocumentVersion | None:
        return self.db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id,
                                                            DocumentVersion.is_current.is_(True)))

    def version(self, document_id: int, version_id: int, *, for_update: bool = False) -> DocumentVersion | None:
        row = self.db.get(DocumentVersion, version_id, with_for_update=for_update, populate_existing=for_update)
        return row if row is not None and row.document_id == document_id else None

    def by_file_hash(self, sha256: str) -> tuple[DocumentVersion, KnowledgeDocument] | None:
        row = self.db.execute(
            select(DocumentVersion, KnowledgeDocument).join(KnowledgeDocument, KnowledgeDocument.id == DocumentVersion.document_id)
            .where(DocumentVersion.file_sha256 == sha256)
        ).first()
        return tuple(row) if row else None

    def versions(self, document_id: int) -> list[DocumentVersion]:
        return list(self.db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.registered_at.desc(), DocumentVersion.id.desc())
        ))

    def chunk_counts(self, version_ids: list[int]) -> dict[int, int]:
        if not version_ids:
            return {}
        return dict(self.db.execute(
            select(DocumentChunk.version_id, func.count()).where(DocumentChunk.version_id.in_(version_ids))
            .group_by(DocumentChunk.version_id)
        ).all())

    def users(self, user_ids: set[int]) -> dict[int, User]:
        return {u.id: u for u in self.db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def search(
        self,
        doc_types: list[str],
        category_codes: list[str],
        q: str | None,
        is_active: bool | None,
        has_current: bool | None,
        scopes: tuple[str, ...] | None,
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple], int]:
        """scopes: 현행 버전의 열람 범위를 이 안으로 제한한다 (현행 없는 문서도 빠진다). None 이면 거르지 않는다."""
        conditions = []
        if doc_types:
            conditions.append(KnowledgeDocument.doc_type.in_(doc_types))
        if category_codes:
            conditions.append(KnowledgeDocument.category_code.in_(category_codes))
        if q:
            conditions.append(or_(KnowledgeDocument.doc_code.icontains(q, autoescape=True),
                                  KnowledgeDocument.title.icontains(q, autoescape=True)))
        if is_active is not None:
            conditions.append(KnowledgeDocument.is_active.is_(is_active))
        if has_current is not None:
            conditions.append(DocumentVersion.id.is_not(None) if has_current else DocumentVersion.id.is_(None))
        if scopes is not None:
            conditions.append(DocumentVersion.view_scope.in_(scopes))

        base = select(KnowledgeDocument.id).outerjoin(DocumentVersion, CURRENT_JOIN).where(*conditions)
        total = self.db.scalar(select(func.count()).select_from(base.subquery()))
        order_by = [SORT_COLUMNS[f].desc() if desc else SORT_COLUMNS[f].asc() for f, desc in sort]
        rows = self.db.execute(
            select(KnowledgeDocument, DocumentVersion, Category, SupportGroup)
            .outerjoin(DocumentVersion, CURRENT_JOIN)
            .outerjoin(Category, Category.code == KnowledgeDocument.category_code)
            .outerjoin(SupportGroup, SupportGroup.id == KnowledgeDocument.owner_group_id)
            .where(*conditions)
            .order_by(*order_by, KnowledgeDocument.id)
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total

    def faq_codes(self, document_id: int) -> set[str]:
        """이 문서의 모든 버전 청크가 가리키는 FAQ 번호와, 이 문서를 출처로 직접 지정한 FAQ 번호."""
        metas = self.db.scalars(
            select(DocumentChunk.meta).join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
            .where(DocumentVersion.document_id == document_id)
        )
        direct = self.db.scalars(
            select(Faq.faq_code).join(FaqSourceDocument, FaqSourceDocument.faq_id == Faq.id)
            .where(FaqSourceDocument.document_id == document_id)
        )
        return {code for meta in metas for code in (meta or {}).get("faq_ids", [])} | set(direct)

    def chunk_metas(self, version_id: int) -> list[dict | None]:
        """버전 청크의 meta 를 청크 순서대로. 본문 조회(DC-12·13)의 그림 목록에 쓴다."""
        return list(self.db.scalars(
            select(DocumentChunk.meta).where(DocumentChunk.version_id == version_id).order_by(DocumentChunk.seq)
        ))

    def image_scopes(self, key: str) -> set[str]:
        """이 그림을 실제로 쓰는 청크의 열람 범위들. 활성 문서의 적재 끝난 버전만 본다.
        글자 검색은 후보만 줄이고, 판단은 meta.images 의 이름표가 정확히 같은지로 한다."""
        rows = self.db.execute(
            select(DocumentChunk.meta, DocumentVersion.view_scope)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentVersion.document_id)
            .where(cast(DocumentChunk.meta, Text).contains(key, autoescape=True),
                   KnowledgeDocument.is_active.is_(True), DocumentVersion.ingest_status == "DONE")
        )
        return {scope for meta, scope in rows if any(image.get("key") == key for image in (meta or {}).get("images", []))}

    def active_faqs_for_update(self, codes: set[str]) -> list[Faq]:
        return list(self.db.scalars(select(Faq).where(Faq.faq_code.in_(codes), Faq.is_active.is_(True))
                                    .order_by(Faq.id).with_for_update()))


DocumentRepositoryDep = Annotated[DocumentRepository, Depends(DocumentRepository)]
