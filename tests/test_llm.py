"""AI 판단 호출부 (M4-2-2) 테스트. 기준은 docs/08 1~3장. Claude 는 부르지 않는다 (Mock·가짜 client)."""
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import app.agent.llm.call as call_module
from app.agent.llm import (AIInput, AIOutput, CategoryInfo, ClaudeAdapter, LLMError, MockAdapter, Taxonomy, TypeInfo,
                           build_system_prompt, call_judge, output_json_schema, safe_default)
from app.agent.llm import config as llm_config
from app.rag.search import ChunkHit, DocumentResult, LegacyResult, SearchResponse

TAXONOMY = Taxonomy(
    categories=(CategoryInfo('NET', 'VPN·네트워크', '사내 Wi-Fi, VPN 장애'), CategoryInfo('SEC', '정보보안')),
    types=(TypeInfo('NET-02', 'NET', '개인 VPN 접속 장애', 'INCIDENT', 'P3'),
           TypeInfo('SEC-06', 'SEC', '계정 도용 의심', 'INCIDENT', 'P2')),
)

# 08 4.1 출력 예시
ANSWER = {
    'schema_version': '1.0', 'action': 'ANSWER', 'urgent_signal': False,
    'title': "재택 중 VPN '서버에 연결할 수 없습니다' 오류", 'category_code': 'NET', 'inquiry_type_code': 'NET-02',
    'request_kind': 'INCIDENT', 'urgency_suggested': 'P3',
    'facts': {'summary': '재택 근무 중 VPN 연결 시 오류가 나며 연결되지 않음', 'target_system': '사내 VPN',
              'symptom': "VPN 연결 시 '서버에 연결할 수 없습니다' 오류", 'occurred_at': '오늘 아침부터',
              'impact_scope': 'PERSONAL', 'work_stopped': 'partial', 'has_workaround': None, 'time_constraint': None,
              'business_impact': '재택 근무 중 VPN이 필요한 사내 시스템을 쓰지 못함', 'security_suspected': False,
              'tried_actions': ['재부팅']},
    'rationale': {'category': '한 명의 VPN 접속 장애라 NET-02에 해당', 'urgency_reasons': ['개인 영향'],
                  'action': 'Guide 근거 충분'},
    'reply': 'VPN 클라이언트를 최신 버전으로 업데이트한 뒤 다시 연결해 보세요.',
    'evidence': [{'kind': 'DOCUMENT', 'source_id': 'IT-NET-001@v2.0/item:3.1', 'quote': 'VPN 클라이언트가 구버전입니다'}],
    'missing_items': [], 'escalation_reason': None, 'confidence': 0.82,
}
ANSWER_JSON = json.dumps(ANSWER, ensure_ascii=False)


def doc(code='IT-NET-001', policy='ALLOWED', text='원인: VPN 클라이언트가 구버전입니다. 김민지 담당 010-1234-5678'):
    return DocumentResult(unit_key=f'{code}@v2.0/item:3.1', chunk_type='ITEM', doc_code=code, title='VPN 가이드',
                          version='v2.0', location='3.1', heading_path='3. 조치 > 3.1', text=text,
                          chunks=(ChunkHit(412, 1, 0.86),), unit_score=0.86, score_type='cosine:kure',
                          view_scope='ALL', transfer_policy=policy, inquiry_type_codes=('NET-02',),
                          handling='사용자 직접 조치')


def case(policy='MASKED'):
    return LegacyResult(legacy_inquiry_id=1, legacy_no='INQ-2026-00245', inquiry_type_code='NET-02', title='VPN 오류',
                        text='VPN 오류 / 구버전 / 재설치', root_cause='구버전', resolution='재설치',
                        resolved_at='2026-07-09 13:51', score=0.6, score_type='cosine:kure', view_scope='ALL',
                        transfer_policy=policy)


