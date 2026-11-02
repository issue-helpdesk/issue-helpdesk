"""판단 흐름 (M4-2-1) 테스트. 기준은 docs/09 4.1, docs/08 3.2·5.4. Mock 모델과 가짜 검색으로 돌린다 (DB·API 키 없음)."""
import json

from app.agent.flow import build_flow, run_flow
from app.agent.llm import LLMError, MockAdapter, safe_default
from app.rag.search import ChunkHit, DocumentResult, LegacyResult, SearchResponse

from test_flow_correct import FACTS, QUOTE, TAXONOMY, inp

DOC = DocumentResult(unit_key='IT-NET-001@v2.0/item:3.1', chunk_type='ITEM', doc_code='IT-NET-001', title='VPN 가이드',
                     version='v2.0', location='3.1', heading_path='3. 조치 > 3.1', text=f'원인: {QUOTE}.',
                     chunks=(ChunkHit(412, 1, 0.86), ChunkHit(413, 2)), unit_score=0.86, score_type='cosine:kure',
                     view_scope='ALL', transfer_policy='ALLOWED')
SECRET_DOC = DocumentResult(unit_key='IT-SEC-009@v1.0/item:2', chunk_type='ITEM', doc_code='IT-SEC-009', title='보안',
                            version='v1.0', location='2', heading_path='2', text='내부 대응 절차',
                            chunks=(ChunkHit(900, 1, 0.9),), unit_score=0.9, score_type='cosine:kure',
                            view_scope='ALL', transfer_policy='BLOCKED')


def reply(action='ANSWER', **kw) -> str:
    d = {'schema_version': '1.0', 'action': action, 'urgent_signal': False, 'title': 'VPN 연결 오류',
         'category_code': 'NET', 'inquiry_type_code': 'NET-02', 'request_kind': 'INCIDENT', 'urgency_suggested': 'P3',
         'facts': FACTS, 'rationale': {'category': '', 'urgency_reasons': [], 'action': ''},
         'reply': 'VPN 클라이언트를 업데이트해 보세요.', 'evidence': [], 'missing_items': [],
         'escalation_reason': None, 'confidence': 0.8}
    return json.dumps(d | kw, ensure_ascii=False)


ANSWERED = reply(evidence=[{'kind': 'DOCUMENT', 'source_id': DOC.unit_key, 'quote': QUOTE}])


class FakeSearch:
    """검색 대신 정해 둔 결과를 돌려주고, 받은 요청을 남긴다."""
    def __init__(self, *documents):
        self.documents = documents or (DOC,)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        return SearchResponse(query=req.query, model='kure', threshold=0.6, documents=self.documents)


def run(replies, search=None, **inp_kw):
    mock, search = MockAdapter(replies), search or FakeSearch()
    return run_flow(inp(**inp_kw), mock, TAXONOMY, ['김민지'], search), mock, search


def purposes(r) -> list[str]:
    return [c.purpose for c in r.llm_calls]


def test_answer_goes_through_search_and_second_judge():
    r, mock, search = run([reply(), ANSWERED], history=[{'role': 'user', 'content': '재택 중이에요'},
                                                        {'role': 'assistant', 'content': '어떤 오류인가요?'}])
    assert (r.next_step, r.output.action, r.urgency, r.failure) == ('answered', 'ANSWER', 'P3', None)
    assert purposes(r) == ['CLASSIFY', 'ANSWER']
    assert search.requests[0].query == '재택 중이에요\nVPN이 안 돼요'          # 사용자 글만 이어 붙인다
    assert search.requests[0].category_code is None                     # 1차 분류로 좁히지 않는다
    assert json.loads(mock.requests[0][1])['search'] is None
    assert json.loads(mock.requests[1][1])['search']['documents'][0]['unit_key'] == DOC.unit_key
    assert r.ai_output['evidence'][0]['quote'] == QUOTE                  # 최종(2차) 판단의 원본
    assert [(s['chunk_id'], s['rank']) for s in r.sources] == [(412, 1), (413, 1)]
    assert r.override_reasons == ()


