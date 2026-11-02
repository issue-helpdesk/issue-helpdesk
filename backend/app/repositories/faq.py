from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Text, cast, func, or_, select

from app.db.session import DbSession
from app.models import Category, DocumentChunk, DocumentVersion, Faq, KnowledgeDocument, User

SORT_COLUMNS = {
    "faqCode": Faq.faq_code,
    "updatedAt": Faq.updated_at,
}


@dataclass(frozen=True)
class FaqLink:
    """현행 청크 하나가 가리키는 FAQ 들 (meta.faq_ids). 출처·게시 조건 판단에 쓴다."""
    faq_codes: tuple[str, ...]
    doc_type: str
    view_scope: str
    document_id: int
    doc_code: str
    title: str
    version: str
    location: str | None


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

    def links(self) -> list[FaqLink]:
        """활성 문서의 현행 버전 청크 가운데 FAQ 를 가리키는 것. 문서 번호·청크 순서대로.

        현행 버전은 적재가 끝난 것만 될 수 있다 (ck_document_versions_current_needs_done).
        meta.faq_ids 를 걸러 내는 연산은 DB 마다 달라서 청크 meta 를 읽어 파이썬에서 고른다.
        """
        rows = self.db.execute(
            select(DocumentChunk.meta, KnowledgeDocument.doc_type, DocumentVersion.view_scope, KnowledgeDocument.id,
                   KnowledgeDocument.doc_code, KnowledgeDocument.title, DocumentVersion.version, DocumentChunk.location)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentVersion.document_id)
            .where(DocumentVersion.is_current.is_(True), KnowledgeDocument.is_active.is_(True))
            .order_by(KnowledgeDocument.doc_code, DocumentChunk.seq)
        )
        return [FaqLink(tuple(meta.get("faq_ids") or ()), *rest) for meta, *rest in rows if (meta or {}).get("faq_ids")]


FaqRepositoryDep = Annotated[FaqRepository, Depends(FaqRepository)]