def inp(search=None, **kw) -> AIInput:
    fields = dict(session_id='S-1', inquiry_id='INQ-2026-01024', message='김민지 팀장님이 VPN이 안 된대요',
                  ask_more_count=0,
                  user_context={'employee_no': 'EMP-1123', 'service_role': 'EMPLOYEE',
                                'department_name': '영업2팀', 'pc_os': 'Windows'},
                  search=search)
    return AIInput(**(fields | kw))


def sent(mock: MockAdapter, i: int = 0) -> dict:
    return json.loads(mock.requests[i][1])


# ── 형식 (08 2장·3.3) ──────────────────────────────

def test_output_schema_requires_every_key():
    s = output_json_schema()
    assert set(s['required']) == set(AIOutput.model_fields)                   # 모든 키가 있어야 한다 (08 2.1)
    assert s['additionalProperties'] is False
    assert s['properties']['title'] == {'type': 'string'}                     # 칸 이름 title 은 남는다
    assert s['properties']['action'] == {'enum': ['ANSWER', 'ASK_MORE', 'ESCALATE', 'OUT_OF_SCOPE']}
    assert 'minimum' not in json.dumps(s)
    assert 'description' not in json.dumps(s)                                 # 코드 설명은 Claude 에 보내지 않는다


def test_safe_default_matches_doc():
    d = safe_default().model_dump()
    assert (d['action'], d['urgent_signal'], d['escalation_reason']) == ('ESCALATE', False, '전문판단')
    assert d['reply'] == '지금은 자동으로 확인하기 어려워요. 담당자에게 연결해 드릴까요?'
    assert d['facts']['work_stopped'] == 'unknown'


def test_output_keeps_unknown_enum_for_judge_flow():
    # 허용값 밖은 여기서 막지 않는다. 판단 흐름이 null 로 바꾼다 (08 3.2 4단계)
    out = AIOutput.model_validate(ANSWER | {'category_code': 'XYZ'})
    assert out.category_code == 'XYZ'


# ── 호출 흐름 ─────────────────────────────────────

def test_success_returns_output_and_call_record():
    mock = MockAdapter([ANSWER_JSON])
    r = call_judge(inp(), mock, TAXONOMY, ['김민지'], 'CLASSIFY')
    assert (r.failure, r.error_code) == (None, None)
    assert r.output.action == 'ANSWER'
    assert r.ai_output == ANSWER
    (c,) = r.calls
    assert (c.purpose, c.adapter, c.model, c.success, c.error_code) == ('CLASSIFY', 'Mock', 'mock', True, None)


def test_pseudonymized_in_order_and_server_only_fields_not_sent():
    mock = MockAdapter([ANSWER_JSON])
    facts = {**ANSWER['facts'], 'summary': '박서준 님 VPN 오류', 'tried_actions': ['박서준 님께 문의']}
    call_judge(inp(history=[{'role': 'user', 'content': '박서준 님 대신 문의해요'}], collected_facts=facts,
                   prior_urgent_signal=True), mock, TAXONOMY, ['김민지', '박서준'], 'CLASSIFY')
    body = sent(mock)
    # 이전 대화 → 모은 사실 → 이번 글 순서로 번호를 매긴다
    assert body['history'][0]['content'] == '[직원1] 님 대신 문의해요'
    assert body['collected_facts']['summary'] == '[직원1] 님 VPN 오류'
    assert body['collected_facts']['tried_actions'] == ['[직원1] 님께 문의']
    assert body['message'] == '[직원2] 팀장님이 VPN이 안 된대요'
    raw = mock.requests[0][1]
    for server_only in ('EMP-1123', 'employee_no', 'prior_urgent_signal', 'session_id', 'INQ-2026-01024'):
        assert server_only not in raw
    assert body['search'] is None


