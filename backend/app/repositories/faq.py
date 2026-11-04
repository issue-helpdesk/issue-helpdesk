from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Text, cast, delete, func, or_, select

from app.db.session import DbSession
from app.models import Category, DocumentChunk, DocumentVersion, Faq, FaqSourceDocument, KnowledgeDocument, User

SORT_COLUMNS = {
    "faqCode": Faq.faq_code,
    "updatedAt": Faq.updated_at,
}


@dataclass(frozen=True)
class FaqLink:
    """현행 청크 하나가 가리키는 FAQ 들 (meta.faq_ids), 또는 FAQ 에 직접 지정한 문서 (location 없음).
    출처·게시 조건 판단에 쓴다. excerpt 는 links(with_excerpt=True) 의 청크 연결에만 있다."""
    faq_codes: tuple[str, ...]
    doc_type: str
    view_scope: str
    document_id: int
    doc_code: str
    title: str
    version: str
    location: str | None
    excerpt: str | None = None


class FaqRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, faq: Faq) -> Faq:
        self.db.add(faq)
        self.db.flush()
        return faq

    def delete(self, faq: Faq) -> None:
        self.db.delete(faq)

    def get(self, faq_id: int) -> Faq | None:
        return self.db.get(Faq, faq_id)

    def get_for_update(self, faq_id: int) -> Faq | None:
        return self.db.get(Faq, faq_id, with_for_update=True)

    def ref(self, model, key):
        return self.db.get(model, key) if key is not None else None

    def codes(self) -> list[str]:
        return list(self.db.scalars(select(Faq.faq_code)))

    def search(
        self,
        category_codes: list[str],
        q: str | None,
        is_active: bool | None,
        allowed_codes: set[str] | None,
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Faq, Category, User | None]], int]:
        """allowed_codes: 이 FAQ 번호만 (게시 조건을 충족한 것). None 이면 거르지 않는다."""
        conditions = []
        if category_codes:
            conditions.append(Faq.category_code.in_(category_codes))
        if is_active is not None:
            conditions.append(Faq.is_active.is_(is_active))
        if allowed_codes is not None:
            conditions.append(Faq.faq_code.in_(allowed_codes))
        if q:
            # 키워드는 배열을 글자로 바꿔 부분 일치로 찾는다 (DB 마다 배열 연산자가 달라서)
            conditions.append(or_(Faq.question.icontains(q, autoescape=True),
                                  cast(Faq.keywords, Text).icontains(q, autoescape=True)))

        total = self.db.scalar(select(func.count()).select_from(select(Faq.id).where(*conditions).subquery()))
        order_by = [(SORT_COLUMNS[f].desc() if desc else SORT_COLUMNS[f].asc()).nulls_last() for f, desc in sort]
        rows = self.db.execute(
            select(Faq, Category, User)
            .join(Category, Category.code == Faq.category_code)
            .outerjoin(User, User.id == Faq.updated_by)
            .where(*conditions)
            .order_by(*order_by, Faq.id)
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total

    def links(self, with_excerpt: bool = False) -> list[FaqLink]:
        """활성 문서의 현행 버전에서 FAQ 를 가리키는 청크와 직접 지정한 연결. 문서 번호·청크 순서대로 (직접 지정은 문서의 맨 뒤).

        현행 버전은 적재가 끝난 것만 될 수 있다 (ck_document_versions_current_needs_done).
        meta.faq_ids 를 걸러 내는 연산은 DB 마다 달라서 청크 meta 를 읽어 파이썬에서 고른다.
        with_excerpt: 청크 본문도 읽는다. 목록은 모든 청크를 읽으므로 본문이 필요한 상세에서만 켠다.
        """
        document_columns = (KnowledgeDocument.doc_type, DocumentVersion.view_scope, KnowledgeDocument.id,
                            KnowledgeDocument.doc_code, KnowledgeDocument.title, DocumentVersion.version)
        chunks = self.db.execute(
            select(DocumentChunk.meta, *document_columns, DocumentChunk.location,
                   *([DocumentChunk.content] if with_excerpt else []))
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentVersion.document_id)
            .where(DocumentVersion.is_current.is_(True), KnowledgeDocument.is_active.is_(True))
            .order_by(KnowledgeDocument.doc_code, DocumentChunk.seq)
        )
        links = [FaqLink(tuple(meta.get("faq_ids") or ()), *rest) for meta, *rest in chunks if (meta or {}).get("faq_ids")]
        direct = self.db.execute(
            select(Faq.faq_code, *document_columns)
            .join(FaqSourceDocument, FaqSourceDocument.faq_id == Faq.id)
            .join(KnowledgeDocument, KnowledgeDocument.id == FaqSourceDocument.document_id)
            .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
            .where(DocumentVersion.is_current.is_(True), KnowledgeDocument.is_active.is_(True))
            .order_by(Faq.faq_code)
        )
        links += [FaqLink((code,), *rest, None) for code, *rest in direct]
        return sorted(links, key=lambda link: link.doc_code)

    def lock_documents(self, document_ids: list[int]) -> None:
        """문서 → FAQ 순으로 잠근다 (문서 정책 변경과 같은 순서). 항상 같은 순서라 서로 기다리다 멈추지 않는다."""
        self.db.scalars(select(KnowledgeDocument.id).where(KnowledgeDocument.id.in_(document_ids))
                        .order_by(KnowledgeDocument.id).with_for_update()).all()

    def public_guide_ids(self, document_ids: list[int]) -> set[int]:
        """이 가운데 활성 문서이고 현행 버전의 열람 범위가 ALL 인 GUIDE."""
        return set(self.db.scalars(
            select(KnowledgeDocument.id)
            .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.id.in_(document_ids), KnowledgeDocument.is_active.is_(True),
                   KnowledgeDocument.doc_type == "GUIDE", DocumentVersion.is_current.is_(True),
                   DocumentVersion.view_scope == "ALL")
        ))

    def replace_sources(self, faq_id: int, document_ids: list[int]) -> None:
        self.db.execute(delete(FaqSourceDocument).where(FaqSourceDocument.faq_id == faq_id))
        self.db.add_all(FaqSourceDocument(faq_id=faq_id, document_id=i) for i in document_ids)
        self.db.flush()


FaqRepositoryDep = Annotated[FaqRepository, Depends(FaqRepository)]
