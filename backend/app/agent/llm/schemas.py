"""AI 입력·출력 형식 (docs/08 1·2장) 을 Pydantic 모델로 옮긴 것. 규칙을 바꾸려면 문서를 먼저 고친다.

- AIInput  : 서버 → AI (08 1장). 서버가 만드는 값이라 허용값을 엄격히 검사한다.
- AIOutput : AI → 서버 (08 2장). 자료형과 필수 키만 검사한다 (08 3.2 3단계).
  허용값 밖의 값은 여기서 막지 않고 판단 흐름(M4-2-1)이 null 로 바꾼다 (08 3.2 4단계).
  대신 Claude 에 보내는 출력 형식(output_json_schema)에는 허용값을 넣어 처음부터 맞게 쓰게 한다.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.security import AI_SECURITY_RULE_IDS
from app.rag.search.result import SearchResponse

SCHEMA_VERSION = '1.0'
SUPPORTED_SCHEMA_VERSIONS = ('1.0',)        # 08 5.5. 목록에 없는 버전은 처리하지 않는다 (08 3.2 1단계)

# 08 3.1 허용값
ACTIONS = ('ANSWER', 'ASK_MORE', 'ESCALATE', 'OUT_OF_SCOPE')
CATEGORY_CODES = ('ACC', 'ACS', 'NET', 'SW', 'HW', 'SYS', 'SEC')
REQUEST_KINDS = ('INCIDENT', 'REQUEST', 'QUESTION')
URGENCIES = ('P1', 'P2', 'P3', 'P4')
IMPACT_SCOPES = ('PERSONAL', 'DEPARTMENT', 'COMPANY')
WORK_STOPPED = ('full', 'partial', 'none', 'unknown')
MISSING_ITEMS = ('target_system', 'symptom', 'situation', 'occurred_at', 'impact', 'tried_actions')
EVIDENCE_KINDS = ('DOCUMENT', 'LEGACY')
ESCALATION_REASONS = ('실제조치', '승인', '권한변경', '전문판단', '근거부족', '전송제한', '긴급대응')


def _enum(values, nullable=False):
    """출력 형식에만 허용값을 적는다. Pydantic 검사는 str 로만 한다 (모듈 설명 참고)."""
    return Field(json_schema_extra={'enum': [*values, None] if nullable else list(values)})


Action = Annotated[str, _enum(ACTIONS)]
CategoryCode = Annotated[str | None, _enum(CATEGORY_CODES, nullable=True)]
RequestKind = Annotated[str | None, _enum(REQUEST_KINDS, nullable=True)]
Urgency = Annotated[str | None, _enum(URGENCIES, nullable=True)]
ImpactScope = Annotated[str | None, _enum(IMPACT_SCOPES, nullable=True)]
WorkStopped = Annotated[str, _enum(WORK_STOPPED)]
MissingItem = Annotated[str, _enum(MISSING_ITEMS)]
EvidenceKind = Annotated[str, _enum(EVIDENCE_KINDS)]
EscalationReason = Annotated[str | None, _enum(ESCALATION_REASONS, nullable=True)]
SecurityRuleId = Annotated[str, _enum(AI_SECURITY_RULE_IDS)]


class _Strict(BaseModel):
    # 모든 키가 있어야 한다. 값이 없으면 null 또는 [] (08 2.1)
    model_config = ConfigDict(extra='forbid', frozen=True)


# ── 출력 (08 2장) ──────────────────────────────────────────

class Facts(_Strict):
    """08 2.2. 입력의 collected_facts 도 이 모양이다."""
    summary: str
    target_system: str | None
    symptom: str | None
    situation: str | None                   # 가이드 상황 목록(situations.txt)에서 고른 상황 제목. 목록에 없으면 사용자 설명
    occurred_at: str | None                 # 사용자 표현 그대로 ("오늘 아침부터")
    impact_scope: ImpactScope
    work_stopped: WorkStopped
    has_workaround: bool | None
    time_constraint: str | None
    business_impact: str | None
    security_suspected: bool
    tried_actions: list[str]

    @model_validator(mode='before')
    @classmethod
    def _old_facts(cls, v):
        """situation 이 생기기 전(M4-3-1) 저장된 facts 도 읽는다. 출력 형식에서는 필수 칸이다."""
        if isinstance(v, dict) and 'situation' not in v:
            return {**v, 'situation': None}
        return v


class Rationale(_Strict):
    category: str
    urgency_reasons: list[str]
    action: str


class Evidence(_Strict):
    kind: EvidenceKind
    source_id: str                          # DOCUMENT → unit_key, LEGACY → legacy_no
    quote: str


class Question(_Strict):
    """추가 질문 하나 (M4-3-1). 화면이 options 는 버튼으로, allow_text 면 직접 입력칸을 함께 보여 준다.
    답을 보낼 때 label 을 앞에 붙인다 ("상황: 집에서 자주 끊겨요"). allow_text 는 서버가 정한다 (correct.py)."""
    label: str | None
    text: str
    options: list[str]
    allow_text: bool

    @model_validator(mode='before')
    @classmethod
    def _old_question(cls, v):
        """label·allow_text 가 생기기 전 모양도 읽는다 (#302 시점 저장값·Mock). 출력 형식에서는 필수 칸이다."""
        if isinstance(v, dict):
            return {'label': None, 'allow_text': False, **v}
        return v


class AIOutput(_Strict):
    schema_version: Annotated[str, _enum(SUPPORTED_SCHEMA_VERSIONS)]
    action: Action
    urgent_signal: bool
    title: str
    category_code: CategoryCode
    inquiry_type_code: str | None
    request_kind: RequestKind
    urgency_suggested: Urgency
    facts: Facts
    rationale: Rationale
    reply: str
    questions: list[Question]
    evidence: list[Evidence]
    missing_items: list[MissingItem]
    escalation_reason: EscalationReason
    confidence: float | None = Field(ge=0, le=1)
    # 해당하는 보안 검토 기준(S01~S06). 없으면 []. 개수 상한(max_length)은 걸지 않는다:
    # 출력 형식이 maxItems 를 받지 않아 모든 호출이 400 으로 실패한다 (PR #325 되돌림 원인). 중복·잘못된 값은 correct 가 정리한다
    security_rule_ids: list[SecurityRuleId]

    @model_validator(mode='before')
    @classmethod
    def _old_output(cls, v):
        """questions·security_rule_ids 가 생기기 전 모양도 읽는다 (평가 도구·Mock). 출력 형식에서는 필수 칸이다."""
        if isinstance(v, dict):
            return {'questions': [], 'security_rule_ids': [], **v}
        return v


# ── 2차 판단 출력 (08 2.6) ─────────────────────────────────
# 2차(검색 뒤)는 검색 결과로 정해지는 칸만 받고, 나머지 칸은 같은 메시지의 1차 판단 값을 쓴다.
# 1차와 같은 칸을 다시 쓰지 않아 출력이 줄고 빨라진다 (2026-11-03 시험: 2차 출력 약 1,300 → 640토큰)
SECOND_FIELDS = ('action', 'reply', 'questions', 'evidence', 'missing_items', 'escalation_reason', 'confidence')


class SecondOutput(_Strict):
    action: Action
    reply: str
    questions: list[Question]
    evidence: list[Evidence]
    missing_items: list[MissingItem]
    escalation_reason: EscalationReason
    confidence: float | None = Field(ge=0, le=1)
    action_reason: str                      # 처리 방향 근거. rationale.action 에 넣는다


def merge_second(first: AIOutput, part: SecondOutput) -> AIOutput:
    """1차 판단에 2차 칸을 덮어 2장 출력 모양으로 만든다."""
    return first.model_copy(update={k: getattr(part, k) for k in SECOND_FIELDS}
                            | {'rationale': first.rationale.model_copy(update={'action': part.action_reason})})


def _clean(node):
    """Pydantic 이 만든 schema 에서 출력 형식이 받지 않는 것(title·숫자 범위)과 코드 설명(description)을 빼고,
    허용값이 있는 칸은 {'enum': [...]} 하나로 둔다. 숫자 범위는 응답을 받은 뒤 Pydantic 이 검사한다.
    """
    if isinstance(node, dict):
        if 'enum' in node:
            return {'enum': node['enum']}
        # 값이 dict 인 'title' 은 출력 칸 이름(AIOutput.title)이라 남긴다
        return {k: _clean(v) for k, v in node.items()
                if not (k in ('title', 'description', 'minimum', 'maximum', 'maxItems') and not isinstance(v, dict))}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def output_json_schema() -> dict:
    """Claude 출력 형식(output_config.format)에 넣을 JSON Schema."""
    return _clean(AIOutput.model_json_schema())


def second_output_json_schema() -> dict:
    """2차 판단 출력 형식 (08 2.6)."""
    return _clean(SecondOutput.model_json_schema())


def safe_default(escalation_reason: str = '전문판단', reason: str = 'AI 판단 실패') -> AIOutput:
    """AI 출력을 쓸 수 없을 때 쓰는 값 (08 3.3). ALL_BLOCKED 는 escalation_reason='전송제한'."""
    return AIOutput(
        schema_version=SCHEMA_VERSION, action='ESCALATE', urgent_signal=False,
        title='IT 문의 (자동 분류 실패)', category_code=None, inquiry_type_code=None, request_kind=None,
        urgency_suggested=None,
        facts=Facts(summary='', target_system=None, symptom=None, situation=None, occurred_at=None, impact_scope=None,
                    work_stopped='unknown', has_workaround=None, time_constraint=None, business_impact=None,
                    security_suspected=False, tried_actions=[]),
        rationale=Rationale(category='', urgency_reasons=[], action=reason),
        reply='지금은 자동으로 확인하기 어려워요. 담당자에게 연결해 드릴까요?',
        questions=[], evidence=[], missing_items=[], escalation_reason=escalation_reason, confidence=None,
        security_rule_ids=[],
    )


# ── 입력 (08 1장) ──────────────────────────────────────────

class Message(_Strict):
    role: Literal['user', 'assistant']
    content: str                            # DB 에 저장된 글 (저장 전 가림을 거친 글)


class UserContext(_Strict):
    employee_no: str                        # 서버만
    service_role: Literal['EMPLOYEE', 'AGENT', 'ADMIN']
    department_name: str | None = None
    pc_os: str | None = None


class AIInput(_Strict):
    model_config = ConfigDict(extra='forbid', frozen=True, arbitrary_types_allowed=True)

    schema_version: Literal['1.0'] = SCHEMA_VERSION
    session_id: str
    inquiry_id: str
    message: str
    history: list[Message] = []             # 최근 N턴 (N 은 08 5.6 합의 전이라 부르는 쪽이 자른다)
    collected_facts: Facts | None = None
    ask_more_count: int = Field(ge=0)
    ask_more_unanswered_count: int = Field(0, ge=0)                 # 서버만
    prior_urgent_signal: bool = False                               # 서버만
    prior_urgency: Literal['P1', 'P2', 'P3', 'P4'] | None = None    # 서버만
    user_context: UserContext
    search: SearchResponse | None           # 검색 전 1차 판단이면 None