def test_urgent_signal_skips_search():
    urgent = reply('ESCALATE', urgent_signal=True, escalation_reason='긴급대응', category_code='SEC',
                   inquiry_type_code='SEC-06', facts=FACTS | {'security_suspected': True})
    r, _, search = run([urgent])
    assert (r.next_step, r.output.urgent_signal, r.urgency) == ('offer', True, 'P2')
    assert search.requests == []
    assert purposes(r) == ['CLASSIFY']
    assert r.sources == () and r.evidence is None


def test_ask_more_stays_in_collect():
    r, _, search = run([reply('ASK_MORE', missing_items=['symptom'], reply='어떤 오류 문구가 보이나요?')],
                       collected_facts=FACTS | {'symptom': None})
    assert (r.next_step, r.output.missing_items) == ('collect', ['symptom'])
    assert search.requests == []


def test_ask_more_limit_offers_without_search():
    r, _, search = run([reply('ASK_MORE', missing_items=['symptom'])], collected_facts=FACTS | {'symptom': None},
                       ask_more_count=2, ask_more_unanswered_count=2)
    assert (r.next_step, r.output.escalation_reason) == ('offer', '전문판단')
    assert [o['rule'] for o in r.override_reasons][0] == 'ASK_MORE_UNANSWERED'
    assert search.requests == []


def test_first_escalate_still_searches():
    # 1차 ESCALATE(긴급 아님)는 검색 후 2차로 판단한다 (09 4.1 "그 밖")
    r, _, search = run([reply('ESCALATE', escalation_reason='권한변경'), ANSWERED])
    assert len(search.requests) == 1
    assert r.next_step == 'answered'


def test_second_without_evidence_offers():
    r, _, _ = run([reply(), reply()])
    assert (r.next_step, r.output.escalation_reason) == ('offer', '근거부족')
    assert [o['rule'] for o in r.override_reasons] == ['NO_EVIDENCE']


def test_second_ask_more_goes_back_to_collect():
    r, _, _ = run([reply(), reply('ASK_MORE', missing_items=['symptom'])], collected_facts=FACTS | {'symptom': None})
    assert r.next_step == 'collect'


def test_unsafe_reply_is_regenerated_once():
    unsafe = reply(reply='확인을 위해 비밀번호를 알려 주세요.')
    r, _, _ = run([reply(), unsafe, ANSWERED])
    assert purposes(r) == ['CLASSIFY', 'ANSWER', 'ANSWER']
    assert (r.next_step, r.failure, r.output.reply) == ('answered', None, 'VPN 클라이언트를 업데이트해 보세요.')


def test_unsafe_first_reply_is_checked_only_when_shown():
    unsafe = '확인을 위해 비밀번호를 알려 주세요.'
    r, _, _ = run([reply(reply=unsafe), ANSWERED])                       # 검색으로 넘어가 보여 주지 않음
    assert purposes(r) == ['CLASSIFY', 'ANSWER']
    ask = reply('ASK_MORE', missing_items=['symptom'], reply=unsafe)     # 1차에서 끝나 보여 줌
    r, _, _ = run([ask, reply('ASK_MORE', missing_items=['symptom'])], collected_facts=FACTS | {'symptom': None})
    assert purposes(r) == ['CLASSIFY', 'CLASSIFY']
    assert (r.next_step, r.failure) == ('collect', None)


def test_unsafe_reply_twice_uses_safe_default():
    unsafe = reply(reply='확인을 위해 비밀번호를 알려 주세요.')
    r, _, search = run([reply(), unsafe, unsafe])
    assert purposes(r) == ['CLASSIFY', 'ANSWER', 'ANSWER']
    assert (r.next_step, r.failure, r.error_code, r.ai_output) == ('offer', 'AI_FAILED', 'UNSAFE_REPLY', None)
    assert r.output.reply == safe_default().reply
    assert r.override_reasons[0] == {'field': 'action', 'ai': None, 'final': 'ESCALATE', 'rule': 'AI_FAILED',
                                     'reason': 'UNSAFE_REPLY'}


