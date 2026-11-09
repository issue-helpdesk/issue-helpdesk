import json

import pytest
from pydantic import ValidationError

from app.agent.llm.schemas import AIOutput, SecondOutput, merge_second, output_json_schema
from test_flow_correct import FACTS
from test_flow_graph import ANSWERED, reply, run


@pytest.mark.parametrize('rule', ['S02', 'S03', 'S04', 'S05', 'S06', 'S07'])
def test_risk_request_forces_safe_handoff_without_incident_priority(rule):
    r, _, search = run([reply('ASK_MORE', security_rule_ids=[rule], missing_items=['symptom'],
                              facts=FACTS | {'symptom': None}, reply='위험한 실행 방법')])
    assert (r.output.action, r.output.escalation_reason, r.next_step) == ('ESCALATE', '전문판단', 'offer')
    assert r.output.urgent_signal is False and r.urgency == 'P3'
    assert r.output.questions == [] and '위험한 실행 방법' not in r.output.reply
    assert search.requests == []


def test_incident_rule_forces_urgency_even_if_ai_flags_disagree():
    r, _, search = run([reply(security_rule_ids=['S01'])])
    assert r.urgency == 'P2' and r.output.facts.security_suspected
    assert r.output.urgent_signal and search.requests == []


def test_existing_incident_boolean_becomes_security_event():
    r, _, _ = run([reply(facts=FACTS | {'security_suspected': True})])
    assert r.output.security_rule_ids == ['S01']


def test_second_judgment_can_add_security_rule():
    r, mock, _ = run([reply(), reply(security_rule_ids=['S05'])])
    assert len(mock.requests) == 2
    assert r.output.security_rule_ids == ['S05'] and r.next_step == 'offer'


def test_second_merge_cannot_drop_first_signal():
    first = AIOutput.model_validate(json.loads(reply(security_rule_ids=['S02'])))
    part = SecondOutput(action='ANSWER', reply='절차', evidence=[], missing_items=[], questions=[],
                        escalation_reason=None, confidence=.9, action_reason='', security_rule_ids=['S04'])
    assert merge_second(first, part).security_rule_ids == ['S02', 'S04']


def test_detected_signal_survives_regeneration_failure():
    # Detection must not disappear if the original unsafe answer is retried and times out.
    from app.agent.llm import LLMError
    bad = reply(security_rule_ids=['S02'], reply='비밀번호를 알려 주세요')
    r, _, _ = run([bad, LLMError('TIMEOUT')])
    assert r.output.security_rule_ids == ['S02']
    assert r.output.action == 'ESCALATE' and '비밀번호를 알려' not in r.output.reply


def test_unknown_rules_rejected_and_schema_requires_rules():
    with pytest.raises(ValidationError):
        AIOutput.model_validate(json.loads(reply(security_rule_ids=['ADMIN_BYPASS'])))
    assert 'security_rule_ids' in output_json_schema()['required']


def test_normal_reply_still_searches_and_answers():
    r, _, search = run([reply(), ANSWERED])
    assert r.output.security_rule_ids == [] and r.next_step == 'answered'
    assert len(search.requests) == 1


def test_live_evaluation_uses_repository_taxonomy_without_db_or_model():
    from app.agent.security_evaluation import evaluation_taxonomy
    taxonomy = evaluation_taxonomy()
    assert len(taxonomy.categories) == 7 and len(taxonomy.types) == 50
    assert {t.request_kind for t in taxonomy.types} <= {'INCIDENT', 'REQUEST', 'QUESTION'}
