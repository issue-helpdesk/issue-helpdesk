"""해결 사례 가이드화: 한 회차 실행 (기획 1~5단계).

    run_round(session, port, search_fn, embed_fn)     # 판단 → 묶기 → 초안. 7일 실행이 부른다

판단(judge_round)은 티켓마다, 묶기·초안(draft_round)은 묶음마다 커밋한다. 중간에 멈춰도 앞서 처리한 것은 남고,
상태가 비어 있는 티켓은 다음 회차에 다시 모인다.
"""
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.guide import cluster as clu
from app.agent.guide import collect, draft, store
from app.agent.guide.case import CaseFns
from app.agent.guide.collect import SearchFn
from app.agent.guide.judge import EXCLUDED_JUDGMENTS, CompareItem, GuideDoc, JudgeOutcome, TicketText, judge_ticket
from app.agent.llm.port import LLMPort
from app.models import GuideCluster, KnowledgeDocument, SupportGroup, Ticket
from app.rag.case_guide import CaseGuideError, _added_lines, sensitive_warnings

logger = logging.getLogger(__name__)

SecFragment = Callable[[int], tuple[str, list[str]]]


@dataclass(frozen=True)
class Forwarded:
    """판단에 성공해 묶기로 넘기는 티켓 (항목 추가·변경·새 가이드·매뉴얼 후보)."""
    ticket: TicketText
    outcome: JudgeOutcome
    items: tuple[CompareItem, ...]


@dataclass
class JudgeRun:
    forwarded: list[Forwarded] = field(default_factory=list)
    excluded: int = 0
    failed: int = 0
    sec: int = 0


@dataclass
class DraftRun:
    """묶음 단위로 센다."""
    created: int = 0            # 새 묶음 (초안 포함)
    attached: int = 0           # 검토 중 묶음의 근거로 붙음
    waiting: int = 0            # 등록된 묶음과 비슷해 WAITING
    failed: int = 0             # 초안 실패. 티켓 상태는 그대로 (다음 회차에 다시)


# ── 1~3단계: 판단 ────────────────────────────────────────

def judge_round(session: Session, port: LLMPort, search_fn: SearchFn,
                sec_fragment: SecFragment | None = None) -> JudgeRun:
    """sec_fragment: SEC 티켓 글 → 조각 (없으면 SEC 초안을 비워 둔다)."""
    run = JudgeRun()
    names = collect.staff_names(session)
    guides: dict[str, list[GuideDoc]] = {}
    for t in collect.targets(session):
        ticket_id = t.id
        try:
            result, forwarded = _one(session, port, search_fn, names, guides, t, sec_fragment)
            session.commit()
        except Exception as e:                  # 티켓 하나의 오류로 회차를 멈추지 않는다
            session.rollback()
            logger.error('가이드화 판단: 티켓 %d 처리 중 오류: %s', ticket_id, type(e).__name__)
            _fail(session, [ticket_id], 'UNEXPECTED')
            run.failed += 1
            continue
        if forwarded is not None:              # 저장에 성공한 것만 센다
            run.forwarded.append(forwarded)
        else:
            setattr(run, result, getattr(run, result) + 1)
    logger.info('가이드화 판단: 넘김 %d, 제외 %d, 실패 %d, SEC %d',
                len(run.forwarded), run.excluded, run.failed, run.sec)
    return run


def _sec(session, t, sec_fragment, names) -> None:
    md, warnings = None, []
    if sec_fragment is not None:
        try:
            md, warnings = sec_fragment(t.id)
            warnings = [*warnings, *sensitive_warnings(md, list(range(1, len(md.splitlines()) + 1)), names)]
        except CaseGuideError as e:
            md, warnings = None, [f'티켓 글을 초안으로 옮기지 못했습니다: {p}' for p in e.problems]
    store.add_sec(session, t, md, warnings)


