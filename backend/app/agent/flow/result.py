"""판단 흐름 결과 (docs/08 5.4, 09 4.1). 백엔드(M1)가 받아 판단 이력·llm_calls·message_sources 에 저장한다.

2차까지 가면 확정값·ai_output·override_reasons 는 최종(2차) 판단 것만 넣고, llm_calls 만 1·2차를 합친다.
"""
from dataclasses import dataclass

from app.agent.llm import AIOutput, LlmCallRecord
from app.agent.sensitive import Filtered
from app.rag.search import DocumentResult, LegacyResult, SearchResponse, message_source_rows

NEXT_STEPS = ('offer', 'collect', 'answered')


@dataclass(frozen=True)
class FlowResult:
    output: AIOutput                    # 확정값 (보정 후). urgency_suggested 는 AI 제안 그대로 둔다 (비교·평가용)
    urgency: str                        # 확정 긴급도 (08 5.3) → inquiry_assessments.urgency
    needs_triage: bool                  # 긴급도 시작값이 없어 P3 로 둠 → 서비스데스크 확인
    next_step: str                      # offer · collect · answered (09 4.1)
    ai_output: dict | None              # 최종 판단의 AI 원본. 안전 기본값·ALL_BLOCKED 면 None
    override_reasons: tuple[dict, ...]  # 보정 + 긴급도 규칙이 바꾼 것 (08 5.4)
    llm_calls: tuple[LlmCallRecord, ...]   # 이 메시지에서 부른 모든 호출 (1·2차, 다시 생성 포함)
    failure: str | None = None          # None · AI_FAILED · ALL_BLOCKED
    error_code: str | None = None       # 실패 사유 (llm README error_code 표 + UNSAFE_REPLY·ANSWER_ASKS_BACK)
    sources: tuple[dict, ...] = ()      # message_sources 행. 확정 evidence 가 가리키는 검색 결과를 쓴 순서대로
    evidence: Filtered | None = None    # 2차에서 보낸·뺀 근거 (audit_logs DOC_BLOCKED·FILTER_FAILED). 검색 안 했으면 None


def used_results(out: AIOutput, search: SearchResponse | None) -> list[DocumentResult | LegacyResult]:
    """확정 evidence 가 가리키는 검색 결과. 저장은 가리기 전 원래 결과로 한다 (M3 스냅샷 규칙)."""
    if search is None:
        return []
    by_key = {**{('DOCUMENT', r.unit_key): r for r in search.documents},
              **{('LEGACY', r.legacy_no): r for r in search.legacy}}
    keys = dict.fromkeys((e.kind, e.source_id) for e in out.evidence)        # 같은 결과를 여러 번 인용해도 한 번
    return [by_key[k] for k in keys if k in by_key]


def source_rows(out: AIOutput, search: SearchResponse | None) -> tuple[dict, ...]:
    return tuple(message_source_rows(used_results(out, search)))
