"""긴급도 확정 (M4-2-1) 테스트. 기준은 docs/08 5.3. LLM 을 부르지 않는다."""
import pytest

from app.agent.flow import decide_urgency
from app.agent.llm import AIOutput, CategoryInfo, Taxonomy, TypeInfo, safe_default

TAXONOMY = Taxonomy(
    categories=(CategoryInfo('NET', 'VPN·네트워크'), CategoryInfo('SYS', '업무 시스템'), CategoryInfo('HW', '장비'),
                CategoryInfo('SEC', '정보보안')),
    types=(TypeInfo('NET-02', 'NET', '개인 VPN 접속 장애', 'INCIDENT', 'P3'),
           TypeInfo('NET-03', 'NET', '전사 VPN 장애', 'INCIDENT', 'P1'),
           TypeInfo('SYS-13', 'SYS', '공유 드라이브 접속 불가', 'INCIDENT', 'P2'),
           TypeInfo('HW-04', 'HW', '장비 파손', 'INCIDENT', 'P3'),
           TypeInfo('HW-05', 'HW', '신규 PC 신청', 'REQUEST', 'P4'),
           TypeInfo('SEC-06', 'SEC', '계정 도용 의심', 'INCIDENT', 'P2')),
)


def out(type_code=None, suggested=None, **facts) -> AIOutput:
    d = safe_default().model_dump()
    d.update(action='ANSWER', escalation_reason=None, inquiry_type_code=type_code,
             category_code=type_code.split('-')[0] if type_code else None, urgency_suggested=suggested)
    d['facts'] |= facts
    return AIOutput.model_validate(d)


def rules(u) -> list[str]:
    return [o['rule'] for o in u.overrides]


# 08 5.3 "예시" 6줄
@pytest.mark.parametrize('o, expected', [
    (out('NET-02', 'P3', impact_scope='PERSONAL', work_stopped='partial'), 'P3'),                     # 재택 VPN, 나만
    (out('SYS-13', 'P2', impact_scope='DEPARTMENT', work_stopped='full'), 'P2'),                      # 팀 전체 드라이브
    (out('NET-03', 'P1', impact_scope='COMPANY', work_stopped='full'), 'P1'),                         # 전사 VPN
    (out('NET-02', 'P3', impact_scope='PERSONAL', work_stopped='partial', time_constraint='오늘 14:00 고객 미팅'), 'P2'),
    (out('HW-05', 'P4', impact_scope='PERSONAL', work_stopped='none', time_constraint='월요일까지'), 'P4'),
    (out('HW-04', 'P3', impact_scope='PERSONAL', work_stopped='full', has_workaround=False), 'P2'),   # 노트북 침수
])
def test_doc_examples(o, expected):
    assert decide_urgency(o, TAXONOMY).value == expected


def test_type_default_wins_over_ai_suggestion():
    u = decide_urgency(out('NET-02', 'P2', impact_scope='PERSONAL', work_stopped='partial'), TAXONOMY)
    assert u.value == 'P3'                                           # 같은 이유를 두 번 반영하지 않는다
    assert u.overrides[0] == {'field': 'urgency', 'ai': 'P2', 'final': 'P3', 'rule': 'TYPE_DEFAULT',
                              'reason': '세부 유형 NET-02 기본 긴급도'}


def test_no_type_uses_ai_then_p3_with_triage():
    assert decide_urgency(out(None, 'P4'), TAXONOMY).value == 'P4'
    u = decide_urgency(out(None, None), TAXONOMY)
    assert (u.value, u.needs_triage, u.overrides) == ('P3', True, ())


def test_security_minimum_p2():
    u = decide_urgency(out('NET-02', 'P3', security_suspected=True), TAXONOMY)
    assert (u.value, rules(u)) == ('P2', ['SEC_MIN_P2'])


def test_only_company_reaches_p1():
    # 부서 영향 + 시간 제약이 겹쳐도 P2 (08 5.3 지키는 것 1)
    u = decide_urgency(out('NET-02', 'P3', impact_scope='DEPARTMENT', work_stopped='full',
                           time_constraint='오늘 18시 보고서 마감'), TAXONOMY)
    assert (u.value, rules(u)) == ('P2', ['DEPT_UP1'])
    u = decide_urgency(out('NET-02', 'P3', impact_scope='COMPANY', work_stopped='partial'), TAXONOMY)
    assert (u.value, rules(u)) == ('P1', ['COMPANY_P1'])


def test_company_without_work_impact_is_not_p1():
    assert decide_urgency(out('NET-02', 'P3', impact_scope='COMPANY', work_stopped='none'), TAXONOMY).value == 'P3'


def test_personal_full_needs_no_workaround():
    o = out('HW-04', 'P3', impact_scope='PERSONAL', work_stopped='full', has_workaround=None)    # 모름은 올리지 않는다
    assert decide_urgency(o, TAXONOMY).value == 'P3'


def test_keep_prior_urgency():
    u = decide_urgency(out('NET-02', 'P3'), TAXONOMY, prior_urgency='P2')
    assert (u.value, rules(u)) == ('P2', ['URGENCY_KEEP'])
    assert decide_urgency(out('NET-03', 'P1'), TAXONOMY, prior_urgency='P2').value == 'P1'      # 올리는 건 그대로


def test_safe_default_still_uses_rules():
    # 안전 기본값이어도 긴급도 규칙은 적용한다 (08 3.3). facts 가 비어 있어 시작값만 남는다
    u = decide_urgency(safe_default(), TAXONOMY, prior_urgency='P2')
    assert (u.value, u.needs_triage) == ('P2', True)