def _one(session, port, search_fn, names, guides, t, sec_fragment) -> tuple[str, Forwarded | None]:
    """('excluded' · 'sec' · 'failed' · 'forwarded', 넘길 티켓)."""
    kind, reason = collect.precheck(t)
    if kind == 'EXCLUDE':
        store.exclude(session, t.id, reason)
        return 'excluded', None
    if kind == collect.SEC:
        _sec(session, t, sec_fragment, names)
        return 'sec', None

    text = collect.ticket_text(session, t)
    if text.category_code not in guides:
        guides[text.category_code] = collect.guides_for(session, text.category_code)
    try:
        items = collect.compare_items(session, search_fn, text)
    except Exception as e:                      # 검색·임베딩 모델 오류. 모델을 부르지 않고 다음 회차에 다시
        session.rollback()
        logger.error('가이드화 판단: 비교 항목 검색 실패: %s', type(e).__name__)
        store.record_failure(session, text.ticket_id, 'SEARCH_FAILED')
        return 'failed', None
    outcome = judge_ticket(text, guides[text.category_code], items, port, names)
    store.add_llm_calls(session, text.inquiry_id, outcome.calls)
    if outcome.judgment is None:
        store.record_failure(session, text.ticket_id, outcome.error_code)
        return 'failed', None
    if outcome.judgment.judgment in EXCLUDED_JUDGMENTS:
        store.exclude(session, text.ticket_id, store.exclude_reason(outcome))
        return 'excluded', None
    store.clear_failure(session, text.ticket_id)
    return 'forwarded', Forwarded(text, outcome, tuple(items))


def _fail(session: Session, ticket_ids: list[int], code: str) -> None:
    """오류 난 티켓들의 실패 기록. 이것마저 실패하면 기록 없이 넘어간다 (다음 회차에 다시 모인다)."""
    try:
        for tid in ticket_ids:
            store.record_failure(session, tid, code)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error('가이드화: 실패 기록 못 함 (티켓 %s): %s', ticket_ids, type(e).__name__)


# ── 4·5단계: 묶기와 초안 ─────────────────────────────────

def draft_round(session: Session, port: LLMPort, forwarded: list[Forwarded], embed_fn: clu.EmbedFn,
                case: CaseFns) -> DraftRun:
    run = DraftRun()
    names = collect.staff_names(session)
    centers: dict[int, object] = {}                     # 기존 묶음 id → 평균 벡터 (이번 회차 안에서만)
    groups: dict[tuple, list[Forwarded]] = defaultdict(list)
    for f in sorted(forwarded, key=lambda f: f.ticket.ticket_id):          # 접수 순서대로 묶는다
        j = f.outcome.judgment
        groups[clu.group_key(f.ticket.category_code, j.judgment, j.target_doc, j.target_item)].append(f)

    for key, fs in groups.items():
        try:
            vectors = embed_fn(clu.texts_of([f.ticket for f in fs]))
        except Exception as e:                  # 임베딩 모델 오류. 초안을 만들지 않고 다음 회차에 다시
            logger.error('가이드화 묶기: 임베딩 실패: %s', type(e).__name__)
            _fail(session, [f.ticket.ticket_id for f in fs], 'EMBED_FAILED')
            run.failed += 1
            continue
        for idx in clu.bundle(vectors):
            members = [fs[i] for i in idx]
            ids = [m.ticket.ticket_id for m in members]
            try:
                result = _bundle(session, port, case, names, key, members, clu.centroid([vectors[i] for i in idx]),
                                 embed_fn, centers)
                session.commit()
            except Exception as e:              # 묶음 하나의 오류로 회차를 멈추지 않는다
                session.rollback()
                logger.error('가이드화 초안: 묶음 처리 중 오류 (티켓 %s): %s', ids, type(e).__name__)
                _fail(session, ids, 'UNEXPECTED')
                result = 'failed'
            setattr(run, result, getattr(run, result) + 1)
    logger.info('가이드화 묶기·초안: 새 묶음 %d, 근거 추가 %d, 대기 %d, 실패 %d',
                run.created, run.attached, run.waiting, run.failed)
    return run


