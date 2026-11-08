"""해결 사례 가이드화: 한 회차 판단 실행 (기획 1~3단계). 묶기·초안(4·5단계)은 이 결과의 forwarded 를 받는다.

티켓마다 커밋한다. 중간에 멈춰도 앞서 처리한 티켓은 남고, 남은 티켓은 다음 회차에 다시 모인다.
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.guide import collect, store
from app.agent.guide.collect import SearchFn
from app.agent.guide.judge import EXCLUDED_JUDGMENTS, CompareItem, GuideDoc, JudgeOutcome, TicketText, judge_ticket
from app.agent.llm.port import LLMPort

logger = logging.getLogger(__name__)


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


def judge_round(session: Session, port: LLMPort, search_fn: SearchFn) -> JudgeRun:
    run = JudgeRun()
    names = collect.staff_names(session)
    guides: dict[str, list[GuideDoc]] = {}
    for t in collect.targets(session):
        kind, reason = collect.precheck(t)
        if kind == 'EXCLUDE':
            store.exclude(session, t.id, reason)
            run.excluded += 1
        elif kind == collect.SEC:
            store.add_sec(session, t)
            run.sec += 1
        else:
            _judge_one(session, port, search_fn, names, guides, t, run)
        session.commit()
    logger.info('가이드화 판단: 넘김 %d, 제외 %d, 실패 %d, SEC %d',
                len(run.forwarded), run.excluded, run.failed, run.sec)
    return run


def _judge_one(session, port, search_fn, names, guides, t, run: JudgeRun) -> None:
    text = collect.ticket_text(session, t)
    if text.category_code not in guides:
        guides[text.category_code] = collect.guides_for(session, text.category_code)
    try:
        items = collect.compare_items(session, search_fn, text)
    except Exception as e:                      # 검색·임베딩 모델 오류. 모델을 부르지 않고 다음 회차에 다시
        logger.error('가이드화 판단: 비교 항목 검색 실패: %s', type(e).__name__)
        store.record_failure(session, t.id, 'SEARCH_FAILED')
        run.failed += 1
        return
    outcome = judge_ticket(text, guides[text.category_code], items, port, names)
    store.add_llm_calls(session, text.inquiry_id, outcome.calls)
    if outcome.judgment is None:
        store.record_failure(session, t.id, outcome.error_code)
        run.failed += 1
    elif outcome.judgment.judgment in EXCLUDED_JUDGMENTS:
        store.exclude(session, t.id, store.exclude_reason(outcome))
        run.excluded += 1
    else:
        store.clear_failure(session, t.id)
        run.forwarded.append(Forwarded(text, outcome, tuple(items)))
