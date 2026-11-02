"""긴급도 확정 (docs/08 5.3). LLM 밖의 코드 규칙이며 facts 만 본다. 판단 흐름의 decide_urgency 노드와 접수 초안 수정(TK-03)이 쓴다.

- 시작값: 세부 유형 기본 긴급도 → 없으면 AI 제안값 → 둘 다 없으면 P3 (서비스데스크 확인)
- 올리기만 한다. P1 은 전사 영향일 때만이고 다른 규칙은 P2 까지. 같은 이유는 한 번만 반영한다
- 대화 중에는 이전 확정값(prior_urgency)보다 내리지 않는다 (URGENCY_KEEP)
"""
from dataclasses import dataclass

from app.agent.flow.correct import override
from app.agent.llm import AIOutput, Facts, Taxonomy, TypeInfo

LEVELS = ('P1', 'P2', 'P3', 'P4')
CAP = 2                         # 전사 규칙 말고는 P2 까지만 올린다
STARTING = 'P3'                 # 시작값이 없을 때


@dataclass(frozen=True)
class Urgency:
    value: str                          # 확정 긴급도 → inquiry_assessments.urgency
    needs_triage: bool                  # 시작값이 없어 P3 로 둠 → 서비스데스크 확인 대상
    overrides: tuple[dict, ...]


def decide_urgency(out: AIOutput, taxonomy: Taxonomy, prior_urgency: str | None = None) -> Urgency:
    """out 은 보정을 마친 출력이다 (세부 유형이 분류 체계와 맞는 것만 남아 있다)."""
    t = next((t for t in taxonomy.types if t.code == out.inquiry_type_code), None)
    return urgency_of(out.facts, out.urgency_suggested, t, prior_urgency)


def urgency_of(f: Facts, ai: str | None, t: TypeInfo | None, prior_urgency: str | None = None) -> Urgency:
    """같은 규칙을 AI 출력 없이 쓴다. 접수 초안에서 세부 유형을 바꿨을 때 다시 계산한다 (TK-03)."""
    o: list[dict] = []
    if t is not None:
        start = t.default_urgency
        if start != ai:
            o.append(override('urgency', ai, start, 'TYPE_DEFAULT', f'세부 유형 {t.code} 기본 긴급도'))
    else:
        start = ai or STARTING
    n = LEVELS.index(start) + 1

    working = f.work_stopped in ('full', 'partial')
    # (조건, 이 규칙이 주는 값, rule, 이유). 값은 1=P1 … 4=P4
    rules = (
        (f.security_suspected, lambda n: CAP, 'SEC_MIN_P2', '보안 사고 의심은 최소 P2'),
        (f.impact_scope == 'PERSONAL' and f.work_stopped == 'full' and f.has_workaround is False,
         lambda n: CAP, 'PERSONAL_FULL_MIN_P2', '개인 업무 전면 중단, 대체 방법 없음'),
        (f.impact_scope == 'DEPARTMENT', lambda n: min(n - 1, CAP), 'DEPT_UP1', '부서 영향은 한 단계 올림, 최소 P2'),
        (f.impact_scope == 'COMPANY' and working, lambda n: 1, 'COMPANY_P1', '전사 업무 중단·지장'),
        (bool(f.time_constraint) and working, lambda n: n - 1, 'TIME_UP1', '구체적인 시간 제약과 업무 지장'),
    )
    for hit, target, rule, why in rules:
        if not hit:
            continue
        new = min(n, target(n) if rule == 'COMPANY_P1' else max(target(n), CAP))     # 내리지 않는다
        if new != n:
            o.append(override('urgency', ai, LEVELS[new - 1], rule, why))
            n = new

    if prior_urgency is not None and LEVELS.index(prior_urgency) + 1 < n:
        o.append(override('urgency', ai, prior_urgency, 'URGENCY_KEEP', '대화 중에는 이전 긴급도보다 내리지 않음'))
        n = LEVELS.index(prior_urgency) + 1
    return Urgency(LEVELS[n - 1], t is None and ai is None, tuple(o))