def _bundle(session, port, case, names, key, members: list[Forwarded], center, embed_fn, centers) -> str:
    """'created' · 'attached' · 'waiting' · 'failed'."""
    ids = [m.ticket.ticket_id for m in members]
    match = clu.match_existing(session, key, center, embed_fn, cache=centers)
    if match is not None and match.kind == 'ATTACH':
        store.attach(session, match.cluster, ids, case.ticket_warnings(ids))
        centers.pop(match.cluster.id, None)             # 근거가 늘었으니 다음에 다시 계산
        return 'attached'
    if (match is not None and match.kind == 'WAIT') or len(members) < clu.MIN_TICKETS:
        store.wait(session, ids)
        return 'waiting'
    return _create(session, port, case, names, key, members, match.cluster if match else None)


def _groups(session: Session, ticket_ids: list[int]) -> dict[int, str | None]:
    rows = session.execute(select(Ticket.id, SupportGroup.name)
                           .outerjoin(SupportGroup, SupportGroup.id == Ticket.group_id)
                           .where(Ticket.id.in_(ticket_ids))).all()
    return dict(rows)


def _policy(items, doc_code: str, location: str) -> str | None:
    """변경 대상 항목의 전송 정책 (판단 때 받은 비교 항목 값)."""
    return next((i.transfer_policy for i in items if (i.doc_code, i.location) == (doc_code, location)), None)


def _create(session, port, case, names, key, members: list[Forwarded], rejected: GuideCluster | None) -> str:
    category, judgment, target_doc, target_item = key
    tickets = tuple(m.ticket for m in members)
    ids = [t.ticket_id for t in tickets]
    receipts = [t.receipt_no for t in tickets]
    warnings: list[str] = []
    items = draft.items_of(m.items for m in members)
    group_names = _groups(session, ids)
    header = draft.Header(draft.majority((t.inquiry_type_code for t in tickets), '문의 유형', warnings),
                          draft.handling_of((m.outcome.judgment.handling for m in members), warnings),
                          draft.majority((group_names.get(i) for i in ids), '담당 부서', warnings))

    doc = session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.doc_code == target_doc)) \
        if target_doc else None
    basis, target_md = None, None
    try:
        if judgment in ('ADD_ITEM', 'CHANGE'):
            out = case.open_basis(judgment, document_id=doc.id, receipts_=receipts,
                                  **({'target_section': target_item} if judgment == 'CHANGE' else {}))
            basis, warnings = out['draft_basis'], [*warnings, *out['warnings']]
            target_md = basis.get('target_md') if judgment == 'CHANGE' else None
    except CaseGuideError as e:
        logger.error('가이드화 초안: 초안 기준을 만들지 못함 (%s): %s', target_doc, '; '.join(e.problems))
        _record(session, ids, 'BASIS_FAILED')
        return 'failed'

    d = draft.DraftInput(judgment, tickets, items, header.handling,
                         guide={'doc_code': doc.doc_code, 'title': doc.title} if doc else None)
    output, draft_md = None, None
    if judgment == 'CHANGE' and _policy(items, target_doc, target_item) != 'ALLOWED':
        # 가려서 보낸 글을 "원문 그대로" 돌려받으면 ●●● 가 가이드에 들어간다. AI 없이 기존 항목을 초안으로 둔다
        draft_md = target_md
        warnings.append(f'고칠 항목({target_doc} {target_item})은 외부 전송이 허용되지 않아 AI 초안을 만들지 않았습니다. '
                        '기존 항목을 직접 고쳐 주세요')
    else:
        if judgment == 'CHANGE':
            d = draft.DraftInput(judgment, tickets, items, header.handling, d.guide, draft.split_item(target_md)[2])
        outcome, draft_md = draft.draft_bundle(d, header, port, names, target_md=target_md, section_no=target_item)
        store.add_llm_calls(session, tickets[0].inquiry_id, outcome.calls)
        if outcome.output is None:
            _record(session, ids, outcome.error_code)
            return 'failed'
        output = outcome.output

    if judgment == 'NEW_GUIDE':
        try:
            out = case.open_basis('NEW_GUIDE', category_code=category, title=output.guide_title, fragments=[draft_md])
        except CaseGuideError as e:
            logger.error('가이드화 초안: 새 가이드 뼈대를 만들지 못함: %s', '; '.join(e.problems))
            _record(session, ids, 'BASIS_FAILED')
            return 'failed'
        fragment = draft_md
        basis, draft_md, warnings = out['draft_basis'], out['draft_md'], [*warnings, *out['warnings']]
    else:
        fragment = None

    if draft_md:
        warnings += sensitive_warnings(draft_md, _check_lines(draft_md, target_md, fragment), names)
    warnings += case.ticket_warnings(ids)
    info = _review_info(members, output, items, warnings, rejected)
    store.add_cluster(session, ids, category_code=category, judgment=judgment,
                      title=_title(output, target_md, tickets), target_document_id=doc.id if doc else None,
                      base_version_id=(basis or {}).get('base_version_id'),
                      compared_items=_compared(members), draft_md=draft_md, draft_basis=basis, review_info=info)
    return 'created'