def test_search_is_filtered_and_server_only_fields_not_sent():
    mock = MockAdapter([ANSWER_JSON])
    search = SearchResponse(query='VPN', model='kure', threshold=0.5, documents=(doc(),), legacy=(case(),))
    r = call_judge(inp(search=search), mock, TAXONOMY, ['김민지'], 'ANSWER')
    body = sent(mock)
    (d,) = body['search']['documents']
    assert d['text'].endswith('김민지 담당 010-1234-5678')                 # ALLOWED 는 그대로
    assert d['handling'] == '사용자 직접 조치'
    assert body['search']['legacy'][0]['legacy_no'] == 'INQ-2026-00245'
    for server_only in ('transfer_policy', 'view_scope', 'sufficient', 'citation', 'chunks', 'legacy_inquiry_id'):
        assert server_only not in mock.requests[0][1]
    assert r.evidence.documents == (doc(),)                                  # 8단계 검사에 쓸 보낸 근거


def test_retry_once_on_bad_json_then_succeed():
    mock = MockAdapter(['{not json', ANSWER_JSON])
    r = call_judge(inp(), mock, TAXONOMY, [], 'CLASSIFY')
    assert r.failure is None
    assert [(c.success, c.error_code) for c in r.calls] == [(False, 'INVALID_JSON'), (True, None)]


def test_two_bad_outputs_use_safe_default():
    missing_key = json.dumps({k: v for k, v in ANSWER.items() if k != 'facts'})
    r = call_judge(inp(), MockAdapter([missing_key]), TAXONOMY, [], 'CLASSIFY')
    assert (r.failure, r.error_code, r.ai_output) == ('AI_FAILED', 'SCHEMA_INVALID', None)
    assert r.output == safe_default()
    assert len(r.calls) == 2


def test_missing_version_is_schema_error_and_retried():
    no_version = json.dumps({k: v for k, v in ANSWER.items() if k != 'schema_version'})
    r = call_judge(inp(), MockAdapter([no_version, ANSWER_JSON]), TAXONOMY, [], 'CLASSIFY')
    assert r.failure is None
    assert [c.error_code for c in r.calls] == ['SCHEMA_INVALID', None]


def test_unsupported_version_is_not_retried():
    r = call_judge(inp(), MockAdapter([json.dumps(ANSWER | {'schema_version': '2.0'})]), TAXONOMY, [], 'CLASSIFY')
    assert (r.failure, r.error_code, len(r.calls)) == ('AI_FAILED', 'UNSUPPORTED_VERSION', 1)


def test_api_error_is_not_retried():
    # SDK 가 연결 오류·429·5xx 를 이미 다시 시도했으므로 여기서는 다시 부르지 않는다
    r = call_judge(inp(), MockAdapter([LLMError('TIMEOUT')]), TAXONOMY, [], 'CLASSIFY')
    assert (r.failure, r.error_code) == ('AI_FAILED', 'TIMEOUT')
    assert [(c.success, c.error_code) for c in r.calls] == [(False, 'TIMEOUT')]


def test_all_blocked_does_not_call():
    mock = MockAdapter([ANSWER_JSON])
    search = SearchResponse(query='VPN', model='kure', threshold=0.5, documents=(doc(policy='BLOCKED'),))
    r = call_judge(inp(search=search), mock, TAXONOMY, [], 'ANSWER')
    assert mock.requests == []
    assert (r.failure, r.output.escalation_reason, r.ai_output, r.calls) == ('ALL_BLOCKED', '전송제한', None, ())
    assert r.evidence.blocked == ('IT-NET-001',)


def test_no_results_is_not_all_blocked():
    mock = MockAdapter([ANSWER_JSON])
    r = call_judge(inp(search=SearchResponse(query='VPN', model='kure', threshold=0.5)), mock, TAXONOMY, [], 'ANSWER')
    assert r.failure is None and len(mock.requests) == 1                     # 근거부족은 판단 흐름이 정한다


def test_filter_error_does_not_call(monkeypatch):
    def broken(self, text):
        raise RuntimeError('boom')
    monkeypatch.setattr(call_module.Pseudonymizer, 'apply', broken)
    mock = MockAdapter([ANSWER_JSON])
    r = call_judge(inp(), mock, TAXONOMY, ['김민지'], 'CLASSIFY')
    assert mock.requests == []
    assert (r.failure, r.error_code, r.output.action) == ('AI_FAILED', 'FILTER_FAILED', 'ESCALATE')