ASKS_BACK = '화면 메시지와 접속 장소를 알려주세요, 담당자에게 연결해 드릴까요?'
EVIDENCE = [{'kind': 'DOCUMENT', 'source_id': DOC.unit_key, 'quote': QUOTE}]


def test_answer_asking_back_is_regenerated_once():
    asking = reply(reply=f'VPN 클라이언트를 업데이트해 보세요. {ASKS_BACK}', evidence=EVIDENCE)
    r, _, _ = run([reply(), asking, ANSWERED])
    assert purposes(r) == ['CLASSIFY', 'ANSWER', 'ANSWER']
    assert (r.next_step, r.output.reply, r.override_reasons) == ('answered', 'VPN 클라이언트를 업데이트해 보세요.', ())


def test_answer_asking_back_twice_drops_the_sentence():
    asking = reply(reply=f'VPN 클라이언트를 업데이트해 보세요. {ASKS_BACK}', evidence=EVIDENCE)
    r, _, _ = run([reply(), asking, asking])
    assert (r.next_step, r.failure, r.output.action) == ('answered', None, 'ANSWER')
    assert r.output.reply == 'VPN 클라이언트를 업데이트해 보세요.'
    assert r.ai_output['reply'].endswith(ASKS_BACK)                      # 원본은 그대로 남긴다
    assert r.override_reasons == ({'field': 'reply', 'ai': f'VPN 클라이언트를 업데이트해 보세요. {ASKS_BACK}',
                                   'final': 'VPN 클라이언트를 업데이트해 보세요.', 'rule': 'ANSWER_ASKS_BACK',
                                   'reason': '답변 뒤 답할 수 없는 연결 제안·정보 요청을 뺌'},)


def test_answer_only_asking_back_uses_safe_default():
    asking = reply(reply=ASKS_BACK, evidence=EVIDENCE)
    r, _, _ = run([reply(), asking, asking])
    assert (r.next_step, r.failure, r.error_code) == ('offer', 'AI_FAILED', 'ANSWER_ASKS_BACK')


def test_handoff_offer_is_fine_when_not_answer():
    # 근거가 없어 ESCALATE 로 바뀌면 연결 제안이 맞으므로 다시 부르지 않는다
    r, _, _ = run([reply(), reply(reply=ASKS_BACK)])
    assert purposes(r) == ['CLASSIFY', 'ANSWER']
    assert (r.next_step, r.output.reply) == ('offer', ASKS_BACK)


def test_first_failure_ends_without_search():
    r, _, search = run([LLMError('TIMEOUT')])
    assert (r.next_step, r.failure, r.error_code) == ('offer', 'AI_FAILED', 'TIMEOUT')
    assert search.requests == []
    assert (r.urgency, r.needs_triage) == ('P3', True)


def test_failure_keeps_urgent_latch_and_prior_urgency():
    r, _, _ = run([LLMError('TIMEOUT')], prior_urgent_signal=True, prior_urgency='P2')
    # 안전 기본값은 이미 ESCALATE 라 URGENT_SIGNAL 은 걸리지 않고 사유는 전문판단 그대로 (08 3.2 표)
    assert (r.output.urgent_signal, r.output.escalation_reason, r.urgency) == (True, '전문판단', 'P2')
    assert [o['rule'] for o in r.override_reasons] == ['AI_FAILED', 'URGENT_LATCH', 'URGENCY_KEEP']


def test_all_blocked_offers_without_second_call():
    r, _, _ = run([reply()], search=FakeSearch(SECRET_DOC))
    assert (r.next_step, r.failure, r.output.escalation_reason) == ('offer', 'ALL_BLOCKED', '전송제한')
    assert purposes(r) == ['CLASSIFY']                                   # 2차는 Claude 를 부르지 않는다
    assert r.evidence.blocked == ('IT-SEC-009',)
    assert r.override_reasons[0]['rule'] == 'ALL_BLOCKED'


def test_graph_is_reusable():
    flow = build_flow(MockAdapter([reply(), ANSWERED]), TAXONOMY, [], FakeSearch())
    assert set(flow.get_graph().nodes) >= {'judge_first', 'correct_first', 'search', 'judge_second',
                                           'correct_second', 'decide_urgency', 'package'}