def _check_lines(md: str, target_md: str | None, fragment: str | None) -> list[int]:
    """민감정보를 볼 줄. 변경은 기존 항목에 없던 줄, 새 가이드는 조각에서 온 줄만 (뼈대의 6장 문의처 공식 연락처까지
    경고하지 않게), 항목 추가는 조각 전체."""
    if target_md:
        return _added_lines(target_md, md)
    if fragment:
        mine = {line for line in fragment.splitlines() if line.strip()}
        return [i for i, line in enumerate(md.splitlines(), 1) if line in mine]
    return list(range(1, len(md.splitlines()) + 1))


def _record(session, ids, code) -> None:
    for tid in ids:
        store.record_failure(session, tid, code)


def _title(output, target_md, tickets) -> str:
    if output is not None and output.title:
        return output.title.strip()
    if target_md:                                   # AI 를 부르지 않은 변경: 기존 항목 제목
        return draft.split_item(target_md)[0].lstrip('#').strip().split(' ', 1)[-1]
    return tickets[0].summary                       # 매뉴얼 후보


def _compared(members) -> list[dict]:
    out = []
    for m in members:
        for ref in m.outcome.compared:
            if ref not in out:
                out.append(ref)
    return out


def _review_info(members, output, items, warnings, rejected) -> dict:
    """검토 정보 (docs/08). 화면은 지금 reason·warnings 만 보여 준다."""
    reasons = list(dict.fromkeys(m.outcome.judgment.reason.strip() for m in members))
    info = {'reason': '\n'.join(reasons), 'warnings': list(dict.fromkeys(warnings))}
    if output is not None:
        info |= {'form': output.form, 'guessed': output.guessed, 'differences': output.differences,
                 'change_note': output.change_note, 'manual_note': output.manual_note,
                 'guide_title': output.guide_title}
    if members[0].outcome.judgment.judgment == 'MANUAL_CANDIDATE':
        info['manual_items'] = list(dict.fromkeys(f'{i.doc_code} {i.location} {i.heading}' for i in items
                                                  if i.doc_type == 'MANUAL'))
    if rejected is not None:                        # 기획 4단계: 맨 위에 이전 거절 표시
        info['rejected_before'] = {'cluster_id': rejected.id, 'reject_reason': rejected.reject_reason}
        info['warnings'].insert(0, f'이전에 거절된 주제입니다 (묶음 {rejected.id}). 거절 사유: {rejected.reject_reason}')
    return {k: v for k, v in info.items() if v not in (None, [], '')} | {'warnings': info['warnings']}


# ── 한 회차 ──────────────────────────────────────────────

def run_round(session: Session, port: LLMPort, search_fn: SearchFn, embed_fn: clu.EmbedFn,
              case: CaseFns | None = None) -> tuple[JudgeRun, DraftRun]:
    """판단 → 묶기 → 초안. case 를 주지 않으면 이 Session 의 PostgreSQL 연결로 case_guide 함수를 부른다."""
    case = case or CaseFns.for_session(session)
    judged = judge_round(session, port, search_fn, sec_fragment=case.ticket_fragment)
    return judged, draft_round(session, port, judged.forwarded, embed_fn, case)
