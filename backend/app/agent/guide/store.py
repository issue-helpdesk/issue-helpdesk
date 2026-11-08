"""해결 사례 가이드화: 판단 결과 저장 (기획 "저장 구조"). 티켓 상태는 ticket_guide_states 에만 쓴다.

- exclude        : EXCLUDED 와 이유 (AI 판단 또는 서버 사전 제외)
- record_failure : 실패. 상태는 그대로 두고 사유와 횟수만 (행이 없으면 상태가 빈 행을 만든다)
- clear_failure  : 판단에 성공했지만 아직 묶기 전. 실패 기록만 0 으로
- add_sec        : SEC 티켓 1건 = SEC_MANUAL 묶음 1개. 티켓은 REVIEWING (묶음 상태 = 티켓 상태)
- add_llm_calls  : llm_calls. 티켓의 문의 번호로 남긴다

커밋은 부르는 쪽(run)이 티켓마다 한다.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent.guide.judge import JudgeOutcome
from app.agent.llm.call import LlmCallRecord
from app.models import GuideCluster, LlmCall, Ticket, TicketGuideState

SEC_REASON = 'SEC 티켓은 외부 모델에 보내지 않아 AI 판단 없이 관리자가 직접 검토한다'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state(session: Session, ticket_id: int) -> TicketGuideState:
    state = session.get(TicketGuideState, ticket_id)
    if state is None:
        state = TicketGuideState(ticket_id=ticket_id, status=None, fail_count=0)
        session.add(state)
    return state


def exclude(session: Session, ticket_id: int, reason: str) -> None:
    state = _state(session, ticket_id)
    state.status, state.cluster_id, state.exclude_reason = 'EXCLUDED', None, reason
    state.fail_code, state.fail_count, state.updated_at = None, 0, _now()


def exclude_reason(outcome: JudgeOutcome) -> str:
    """AI 가 제외한 이유. 이미 있음이면 어느 항목인지 앞에 붙인다."""
    j = outcome.judgment
    if j.judgment == 'EXISTS':
        return f'이미 있음 ({j.target_doc} {j.target_item}): {j.reason}'
    return f'대상 아님: {j.reason}'


def record_failure(session: Session, ticket_id: int, code: str | None) -> None:
    state = _state(session, ticket_id)
    state.fail_code = code or 'UNKNOWN'
    state.fail_count = (state.fail_count or 0) + 1
    state.updated_at = _now()


def clear_failure(session: Session, ticket_id: int) -> None:
    state = session.get(TicketGuideState, ticket_id)
    if state is not None and (state.fail_code or state.fail_count):
        state.fail_code, state.fail_count, state.updated_at = None, 0, _now()


def add_sec(session: Session, t: Ticket) -> GuideCluster:
    """초안 글은 김태연 님 조각 함수로 채운다 (아직 연결 전이라 비어 있다)."""
    cluster = GuideCluster(category_code=t.category_code, judgment='SEC_MANUAL', status='REVIEWING',
                           title=t.summary, review_info={'reason': SEC_REASON})
    session.add(cluster)
    session.flush()
    state = _state(session, t.id)
    state.status, state.cluster_id, state.exclude_reason = 'REVIEWING', cluster.id, None
    state.fail_code, state.fail_count, state.updated_at = None, 0, _now()
    return cluster


def add_llm_calls(session: Session, inquiry_id: int, calls: tuple[LlmCallRecord, ...]) -> None:
    for c in calls:
        session.add(LlmCall(inquiry_id=inquiry_id, purpose=c.purpose, model=c.model, adapter=c.adapter,
                            latency_ms=c.latency_ms, input_tokens=c.input_tokens, output_tokens=c.output_tokens,
                            success=c.success, error_code=c.error_code))
