"""AI 출력 보정 (M4-2-1) 테스트. 기준은 docs/08 3.2 4~9단계와 처리 방향 보정. LLM 을 부르지 않는다."""
import pytest

from app.agent.flow import Limits, asks_back, correct, drop_asks_back, unsafe_reply
from app.agent.llm import AIInput, AIOutput, CategoryInfo, Taxonomy, TypeInfo
from app.agent.sensitive import Filtered
from app.rag.search import ChunkHit, DocumentResult, LegacyResult, SearchResponse

TAXONOMY = Taxonomy(
    categories=(CategoryInfo('NET', 'VPN·네트워크'), CategoryInfo('SEC', '정보보안')),
    types=(TypeInfo('NET-02', 'NET', '개인 VPN 접속 장애', 'INCIDENT', 'P3'),
           TypeInfo('SEC-06', 'SEC', '계정 도용 의심', 'INCIDENT', 'P2')),
)
FACTS = {'summary': '재택 근무 중 VPN 연결 오류', 'target_system': '사내 VPN', 'symptom': '연결 오류',
         'occurred_at': None, 'impact_scope': 'PERSONAL', 'work_stopped': 'partial', 'has_workaround': None,
         'time_constraint': None, 'business_impact': None, 'security_suspected': False, 'tried_actions': []}
QUOTE = 'VPN 클라이언트가 구버전입니다'
DOC = DocumentResult(unit_key='IT-NET-001@v2.0/item:3.1', chunk_type='ITEM', doc_code='IT-NET-001', title='VPN 가이드',
                     version='v2.0', location='3.1', heading_path='3. 조치 > 3.1', text=f'원인: {QUOTE}.',
                     chunks=(ChunkHit(412, 1, 0.86),), unit_score=0.86, score_type='cosine:kure', view_scope='ALL',
                     transfer_policy='ALLOWED')
CASE = LegacyResult(legacy_inquiry_id=1, legacy_no='INQ-2026-00245', inquiry_type_code='NET-02', title='VPN 오류',
                    text='VPN 오류 / 구버전 / 재설치', root_cause='구버전', resolution='재설치', resolved_at=None,
                    score=0.6, score_type='cosine:kure', view_scope='ALL', transfer_policy='ALLOWED')
SENT = Filtered((DOC,), (CASE,))
DOC_EVIDENCE = {'kind': 'DOCUMENT', 'source_id': DOC.unit_key, 'quote': QUOTE}


def out(**kw) -> AIOutput:
    d = {'schema_version': '1.0', 'action': 'ANSWER', 'urgent_signal': False, 'title': 'VPN 연결 오류',
         'category_code': 'NET', 'inquiry_type_code': 'NET-02', 'request_kind': 'INCIDENT', 'urgency_suggested': 'P3',
         'facts': FACTS, 'rationale': {'category': '', 'urgency_reasons': [], 'action': ''},
         'reply': 'VPN 클라이언트를 업데이트해 보세요.', 'evidence': [DOC_EVIDENCE], 'missing_items': [],
         'escalation_reason': None, 'confidence': 0.8}
    return AIOutput.model_validate(d | kw)


def inp(**kw) -> AIInput:
    return AIInput(**({'session_id': 'S-1', 'inquiry_id': 'INQ-1', 'message': 'VPN이 안 돼요', 'ask_more_count': 0,
                       'user_context': {'employee_no': 'EMP-1123', 'service_role': 'EMPLOYEE'}, 'search': None} | kw))


def search(score=0.86) -> SearchResponse:
    return SearchResponse(query='VPN', model='kure', threshold=0.6, documents=(DOC,) if score else (), legacy=(CASE,))


def second(o, i=None, s=None, sent=SENT, **kw):
    return correct(o, i or inp(), second=True, sent=sent, search=s or search(), taxonomy=TAXONOMY, **kw)


def first(o, i=None, **kw):
    return correct(o, i or inp(), second=False, sent=None, search=None, taxonomy=TAXONOMY, **kw)


def rules(c) -> list[str]:
    return [o['rule'] for o in c.overrides]


def test_valid_answer_is_unchanged():
    c = second(out())
    assert c.output == out()
    assert c.overrides == ()


# ── 4·5단계 ─────────────────────────────────────

def test_unknown_values_become_null():
    c = second(out(category_code='XYZ', request_kind='BUG', urgency_suggested='P0',
                   facts=FACTS | {'impact_scope': 'TEAM', 'work_stopped': 'half'}))
    o = c.output
    assert (o.category_code, o.request_kind, o.urgency_suggested) == (None, None, None)
    assert (o.facts.impact_scope, o.facts.work_stopped) == (None, 'unknown')
    assert {x['field'] for x in c.overrides if x['rule'] == 'INVALID_VALUE'} >= {
        'category_code', 'request_kind', 'urgency_suggested', 'facts.impact_scope', 'facts.work_stopped'}


