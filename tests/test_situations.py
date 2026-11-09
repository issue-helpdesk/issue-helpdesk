"""가이드 상황 목록 (M4-3-1) 테스트. 서버 이미지에 dataset 이 없어 만들어 둔 situations.txt 가 가이드와 같은지 본다."""
from app.agent.llm import CategoryInfo, Facts, Taxonomy, situations
from app.agent.llm.call import FACT_TEXTS
from app.agent.llm.prompt import build_system_prompt


def test_file_matches_guides():
    # 다르면 backend 폴더에서 uv run python -m app.agent.llm.situations 로 다시 만든다
    assert situations.load() == situations.build()


def test_only_current_guides_not_manuals():
    text = situations.load()
    docs = [ln for ln in text.splitlines() if not ln.startswith(' ')]
    assert len(docs) == 27 and not any('-M ' in d for d in docs)           # 가이드 27개. 매뉴얼은 외부 전송 BLOCKED
    assert '  3.3 집에서 VPN이 자주 끊김' in text.splitlines()


def test_system_prompt_ends_with_situations():
    p = build_system_prompt(Taxonomy(categories=(CategoryInfo('NET', 'VPN·네트워크'),), types=()))
    assert p.endswith(situations.load())


def test_old_facts_without_situation_still_read():
    """situation 이 생기기 전 DB 에 저장된 facts (inquiry_assessments.facts)."""
    old = {'summary': '', 'target_system': None, 'symptom': None, 'occurred_at': None, 'impact_scope': None,
           'work_stopped': 'unknown', 'has_workaround': None, 'time_constraint': None, 'business_impact': None,
           'security_suspected': False, 'tried_actions': []}
    assert Facts.model_validate(old).situation is None


def test_situation_fact_is_pseudonymized_before_sending():
    """사용자가 "그 밖의 상황"으로 쓴 설명이 facts.situation 에 들어가므로 다음 호출 때 치환한다."""
    assert 'situation' in FACT_TEXTS
