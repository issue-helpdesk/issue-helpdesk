"""해결 사례 가이드화: 판단 결과 저장 (기획 "저장 구조"). 티켓 상태는 ticket_guide_states 에만 쓴다.

- exclude        : EXCLUDED 와 이유 (AI 판단 또는 서버 사전 제외)
- record_failure : 실패. 상태는 그대로 두고 사유와 횟수만 (행이 없으면 상태가 빈 행을 만든다)
- clear_failure  : 판단에 성공했지만 아직 묶기 전. 실패 기록만 0 으로
- add_cluster    : 새 묶음 + 티켓 REVIEWING
- attach         : 검토 중 묶음의 근거 티켓에 추가 (초안은 그대로)
- wait           : WAITING (같은 주제의 등록된 묶음이 있음)
- add_llm_calls  : llm_calls. 티켓의 문의 번호로 남긴다

커밋은 부르는 쪽(run)이 티켓마다 한다.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent.guide.judge import JudgeOutcome
from app.agent.llm.call import LlmCallRecord
from app.models import GuideCluster, LlmCall, TicketGuideState


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


def _review(session: Session, ticket_ids, cluster_id: int) -> None:
    for tid in ticket_ids:
        state = _state(session, tid)
        state.status, state.cluster_id, state.exclude_reason = 'REVIEWING', cluster_id, None
        state.fail_code, state.fail_count, state.updated_at = None, 0, _now()


def add_cluster(session: Session, ticket_ids: list[int], **values) -> GuideCluster:
    """새 묶음 1행 + 티켓 REVIEWING. 커밋은 부르는 쪽이 묶음마다 한다 (실패하면 티켓은 그대로)."""
    cluster = GuideCluster(status='REVIEWING', **values)
    session.add(cluster)
    session.flush()
    _review(session, ticket_ids, cluster.id)
    return cluster


def attach(session: Session, cluster: GuideCluster, ticket_ids: list[int], warnings: list[str]) -> None:
    """검토 중(등록 전) 묶음의 근거 티켓에 추가. 초안 본문은 바꾸지 않고, 새 티켓의 경고만 더한다."""
    _review(session, ticket_ids, cluster.id)
    if warnings:
        info = dict(cluster.review_info or {})
        info['warnings'] = [*info.get('warnings', []), *warnings]
        cluster.review_info = info
    cluster.updated_at = _now()


def wait(session: Session, ticket_ids: list[int]) -> None:
    """같은 주제의 등록된 묶음이 있음. 다음 회차에 다시 판단한다 (그사이 현행이 되면 '이미 있음')."""
    for tid in ticket_ids:
        state = _state(session, tid)
        state.status, state.cluster_id, state.exclude_reason = 'WAITING', None, None
        state.fail_code, state.fail_count, state.updated_at = None, 0, _now()


def add_llm_calls(session: Session, inquiry_id: int, calls: tuple[LlmCallRecord, ...]) -> None:
    for c in calls:
        session.add(LlmCall(inquiry_id=inquiry_id, purpose=c.purpose, model=c.model, adapter=c.adapter,
                            latency_ms=c.latency_ms, input_tokens=c.input_tokens, output_tokens=c.output_tokens,
                            success=c.success, error_code=c.error_code))