def test_unknown_action_becomes_escalate():
    c = second(out(action='CLOSE'))
    assert (c.output.action, c.output.escalation_reason) == ('ESCALATE', '전문판단')
    assert c.overrides[0] == {'field': 'action', 'ai': 'CLOSE', 'final': 'ESCALATE', 'rule': 'INVALID_VALUE',
                              'reason': '허용값 밖의 처리 방향'}


def test_list_fields_drop_only_unknown_items():
    c = second(out(evidence=[DOC_EVIDENCE, {'kind': 'WEB', 'source_id': 'x', 'quote': 'y'}]))
    assert len(c.output.evidence) == 1


@pytest.mark.parametrize('kw', [{'inquiry_type_code': 'NET-99'}, {'inquiry_type_code': 'SEC-06'}])
def test_type_code_mismatch_keeps_category(kw):
    c = second(out(**kw))
    assert (c.output.inquiry_type_code, c.output.category_code) == (None, 'NET')
    assert rules(c) == ['TYPE_CODE_MISMATCH']


# ── 6·7·8단계 ───────────────────────────────────

def test_missing_items_drop_known_and_later_items():
    i = inp(collected_facts={**FACTS, 'symptom': None})
    c = first(out(action='ASK_MORE', evidence=[],
                  missing_items=['target_system', 'symptom', 'occurred_at', 'tried_actions', 'impact', 'symptom']), i)
    assert c.output.missing_items == ['symptom']                      # 대상 시스템·영향은 이미 앎


def test_empty_title_is_filled_from_summary_and_cut():
    c = second(out(title='  '))
    assert c.output.title == FACTS['summary']
    assert second(out(title='VPN 오류 ')).overrides == ()              # 앞뒤 공백만으로는 바꾸지 않는다
    assert second(out(title='가' * 300)).output.title == '가' * 255


def test_evidence_must_be_in_sent_text():
    fake = {'kind': 'DOCUMENT', 'source_id': DOC.unit_key, 'quote': '지어낸 문장'}
    other = {'kind': 'DOCUMENT', 'source_id': 'IT-XXX@v1/item:1', 'quote': QUOTE}
    c = second(out(evidence=[fake, other, DOC_EVIDENCE]))
    assert [e.quote for e in c.output.evidence] == [QUOTE]


# ── 처리 방향 보정 ──────────────────────────────

def test_answer_without_evidence_escalates_only_in_second():
    c = second(out(evidence=[]))
    assert (c.output.action, c.output.escalation_reason, rules(c)) == ('ESCALATE', '근거부족', ['NO_EVIDENCE'])
    c = first(out(evidence=[]))                                       # 1차에는 근거 보정을 하지 않는다
    assert (c.output.action, c.overrides) == ('ANSWER', ())


def test_guide_insufficient_needs_legacy_evidence():
    weak = search(score=0)                                            # 가이드 결과 없음 → sufficient=False
    c = second(out(), s=weak)
    assert rules(c) == ['GUIDE_INSUFFICIENT']
    legacy = {'kind': 'LEGACY', 'source_id': CASE.legacy_no, 'quote': '구버전'}
    assert second(out(evidence=[legacy]), s=weak).output.action == 'ANSWER'     # 과거 사례로는 답할 수 있다


def test_ask_more_empty_and_limits():
    ask = out(action='ASK_MORE', evidence=[], missing_items=['occurred_at'])
    assert rules(first(ask)) == ['ASK_MORE_EMPTY']
    ask = out(action='ASK_MORE', evidence=[], missing_items=['symptom'])
    assert rules(first(ask, inp(ask_more_count=1))) == []
    assert rules(first(ask, inp(ask_more_count=2, ask_more_unanswered_count=2))) == ['ASK_MORE_UNANSWERED']
    assert rules(first(ask, inp(ask_more_count=5, ask_more_unanswered_count=1))) == ['ASK_MORE_LIMIT']
    assert rules(first(ask, inp(ask_more_count=3), limits=Limits(total=3))) == ['ASK_MORE_LIMIT']


def test_escalate_without_reason_and_reason_without_escalate():
    c = second(out(action='ESCALATE', evidence=[]))
    assert (c.output.escalation_reason, rules(c)) == ('전문판단', ['INVALID_VALUE'])
    c = second(out(escalation_reason='실제조치'))
    assert c.output.escalation_reason is None


