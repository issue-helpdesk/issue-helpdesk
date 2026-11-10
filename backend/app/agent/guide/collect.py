"""해결 사례 가이드화: 판단에 쓸 값 모으기 (기획 1·2단계). DB 를 읽기만 한다.

- targets       : 이번 회차 대상 CLS 티켓 (상태 행이 없거나, 상태가 비었거나, WAITING)
- precheck      : AI 없이 서버가 정하는 제외 (분류 없음, SEC, 처리 결과 없음·짧음)
- guides_for    : 같은 분류의 임직원용 가이드 (넣을 문서 후보)
- compare_items : 비교할 가이드·매뉴얼 항목. 기존 검색을 관리자 권한으로 부른다
"""
from collections.abc import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agent.guide.judge import CompareItem, GuideDoc, TicketText
from app.models import Category, DocumentVersion, InquiryType, KnowledgeDocument, Ticket, TicketGuideState, User
from app.rag.search.result import SearchRequest, SearchResponse

SearchFn = Callable[[SearchRequest], SearchResponse]

SHORT_NOTE = 20                 # 처리 결과가 이보다 짧으면 AI 없이 제외 (case_guide.SHORT_NOTE 와 같은 기준)
TOP_K = 5                       # 비교 항목 수
SEC = 'SEC'
# 보안 티켓은 AI 에 보내지 않아 초안이 티켓 글 복사뿐이고, 보안 글을 초안으로 한 번 더 저장하게 된다 (M4 결정, 2026-11-10)
SEC_REASON = 'SEC 티켓은 가이드화하지 않음'


def targets(session: Session) -> list[Ticket]:
    """이번 회차 대상. 날짜가 아니라 상태로 고른다 (기획 1단계)."""
    stmt = (select(Ticket).outerjoin(TicketGuideState, TicketGuideState.ticket_id == Ticket.id)
            .where(Ticket.work_status == 'CLS',
                   or_(TicketGuideState.ticket_id.is_(None), TicketGuideState.status.is_(None),
                       TicketGuideState.status == 'WAITING'))
            .order_by(Ticket.id))
    return list(session.scalars(stmt))


def precheck(t: Ticket) -> tuple[str, str | None]:
    """('EXCLUDE', 이유) · ('JUDGE', None). 순서: 분류 → SEC → 처리 결과."""
    if not t.category_code:
        return 'EXCLUDE', '분류 없음'
    if t.category_code == SEC:
        return 'EXCLUDE', SEC_REASON
    note = (t.resolution_note or '').strip()
    if not note:
        return 'EXCLUDE', '처리 결과 없음'
    if len(note) < SHORT_NOTE:
        return 'EXCLUDE', f'처리 결과가 짧아 해결 방법을 알 수 없음 ({SHORT_NOTE}자 미만)'
    return 'JUDGE', None


def ticket_text(session: Session, t: Ticket) -> TicketText:
    category = session.get(Category, t.category_code)
    type_code = session.scalar(select(InquiryType.code).where(InquiryType.id == t.inquiry_type_id)) \
        if t.inquiry_type_id else None
    return TicketText(ticket_id=t.id, inquiry_id=t.inquiry_id, receipt_no=t.receipt_no,
                      category_code=t.category_code, category_name=category.name if category else t.category_code,
                      inquiry_type_code=type_code, summary=t.summary, symptom=t.symptom,
                      target_system=t.target_system, resolution_note=(t.resolution_note or '').strip())


def guides_for(session: Session, category_code: str) -> list[GuideDoc]:
    """현행 버전이 있는 같은 분류의 가이드."""
    stmt = (select(KnowledgeDocument.doc_code, KnowledgeDocument.title)
            .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.doc_type == 'GUIDE', KnowledgeDocument.is_active.is_(True),
                   KnowledgeDocument.category_code == category_code, DocumentVersion.is_current.is_(True))
            .order_by(KnowledgeDocument.doc_code))
    return [GuideDoc(code, title) for code, title in session.execute(stmt)]


def search_query(t: TicketText) -> str:
    """요약 + 증상 + 처리 결과. 처리 결과가 있어야 '이미 있음'을 찾는다. 임베딩은 서버 안에서 돈다."""
    return '\n'.join(v for v in (t.summary, t.symptom, t.resolution_note) if v)


def compare_items(session: Session, search_fn: SearchFn, t: TicketText) -> list[CompareItem]:
    """같은 분류(와 공통 기준)의 가이드·매뉴얼 상위 TOP_K. 매뉴얼까지 보려고 관리자 권한으로 찾는다."""
    response = search_fn(SearchRequest(query=search_query(t), service_role='ADMIN', sources=('DOCUMENT',),
                                       category_code=t.category_code, top_k=TOP_K))
    codes = {r.doc_code for r in response.documents}
    types = dict(session.execute(select(KnowledgeDocument.doc_code, KnowledgeDocument.doc_type)
                                 .where(KnowledgeDocument.doc_code.in_(sorted(codes)))).all()) if codes else {}
    return [CompareItem(doc_code=r.doc_code, doc_type=types.get(r.doc_code, 'GUIDE'), version=r.version,
                        location=r.location, chunk_type=r.chunk_type, heading=r.heading_path, text=r.text,
                        transfer_policy=r.transfer_policy)
            for r in response.documents]


def staff_names(session: Session) -> list[str]:
    """치환할 직원 이름 (users.name). 상담 판단과 같은 목록."""
    return [n for n in session.scalars(select(User.name)) if n]
