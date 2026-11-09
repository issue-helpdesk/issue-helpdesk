"""AI 보안 검토 기준 S01~S06: 출력 형식·보정·판단 흐름·알림 생성. LLM 은 Mock 이다."""
import json

import pytest
from sqlalchemy import select

from app.agent.flow import correct
from app.agent.flow.correct import SECURITY_HANDOFF
from app.agent.llm import AIOutput, output_json_schema, safe_default
from app.agent.llm.schemas import second_output_json_schema
from app.models import AuditLog, SecurityAlert
from test_auth import bearer, client, login  # noqa: F401 (픽스처)
from test_flow_correct import FACTS, TAXONOMY, inp, out
from test_flow_graph import ANSWERED, reply, run
from test_inquiries import ai, ai_reply, db, headers, owner, start, taxonomy  # noqa: F401


# ── 출력 형식: 배열 개수 제한(maxItems)이 없어야 한다 ───────────
# Claude 출력 형식은 maxItems 를 받지 않아 호출이 400 으로 실패한다 (PR #325 가 되돌려진 원인).

def test_output_schema_has_no_max_items_and_lists_rule_ids():
    s = output_json_schema()
    assert 'maxItems' not in json.dumps(s)
    assert 'maxItems' not in json.dumps(second_output_json_schema())
    assert s['properties']['security_rule_ids'] == {
        'type': 'array', 'items': {'enum': ['S01', 'S02', 'S03', 'S04', 'S05', 'S06']}}
    assert 'security_rule_ids' in s['required']


def test_clean_strips_max_items_even_if_a_model_adds_one():
    from app.agent.llm.schemas import _clean
    assert _clean({'type': 'array', 'maxItems': 3, 'items': {'type': 'string'}}) == {
        'type': 'array', 'items': {'type': 'string'}}


def test_old_output_without_the_field_is_read_as_empty():
    assert out().security_rule_ids == []
    assert safe_default().security_rule_ids == []


# ── 보정 ───────────────────────────────────────────────────────

def first(o, **kw):
    return correct(o, inp(), second=False, sent=None, search=None, taxonomy=TAXONOMY, **kw)


def test_no_rules_changes_nothing():
    o = out(action='ESCALATE', escalation_reason='전문판단', evidence=[])
    c = first(o)
    assert c.output == o and c.overrides == ()


def test_s02_to_s06_offer_handoff_with_fixed_reply_without_urgency():
    c = first(out(security_rule_ids=['S02'], reply='승인 없이 권한을 얻으려면 이렇게 하세요.'))
    o = c.output
    assert (o.action, o.escalation_reason, o.urgent_signal) == ('ESCALATE', '전문판단', False)
    assert o.facts.security_suspected is False                      # 우회 요청이 곧 사고는 아니다
    assert o.reply == SECURITY_HANDOFF and o.questions == []
    assert {x['rule'] for x in c.overrides} >= {'SECURITY_REVIEW'}


def test_s01_marks_security_suspected_and_urgent():
    o = first(out(security_rule_ids=['S01'])).output
    assert (o.action, o.escalation_reason, o.urgent_signal, o.facts.security_suspected) == (
        'ESCALATE', '긴급대응', True, True)


def test_rules_are_deduplicated_and_unknown_values_dropped():
    c = first(out(security_rule_ids=['S03', 'S03', 'S99', 'S07']))
    assert c.output.security_rule_ids == ['S03']
    assert any(x['field'] == 'security_rule_ids' for x in c.overrides)


def test_unknown_values_only_do_not_trigger_handoff():
    c = first(out(security_rule_ids=['S99'], action='ANSWER'))
    assert c.output.security_rule_ids == [] and c.output.action == 'ANSWER'
    assert c.output.reply != SECURITY_HANDOFF


def test_security_overrides_ask_more_questions():
    o = first(out(action='ASK_MORE', missing_items=['target_system'], evidence=[], security_rule_ids=['S06'],
                  questions=[{'label': '대상', 'text': '무엇이 안 되나요?', 'options': ['VPN']}])).output
    assert (o.action, o.questions, o.reply) == ('ESCALATE', [], SECURITY_HANDOFF)


# ── 판단 흐름: 검색 전에 끝난다 ─────────────────────────────

def test_security_rule_ends_before_search():
    r, mock, search = run([reply('ANSWER', security_rule_ids=['S04'], reply='다른 직원 상담은 이렇게 봅니다.')])
    assert (r.next_step, r.output.action, r.output.reply) == ('offer', 'ESCALATE', SECURITY_HANDOFF)
    assert r.output.security_rule_ids == ['S04']
    assert search.requests == [] and [c.purpose for c in r.llm_calls] == ['CLASSIFY']


def test_normal_inquiry_still_goes_through_search_and_answers():
    r, _, search = run([reply('ANSWER'), ANSWERED])
    assert r.output.security_rule_ids == []
    assert r.next_step == 'answered' and len(search.requests) == 1


def test_normal_inquiry_with_empty_rules_in_reply_still_answers():
    r, _, search = run([reply('ANSWER', security_rule_ids=[]), ANSWERED])
    assert r.next_step == 'answered' and len(search.requests) == 1


# ── 저장: 알림·감사 기록 ─────────────────────────────────────

def alerts(db):
    return [(a.alert_type, a.severity, a.status, a.target_type) for a in db.scalars(select(SecurityAlert).order_by(SecurityAlert.id))]


def test_inquiry_with_rules_creates_one_alert_per_rule_and_audit(client, db, owner, headers, ai, taxonomy):
    ai.replies = [ai_reply('ESCALATE', security_rule_ids=['S02', 'S06', 'S02'], escalation_reason='전문판단')]

    r = start(client, headers)

    assert r.status_code == 201
    assert alerts(db) == [('S02', 'MEDIUM', 'NEW', 'inquiry'), ('S06', 'MEDIUM', 'NEW', 'inquiry')]
    assert ai.searches == []
    events = db.scalars(select(AuditLog).where(AuditLog.event_type == 'SECURITY_REVIEW').order_by(AuditLog.id)).all()
    assert [(e.result, e.target_type) for e in events] == [('S02', 'inquiry'), ('S06', 'inquiry')]
    assert all(e.actor_id is None for e in events)


def test_s01_alert_is_high(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply('ESCALATE', security_rule_ids=['S01'], urgent_signal=True, escalation_reason='긴급대응')]
    start(client, headers)
    assert alerts(db) == [('S01', 'HIGH', 'NEW', 'inquiry')]


def test_normal_inquiry_creates_no_alert(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply('ASK_MORE')]
    start(client, headers)
    assert alerts(db) == []