def test_urgent_latch_then_urgent_signal():
    c = first(out(), inp(prior_urgent_signal=True))
    assert (c.output.urgent_signal, c.output.action, c.output.escalation_reason) == (True, 'ESCALATE', '긴급대응')
    assert rules(c) == ['URGENT_LATCH', 'URGENT_SIGNAL']


# ── 9단계 ───────────────────────────────────────

@pytest.mark.parametrize('reply', [
    '확인을 위해 비밀번호를 알려 주세요.',
    '문자로 받은 인증번호 6자리를 채팅에 입력해 주세요.',
    'API 키를 보내 주시면 확인해 드릴게요.',
    'API 키를 적어 주세요.',
    '인증번호 6자리를 보내주시면 확인할게요.',
    '비밀번호를 저에게 알려 주세요.',
    'OTP 앱에 표시된 번호를 알려 주세요.',
    '문의가 접수되었습니다. 곧 연락드릴게요.',
    '담당자가 배정됐어요.',
    '접수가 완료되었어요.',
    '티켓을 생성했어요.',
])
def test_unsafe_reply(reply):
    assert unsafe_reply(reply)


@pytest.mark.parametrize('reply', [
    '비밀번호는 절대 알려 주지 마세요.',
    '비밀번호 재설정 포털에서 새 비밀번호를 입력해 주세요.',
    '지금은 자동으로 확인하기 어려워요. 담당자에게 연결해 드릴까요?',
    '접수 전에 내용을 확인해 주세요.',
    '접수 전 내용을 확인했어요.',
    '파일을 암호화해서 보내 주세요.',
    '비밀번호 변경 방법을 알려 드릴게요.',
    '비밀번호 재설정 링크를 메일로 보내 드려요.',
    '휴대폰 번호가 바뀌었거나 인증번호를 받을 수 없으면 말씀해 주세요.',   # EV-001 실제 시험에서 잘못 잡힌 문장
    '휴대폰 번호가 바뀌었거나 인증번호를 받을 수 없으면 알려 주세요.',
    '인증번호가 문자로 보내지면 포털에 입력하세요.',
])
def test_safe_reply(reply):
    assert not unsafe_reply(reply)


# ── 9단계: ANSWER 답변 끝맺음 ─────────────────────

VPN_ASKS_BACK = ('VPN 클라이언트를 최신 버전으로 업데이트한 뒤 다시 연결해 보세요. '
                 '그래도 해결되지 않으면 화면에 나오는 메시지와 접속 장소를 알려주세요, 담당자에게 연결해 드릴까요?')


@pytest.mark.parametrize('reply', [
    VPN_ASKS_BACK,                                                      # API 테스트에서 나온 문장
    '해결되지 않으면 담당자에게 연결해 드릴까요?',
    '담당자 연결을 원하시면 아래 버튼을 눌러 주세요.',
    '화면 메시지를 알려 주세요.',
    '휴대폰 번호가 바뀌었거나 인증번호를 받을 수 없으면 말씀해 주세요.',
    '접속 장소를 알려주시면 확인해 볼게요.',
    '화면 메시지와 함께 접속 장소를 알려 주세요.',
])
def test_asks_back(reply):
    assert asks_back(reply)


@pytest.mark.parametrize('reply', [
    'VPN 클라이언트를 업데이트해 보세요.',
    '연결 상태로 바뀌고 그룹웨어가 열리면 해결된 거예요.',
    '이 방법으로 해결되었나요?',
    '팀장님께 승인 요청을 말씀해 주세요.',
    '보안 담당자에게 알려 주세요.',
    '신청서를 작성해 메일로 보내 주세요.',
    '비밀번호는 절대 알려 주지 마세요.',
])
def test_not_asks_back(reply):
    assert not asks_back(reply)


def test_drop_asks_back_keeps_steps():
    reply = ('아래 순서로 해 보세요.\n1. VPN 클라이언트를 업데이트합니다.\n2. 우회 포트 모드를 켭니다.\n\n'
             '연결되면 해결된 거예요. 그래도 안 되면 화면 메시지를 알려 주세요. 담당자에게 연결해 드릴까요?')
    assert drop_asks_back(reply) == ('아래 순서로 해 보세요.\n1. VPN 클라이언트를 업데이트합니다.\n2. 우회 포트 모드를 켭니다.\n\n'
                                     '연결되면 해결된 거예요.')
    assert drop_asks_back(VPN_ASKS_BACK) == 'VPN 클라이언트를 최신 버전으로 업데이트한 뒤 다시 연결해 보세요.'
