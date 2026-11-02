"""FAQ (FQ-01~05). 게시 조건: 활성 문서의 현행 GUIDE 이고 열람 범위 ALL 인 청크가 이 FAQ 를 가리켜야 한다 (API 04 게시·출처 정책)."""
import re
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.core.permissions import visible_scopes
from app.db.session import DbSession
from app.models import Category, Faq, User
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.faq import FaqLink, FaqRepositoryDep
from app.schemas.common import Page, parse_sort
from app.schemas.faq import (
    Faq as FaqView,
    FaqCreateRequest,
    FaqDetail,
    FaqListQuery,
    FaqSource,
    FaqUpdateRequest,
)
from app.schemas.inquiry import CategoryRef, UserRef
from app.utils import datetime_utils

CODE_NUMBER = re.compile(r"^FAQ-(\d+)$")


class FaqService:
    def __init__(self, db: DbSession, faqs: FaqRepositoryDep, audit_logs: AuditLogRepositoryDep) -> None:
        self.db = db
        self.faqs = faqs
        self.audit_logs = audit_logs

    def list_faqs(self, query: FaqListQuery, viewer: User) -> Page[FaqView]:
        """FQ-01. ADMIN 이 아니면 게시 중이고 게시 조건을 충족한 것만. 조건은 페이지 계산 전에 건다."""
        is_admin = viewer.service_role == "ADMIN"
        if query.is_active is not None and not is_admin:
            raise AppError(ErrorCode.FORBIDDEN)
        rows, total = self.faqs.search(
            category_codes=query.category_code,
            q=query.q or None,
            is_active=query.is_active if is_admin else True,
            allowed_codes=None if is_admin else publishable_codes(self.faqs.links()),
            sort=parse_sort(query.sort),
            offset=query.offset,
            limit=query.size,
        )
        items = [to_view(faq, category, updater, is_admin) for faq, category, updater in rows]
        return Page.of(items, query.page, query.size, total)

    def get_faq(self, faq_id: int, viewer: User) -> FaqDetail:
        """FQ-02. 출처는 보는 사람의 열람 범위로 거른다."""
        is_admin = viewer.service_role == "ADMIN"
        faq = self.faqs.get(faq_id)
        links = self.faqs.links()
        if faq is None or not (is_admin or (faq.is_active and faq.faq_code in publishable_codes(links))):
            raise AppError(ErrorCode.FAQ_NOT_FOUND)
        view = to_view(faq, self.faqs.ref(Category, faq.category_code), self.faqs.ref(User, faq.updated_by), is_admin)
        return FaqDetail(**view.model_dump(), sources=sources_of(faq.faq_code, links, visible_scopes(viewer.service_role)))

    def create(self, body: FaqCreateRequest, user: User) -> FaqView:
        """FQ-03. 번호가 없으면 다음 번호를 준다."""
        self.check_category(body.category_code)
        code = body.faq_code or next_code(self.faqs.codes())
        if body.is_active:
            self.check_publishable(code)
        try:
            faq = self.faqs.add(Faq(faq_code=code, category_code=body.category_code, question=body.question,
                                    answer=body.answer, keywords=body.keywords, is_active=body.is_active,
                                    updated_by=user.id))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise field_error(ErrorCode.FAQ_CODE_DUPLICATE, "faqCode", "DUPLICATE")
        return to_view(faq, self.faqs.ref(Category, faq.category_code), user, is_admin=True)

    def update(self, faq_id: int, body: FaqUpdateRequest, user: User) -> FaqView:
        """FQ-04. 보낸 필드만 바꾼다. 수정 뒤에도 게시 중이면 게시 조건을 다시 본다."""
        faq = self.faqs.get_for_update(faq_id)
        if faq is None:
            raise AppError(ErrorCode.FAQ_NOT_FOUND)
        sent = body.model_fields_set
        if "category_code" in sent:
            self.check_category(body.category_code)
        active_after = body.is_active if "is_active" in sent else faq.is_active
        if sent and active_after:
            self.check_publishable(faq.faq_code)
        for name in sent:
            setattr(faq, name, getattr(body, name))
        if sent:
            faq.updated_by, faq.updated_at = user.id, datetime_utils.now()
        self.db.commit()
        return to_view(faq, self.faqs.ref(Category, faq.category_code), self.faqs.ref(User, faq.updated_by), is_admin=True)

    def delete(self, faq_id: int, user: User) -> None:
        """FQ-05. 행을 지우고 운영 기록을 남긴다."""
        faq = self.faqs.get_for_update(faq_id)
        if faq is None:
            raise AppError(ErrorCode.FAQ_NOT_FOUND)
        self.audit_logs.add("FAQ_DELETE", "faq", faq.id, result=faq.faq_code, actor_id=user.id)
        self.faqs.delete(faq)
        self.db.commit()

    def check_category(self, code: str) -> None:
        if self.faqs.ref(Category, code) is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "categoryCode", "NOT_FOUND", "존재하지 않는 분류입니다.")

    def check_publishable(self, code: str) -> None:
        if code not in publishable_codes(self.faqs.links()):
            raise AppError(ErrorCode.FAQ_SOURCE_NOT_PUBLIC)


FaqServiceDep = Annotated[FaqService, Depends(FaqService)]


def publishable_codes(links: list[FaqLink]) -> set[str]:
    """공개 출처(GUIDE·ALL)가 있고, 제한 문서(열람 범위가 ALL 이 아님)에는 연결되지 않은 FAQ 번호."""
    public, restricted = set(), set()
    for link in links:
        if link.view_scope != "ALL":
            restricted.update(link.faq_codes)
        elif link.doc_type == "GUIDE":
            public.update(link.faq_codes)
    return public - restricted


def sources_of(code: str, links: list[FaqLink], scopes: tuple[str, ...]) -> list[FaqSource]:
    """이 FAQ 를 가리키는 현행 청크. 같은 문서·위치는 한 번만."""
    seen, out = set(), []
    for link in links:
        key = (link.document_id, link.version, link.location)
        if code in link.faq_codes and link.view_scope in scopes and key not in seen:
            seen.add(key)
            out.append(FaqSource(document_id=link.document_id, doc_code=link.doc_code, title=link.title,
                                 version=link.version, location=link.location))
    return out


def next_code(codes: list[str]) -> str:
    numbers = [int(m.group(1)) for c in codes if (m := CODE_NUMBER.match(c))]
    return f"FAQ-{max(numbers, default=0) + 1:03d}"


def to_view(faq: Faq, category: Category, updater: User | None, is_admin: bool) -> FaqView:
    return FaqView(
        id=faq.id,
        faq_code=faq.faq_code,
        category_code=faq.category_code,
        category=CategoryRef.model_validate(category),
        question=faq.question,
        answer=faq.answer,
        keywords=faq.keywords or [],
        is_active=faq.is_active,
        updated_by=UserRef.model_validate(updater) if updater and is_admin else None,
        created_at=faq.created_at,
        updated_at=faq.updated_at,
    )