def test_system_prompt_has_taxonomy_and_is_stable():
    s = build_system_prompt(TAXONOMY)
    assert '- NET-02 | 개인 VPN 접속 장애 | INCIDENT | P3' in s
    assert '- NET VPN·네트워크: 사내 Wi-Fi, VPN 장애' in s
    reordered = Taxonomy(TAXONOMY.categories, tuple(reversed(TAXONOMY.types)))
    assert build_system_prompt(reordered) == s                               # 같아야 캐시가 맞는다


# ── Claude Adapter (가짜 client) ───────────────────

class FakeClient:
    def __init__(self, result):
        self.result, self.kwargs = result, None
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def response(text=ANSWER_JSON, stop_reason='end_turn'):
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0,
                            cache_read_input_tokens=900)
    return SimpleNamespace(model='claude-sonnet-5-5', stop_reason=stop_reason, usage=usage,
                           content=[SimpleNamespace(type='thinking'), SimpleNamespace(type='text', text=text)])


def test_claude_adapter_request_and_reply():
    client = FakeClient(response())
    reply = ClaudeAdapter('key', 'claude-sonnet-5-5', client=client).complete('시스템', '사용자', {'type': 'object'})
    assert (reply.text, reply.model, reply.input_tokens, reply.output_tokens) == \
        (ANSWER_JSON, 'claude-sonnet-5-5', 1000, 50)
    k = client.kwargs
    assert k['output_config'] == {'format': {'type': 'json_schema', 'schema': {'type': 'object'}}}
    assert k['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert k['messages'] == [{'role': 'user', 'content': '사용자'}]
    assert 'fallbacks' not in k and 'betas' not in k          # 거절되면 다른 모델로 넘기지 않는다


def test_claude_adapter_time_limit():
    # 한 번 30초, 넘으면 1번 더 (최악 약 1분)
    client = ClaudeAdapter('key', 'claude-sonnet-5-5')._client
    assert (client.timeout, client.max_retries) == (30.0, 1)


@pytest.mark.parametrize('stop_reason, code', [('refusal', 'REFUSAL'), ('max_tokens', 'MAX_TOKENS')])
def test_claude_adapter_stop_reasons(stop_reason, code):
    with pytest.raises(LLMError) as e:
        ClaudeAdapter('key', 'claude-sonnet-5-5', client=FakeClient(response(stop_reason=stop_reason))) \
            .complete('s', 'u', {})
    assert (e.value.code, e.value.input_tokens) == (code, 1000)


def test_claude_adapter_errors():
    req = httpx2.Request('POST', 'https://api.anthropic.com/v1/messages')
    cases = [
        (anthropic.APITimeoutError(request=req), 'TIMEOUT'),
        (anthropic.APIConnectionError(request=req), 'CONNECTION'),
        (anthropic.RateLimitError('429', response=httpx2.Response(429, request=req), body=None), 'RATE_LIMIT'),
        (anthropic.InternalServerError('500', response=httpx2.Response(500, request=req), body=None), 'HTTP_500'),
    ]
    for error, code in cases:
        with pytest.raises(LLMError) as e:
            ClaudeAdapter('key', 'claude-sonnet-5-5', client=FakeClient(error)).complete('s', 'u', {})
        assert e.value.code == code


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    llm_config.get_llm_adapter.cache_clear()
    with pytest.raises(RuntimeError, match='LLM_API_KEY'):
        llm_config.get_llm_adapter()


def test_default_model(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.delenv('LLM_MODEL', raising=False)
    llm_config.get_llm_adapter.cache_clear()
    try:
        assert llm_config.get_llm_adapter().model == 'claude-sonnet-5-5'
    finally:
        llm_config.get_llm_adapter.cache_clear()
