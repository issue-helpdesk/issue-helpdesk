"""AI 판단 호출 (WBS M4-2-2). 판단 흐름(M4-2-1)은 이 함수 하나로 모델을 부른다.

순서
1. 치환 (docs/10 3.1)    : 이전 대화 → 모은 사실 → 이번 글 순서로 같은 Pseudonymizer 를 쓴다
2. 근거 거르기 (10 4장 ④) : 결과가 있었는데 모두 빠지면 부르지 않는다 (08 3.2 ALL_BLOCKED)
3. 호출 → 검사 (08 3.2 1~3단계) : 버전 · JSON · 필수 키와 자료형. JSON·자료형이 틀리면 한 번 다시 부른다
4. 그래도 안 되면 안전 기본값 (08 3.3)

1·2 에서 오류가 나면 부르지 않고 안전 기본값으로 넘긴다 (docs/10 3.3, 09 T11).
08 3.2 4~9단계(허용값·근거·처리 방향 보정)와 5.3 긴급도 규칙은 판단 흐름(M4-2-1)이 한다.
"""
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agent.llm.port import LLMError, LLMPort
from app.agent.llm.prompt import Taxonomy, build_system_prompt, build_user_content
from app.agent.llm.schemas import (SUPPORTED_SCHEMA_VERSIONS, AIInput, AIOutput, Facts, output_json_schema,
                                   safe_default)
from app.agent.sensitive import Filtered, Pseudonymizer, filter_evidence

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2                                    # 처음 + 다시 한 번 (08 3.2 2·3단계)
RETRY_CODES = ('INVALID_JSON', 'SCHEMA_INVALID', 'MAX_TOKENS')
FACT_TEXTS = ('summary', 'target_system', 'symptom', 'occurred_at', 'time_constraint', 'business_impact')


@dataclass(frozen=True)
class LlmCallRecord:
    """llm_calls 한 행. inquiry_id 는 저장할 때 채운다."""
    purpose: str
    adapter: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    success: bool                       # 쓸 수 있는 응답을 받았는가. API 는 답했어도 형식이 틀리면 False
    error_code: str | None = None


@dataclass(frozen=True)
class JudgeResult:
    output: AIOutput                    # 검사를 통과한 AI 출력, 또는 안전 기본값
    ai_output: dict | None              # inquiry_assessments.ai_output. 안전 기본값·ALL_BLOCKED 면 None (08 5.4)
    failure: str | None = None          # None · AI_FAILED · ALL_BLOCKED (08 3.2 rule)
    error_code: str | None = None       # 실패 사유. FILTER_FAILED · INVALID_JSON · SCHEMA_INVALID · TIMEOUT …
    evidence: Filtered | None = None    # Claude 에 보낸 근거(3.2 8단계 검사용)와 뺀 근거(audit_logs). 검색 전이면 None
    calls: tuple[LlmCallRecord, ...] = field(default=())


def call_judge(inp: AIInput, port: LLMPort, taxonomy: Taxonomy, staff_names: Iterable[str],
               purpose: str) -> JudgeResult:
    """staff_names: 직원 이름 목록 (users.name). purpose: llm_calls.purpose (예: 1차 CLASSIFY, 2차 ANSWER)."""
    try:
        p = Pseudonymizer(staff_names)
        history = [{'role': m.role, 'content': p.apply(m.content)} for m in inp.history]
        facts = _pseudonymize_facts(inp.collected_facts, p)
        message = p.apply(inp.message)
        evidence = None if inp.search is None else filter_evidence(inp.search.documents, inp.search.legacy, p)
    except Exception as e:
        # 오류 내용에 글이 섞일 수 있어 종류만 남긴다. 로그 안전망은 전화번호·이름(C·D)을 가리지 않는다 (docs/10 5.3)
        logger.error('민감정보 치환 실패. 모델을 부르지 않습니다: %s', type(e).__name__)
        return JudgeResult(safe_default(), None, 'AI_FAILED', 'FILTER_FAILED')

    if evidence is not None and evidence.all_blocked:
        return JudgeResult(safe_default('전송제한', '근거가 모두 외부 전송 제한'), None, 'ALL_BLOCKED', None, evidence)

    system = build_system_prompt(taxonomy)
    user = build_user_content(message=message, history=history, collected_facts=facts,
                              ask_more_count=inp.ask_more_count, user_context=inp.user_context, evidence=evidence)
    schema = output_json_schema()

    calls = []
    for _ in range(MAX_ATTEMPTS):
        started = time.monotonic()
        output, code, reply_model, tokens = None, None, port.model, (None, None)
        try:
            reply = port.complete(system, user, schema)
            reply_model, tokens = reply.model, (reply.input_tokens, reply.output_tokens)
            output, code = _parse(reply.text)
        except LLMError as e:
            code = e.code
            reply_model, tokens = e.model or port.model, (e.input_tokens, e.output_tokens)
        calls.append(LlmCallRecord(purpose, port.name, reply_model, int((time.monotonic() - started) * 1000),
                                   *tokens, success=output is not None, error_code=code))
        if output is not None:
            return JudgeResult(output, output.model_dump(mode='json'), evidence=evidence, calls=tuple(calls))
        logger.warning('AI 판단 호출 실패: %s', code)          # 원문은 남기지 않는다 (docs/10 5.3)
        if code not in RETRY_CODES:
            break
    return JudgeResult(safe_default(), None, 'AI_FAILED', code, evidence, tuple(calls))


def _parse(text: str) -> tuple[AIOutput | None, str | None]:
    """08 3.2 1~3단계. 성공하면 (출력, None), 실패하면 (None, 사유)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None, 'INVALID_JSON'
    if not isinstance(data, dict):
        return None, 'SCHEMA_INVALID'
    version = data.get('schema_version')
    if version is not None and version not in SUPPORTED_SCHEMA_VERSIONS:
        return None, 'UNSUPPORTED_VERSION'                  # 다시 부르지 않는다 (1단계). 키가 없으면 3단계에서 걸린다
    try:
        return AIOutput.model_validate(data), None
    except ValidationError:
        return None, 'SCHEMA_INVALID'


def _pseudonymize_facts(facts: Facts | None, p: Pseudonymizer) -> Facts | None:
    if facts is None:
        return None
    changes = {k: p.apply(v) for k in FACT_TEXTS if (v := getattr(facts, k))}
    changes['tried_actions'] = [p.apply(a) for a in facts.tried_actions]
    return facts.model_copy(update=changes)
