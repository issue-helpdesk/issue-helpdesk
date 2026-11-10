"""해결 사례 가이드화 묶기·초안 (app.agent.guide run_round). Mock 모델, 가짜 임베딩, 가짜 case_guide 함수, SQLite 만 쓴다.
외부로 아무것도 보내지 않는다."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent.guide import CaseFns, run_round
from app.agent.guide import draft as dr
from app.agent.guide.cluster import bundle
from app.agent.guide.judge import SYSTEM_PROMPT as JUDGE_PROMPT
from app.agent.llm.mock import MockAdapter
from app.models import (Category, DocumentVersion, GuideCluster, KnowledgeDocument, LlmCall, SupportGroup,
                        TicketGuideState)
from app.rag.case_guide import CaseGuideError
from app.rag.search.result import ChunkHit, DocumentResult, SearchResponse
from test_auth import TABLES, add_user
from test_dashboard import add_ticket
from test_inquiries import create_sqlite_tables

NOTE = '공유기의 VPN 패스스루 설정을 켜도록 안내해 해결했습니다. 사용자가 다시 연결해 정상 확인.'
TARGET_MD = ('### 3.3 집에서 VPN이 자주 끊김\n\n**문의 유형** NET-02 · **처리 구분** 🟢 사용자 직접 조치 · '
             '**담당 부서** 네트워크팀\n\n#### 이런 경우\n\n- 집에서 VPN이 끊깁니다.\n\n**해결되지 않으면**\n\n- 헬프데스크에 문의합니다.\n')


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ['categories', 'inquiry_types', 'inquiries', 'tickets',
                                           'knowledge_documents', 'document_versions', 'guide_clusters',
                                           'ticket_guide_states', 'llm_calls'])
    with Session(engine) as session:
        add_user(session, 'E0001', name='김민지')
        session.add_all([Category(code='NET', name='VPN·네트워크'), Category(code='SEC', name='보안'),
                         SupportGroup(id=1, name='네트워크팀'), SupportGroup(id=2, name='서비스데스크')])
        for code, doc_type in (('IT-NET-001', 'GUIDE'), ('IT-NET-001-M', 'MANUAL')):
            doc = KnowledgeDocument(doc_code=code, doc_type=doc_type, title=f'{code} 제목', category_code='NET',
                                    is_active=True)
            session.add(doc)
            session.flush()
            session.add(DocumentVersion(document_id=doc.id, version='v2.0', is_current=True, ingest_status='DONE',
                                        view_scope='ALL', transfer_policy='ALLOWED' if doc_type == 'GUIDE' else 'BLOCKED'))
        session.commit()
        yield session
    engine.dispose()


def ticket(db, summary='재택 VPN 연결 시 인터넷 끊김', note=NOTE, category='NET', group=1):
    t = add_ticket(db, 1, work='CLS', category=category, group=group)
    t.summary, t.symptom, t.resolution_note = summary, None, note
    db.commit()
    return t


def hit(doc_code, location, policy='ALLOWED', chunk_type='ITEM', text='본문'):
    return DocumentResult(unit_key=f'{doc_code}@v2.0/{location}', chunk_type=chunk_type, doc_code=doc_code,
                          title=doc_code, version='v2.0', location=location, heading_path=f'{location} 제목',
                          text=text, chunks=(ChunkHit(1, 1, 0.8),), unit_score=0.8, score_type='cosine:m',
                          view_scope='ALL', transfer_policy=policy)


def searcher(*hits):
    hits = hits or (hit('IT-NET-001', '3.3', text=TARGET_MD), hit('IT-NET-001', 'FAQ-007', chunk_type='FAQ'),
                    hit('IT-NET-001-M', '3.2', 'BLOCKED', text='내부 절차'))
    return lambda request: SearchResponse(query=request.query, model='m', threshold=0.5, documents=tuple(hits))


def embed(texts):
    """가짜 임베딩: VPN · Wi-Fi · 그 밖 세 방향. 같은 주제는 점수 1, 다른 주제는 0."""
    return [[1.0 if 'VPN' in t else 0.0, 1.0 if 'Wi-Fi' in t else 0.0, 0.0 if ('VPN' in t or 'Wi-Fi' in t) else 1.0]
            for t in texts]


def judged(judgment, doc=None, item=None, handling='AGENT', reason='가이드에 공유기 설정이 없음'):
    return json.dumps({'judgment': judgment, 'reason': reason, 'target_doc': doc, 'target_item': item,
                       'handling': handling})


def drafted(**kw):
    out = {'form': 'TROUBLESHOOT', 'title': 'VPN을 연결하면 인터넷이 끊길 때',
           'body': '#### 이런 경우\n\n- VPN을 연결하면 인터넷이 끊깁니다.\n\n#### 조치 방법\n\n1. 공유기 설정을 확인합니다.\n'
                   '2. 네트워크팀이 설정 방법을 안내합니다.\n\n**해결 확인**\n\n- 인터넷이 열리면 해결된 것입니다.',
           'guide_title': None, 'change_note': None, 'manual_note': None, 'ask_info': ['사번', '공유기 모델'],
           'related_faq': ['FAQ-007'], 'differences': [], 'guessed': ['원인']}
    return json.dumps(out | kw)


def model(judge_reply, *draft_replies):
    """판단 프롬프트면 판단 응답, 초안 프롬프트면 초안 응답을 차례로."""
    drafts = list(draft_replies)

    def reply(system, user):
        if system == JUDGE_PROMPT:
            return judge_reply
        return drafts.pop(0) if len(drafts) > 1 else drafts[0]
    return MockAdapter([reply])


class Case:
    """가짜 case_guide 함수. 받은 인자를 남긴다."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def open_basis(self, judgment, **kw):
        self.calls.append((judgment, kw))
        if self.fail:
            raise CaseGuideError(['현행 없음'])
        if judgment == 'NEW_GUIDE':
            return {'draft_basis': {'judgment': judgment, 'base_version_id': None, 'category_code': kw['category_code']},
                    'draft_md': f"---\nversion: v1.0\n---\n# {kw['title']}\n\n## 3. 항목\n\n{kw['fragments'][0]}",
                    'warnings': ['뼈대 경고']}
        basis = {'judgment': judgment, 'base_version_id': 1, 'base_md': '...'}
        if judgment == 'CHANGE':
            basis |= {'target_section': kw['target_section'], 'target_md': TARGET_MD}
        return {'draft_basis': basis, 'draft_md': None, 'warnings': []}

    def fns(self):
        return CaseFns(open_basis=self.open_basis,
                       ticket_warnings=lambda ids: [f'{i}: 짧은 처리' for i in ids])


def go(db, port, case=None, search=None):
    return run_round(db, port, search or searcher(), embed, (case or Case()).fns())


def clusters(db):
    return db.scalars(select(GuideCluster).order_by(GuideCluster.id)).all()


def state(db, t):
    return db.get(TicketGuideState, t.id)


def draft_requests(port):
    return [json.loads(u) for s, u in port.requests if s == dr.SYSTEM_PROMPT]


# ── 묶기 ─────────────────────────────────────────────────

def test_similar_tickets_become_one_cluster_with_one_call(db):
    a, b = ticket(db, '재택 VPN 연결 시 인터넷 끊김 (김민지 010-1234-5678)'), ticket(db, 'VPN 붙이면 인터넷 안 됨')
    port = model(judged('ADD_ITEM', 'IT-NET-001'), drafted())
    judged_run, run = go(db, port)

    c = clusters(db)[0]
    assert (run.created, len(clusters(db)), len(draft_requests(port))) == (1, 1, 1)
    assert (c.judgment, c.status, c.title, c.target_document_id, c.base_version_id) == \
        ('ADD_ITEM', 'REVIEWING', 'VPN을 연결하면 인터넷이 끊길 때', 1, 1)
    assert [state(db, t).status for t in (a, b)] == ['REVIEWING', 'REVIEWING']
    assert {state(db, t).cluster_id for t in (a, b)} == {c.id}
    sent = draft_requests(port)[0]
    assert len(sent['tickets']) == 2 and sent['guide'] == {'doc_code': 'IT-NET-001', 'title': 'IT-NET-001 제목'}
    assert '김민지' not in json.dumps(sent, ensure_ascii=False) and '[직원1]' in sent['tickets'][0]['summary']
    manual = [i for i in sent['similar_items'] if i['doc_type'] == 'MANUAL'][0]
    assert (manual['content'], manual['content_hidden']) == (None, True)          # 판단 때와 같은 정책
    assert db.scalars(select(LlmCall).where(LlmCall.purpose == 'GUIDE_DRAFT')).one().success


def test_fragment_is_assembled_by_server(db):
    ticket(db)
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    md = clusters(db)[0].draft_md
    assert md.startswith('### 3.N VPN을 연결하면 인터넷이 끊길 때\n\n'
                         '**처리 구분** 🔵 IT 담당자 처리 · **담당 부서** 네트워크팀 · **관련 FAQ** FAQ-007\n\n#### 이런 경우')
    assert md.index('**해결 확인**') < md.index('**해결되지 않으면**') < md.index('**문의 시 알려 주실 정보**')
    assert '네트워크팀이 확인합니다' in md and '- 공유기 모델' in md


def test_request_form_has_no_unresolved_paragraph(db):
    ticket(db)
    go(db, model(judged('ADD_ITEM', 'IT-NET-001', handling='APPROVAL'),
                 drafted(form='REQUEST', ask_info=[], body='#### 이럴 때 신청합니다\n\n- 공용 메일이 필요할 때')))
    md = clusters(db)[0].draft_md
    assert '**해결되지 않으면**' not in md and '🟡 신청·승인 후 처리' in md


def test_server_paragraphs_not_doubled(db):
    ticket(db)
    body = '#### 이런 경우\n\n- 끊김\n\n**해결되지 않으면**\n\n- 문의합니다\n\n**문의 시 알려 주실 정보**\n\n- 사번'
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted(body=body)))
    md = clusters(db)[0].draft_md
    assert (md.count('**해결되지 않으면**'), md.count('**문의 시 알려 주실 정보**')) == (1, 1)


def test_different_topics_become_two_clusters(db):
    ticket(db, 'VPN 끊김'), ticket(db, '사내 Wi-Fi 인증서 오류')
    port = model(judged('ADD_ITEM', 'IT-NET-001'), drafted())
    _, run = go(db, port)
    assert (run.created, len(draft_requests(port))) == (2, 2)


def test_bundle_order_and_threshold():
    assert bundle([[1, 0], [0, 1], [1, 0.1]]) == [[0, 2], [1]]
    assert bundle([[1, 0], [1, 0.9]], threshold=0.75) == [[0], [1]]          # 코사인 약 0.74


def test_reviewing_cluster_gets_new_evidence_without_ai(db):
    old = ticket(db, 'VPN 끊김')
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    new = ticket(db, 'VPN 연결 후 인터넷 안 됨')
    port = model(judged('ADD_ITEM', 'IT-NET-001'), drafted())
    _, run = go(db, port)
    c = clusters(db)[0]
    assert (run.attached, len(clusters(db)), draft_requests(port)) == (1, 1, [])
    assert state(db, new).cluster_id == c.id == state(db, old).cluster_id
    assert f'{new.id}: 짧은 처리' in c.review_info['warnings']


def test_registered_cluster_makes_ticket_wait(db):
    ticket(db, 'VPN 끊김')
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    clusters(db)[0].registered_version_id = 1
    db.commit()
    new = ticket(db, 'VPN 연결 후 인터넷 안 됨')
    _, run = go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    assert (run.waiting, state(db, new).status, state(db, new).cluster_id) == (1, 'WAITING', None)


def test_rejected_topic_is_marked_on_new_cluster(db):
    ticket(db, 'VPN 끊김')
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    old = clusters(db)[0]
    old.status, old.reject_reason = 'REJECTED', '일회성 조치'
    db.commit()
    ticket(db, 'VPN 연결 후 인터넷 안 됨')
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    new = clusters(db)[1]
    assert new.review_info['rejected_before'] == {'cluster_id': old.id, 'reject_reason': '일회성 조치'}
    assert new.review_info['warnings'][0].startswith(f'이전에 거절된 주제입니다 (묶음 {old.id})')


def test_other_target_document_is_not_matched(db):
    """항목 추가는 넣을 문서가 같아야 같은 그룹이다."""
    ticket(db, 'VPN 끊김')
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    ticket(db, 'VPN 연결 후 인터넷 안 됨')
    _, run = go(db, model(judged('NEW_GUIDE'), drafted(guide_title='VPN 새 가이드')))
    assert (run.created, run.attached) == (1, 0)


# ── 판단별 ───────────────────────────────────────────────

def test_change_keeps_number_and_header_and_sends_body_only(db):
    t = ticket(db)
    case = Case()
    port = model(judged('CHANGE', 'IT-NET-001', '3.3'),
                 drafted(change_note='공유기 설정 단계를 더함', ask_info=['무시됨'], title='집에서 VPN이 자주 끊김'))
    go(db, port, case)
    c = clusters(db)[0]
    assert case.calls[0] == ('CHANGE', {'document_id': 1, 'receipts_': [t.receipt_no], 'target_section': '3.3'})
    assert c.draft_md.startswith('### 3.3 집에서 VPN이 자주 끊김\n\n**문의 유형** NET-02 · **처리 구분** 🟢 사용자 직접 조치')
    assert '**문의 시 알려 주실 정보**' not in c.draft_md                      # 변경은 ask_info 를 비운다
    sent = draft_requests(port)[0]['target_item']
    assert sent.startswith('#### 이런 경우') and '### 3.3' not in sent and '**문의 유형**' not in sent
    assert c.review_info['change_note'] == '공유기 설정 단계를 더함'


def test_change_of_masked_item_does_not_call_ai(db):
    t = ticket(db)
    port = model(judged('CHANGE', 'IT-NET-001', '3.3'), drafted())
    go(db, port, search=searcher(hit('IT-NET-001', '3.3', 'MASKED', text=TARGET_MD)))
    c = clusters(db)[0]
    assert (draft_requests(port), c.draft_md, c.title) == ([], TARGET_MD, '집에서 VPN이 자주 끊김')
    assert any('외부 전송이 허용되지 않아' in w for w in c.review_info['warnings'])
    assert state(db, t).status == 'REVIEWING'


def test_new_guide_uses_skeleton(db):
    ticket(db)
    case = Case()
    go(db, model(judged('NEW_GUIDE'), drafted(guide_title='VPN 새 가이드')), case)
    c = clusters(db)[0]
    judgment, kw = case.calls[0]
    assert (judgment, kw['category_code'], kw['title'], kw['fragments'][0].startswith('### 3.N ')) == \
        ('NEW_GUIDE', 'NET', 'VPN 새 가이드', True)
    assert c.draft_md.startswith('---\nversion: v1.0') and c.target_document_id is None
    assert '뼈대 경고' in c.review_info['warnings'] and c.review_info['guide_title'] == 'VPN 새 가이드'


def test_manual_candidate_has_note_and_manual_titles_only(db):
    t = ticket(db)
    go(db, model(judged('MANUAL_CANDIDATE'), drafted(manual_note='담당자 확인 절차 요약', title='무시', body='무시')))
    c = clusters(db)[0]
    assert (c.draft_md, c.draft_basis, c.title) == (None, None, t.summary)
    assert c.review_info['manual_note'] == '담당자 확인 절차 요약'
    assert c.review_info['manual_items'] == ['IT-NET-001-M 3.2 3.2 제목']


# ── 검사와 실패 ──────────────────────────────────────────

@pytest.mark.parametrize('bad, code', [
    (drafted(body='#### 이런 경우\n\n- [직원1] 님이 끊김'), 'INVALID_CONTENT'),
    (drafted(body='#### 이런 경우\n\n- 비밀번호 ●●●●●● 입력'), 'INVALID_CONTENT'),
    (drafted(body='### 다른 제목\n\n본문'), 'INVALID_FORMAT'),
    (drafted(body='#### 이런 경우\n\n```\n안 닫힌 코드'), 'INVALID_FORMAT'),
    (drafted(related_faq=['FAQ-999']), 'INVALID_REFERENCE'),
    (drafted(title=None), 'SCHEMA_INVALID'),
    ('not json', 'INVALID_JSON'),
])
def test_bad_output_retried_then_ticket_unchanged(db, bad, code):
    t = ticket(db)
    port = model(judged('ADD_ITEM', 'IT-NET-001'), bad)
    _, run = go(db, port)
    s = state(db, t)
    assert (run.failed, clusters(db), len(draft_requests(port))) == (1, [], 2)
    assert (s.status, s.cluster_id, s.fail_code, s.fail_count) == (None, None, code, 1)


def test_tags_allowed_in_admin_only_note(db):
    """manual_note 는 관리자만 본다. 치환 표시가 있어도 실패로 보지 않는다."""
    ticket(db)
    _, run = go(db, model(judged('MANUAL_CANDIDATE'), drafted(manual_note='[직원1] 님 계정은 담당자가 확인')))
    assert run.created == 1


def test_new_guide_sensitive_check_skips_skeleton_contacts(db):
    """뼈대에 복사된 공식 연락처(6장)는 경고하지 않고, AI 조각에서 온 줄만 본다."""
    ticket(db)

    class WithContacts(Case):
        def open_basis(self, judgment, **kw):
            out = super().open_basis(judgment, **kw)
            out['draft_md'] += '\n## 6. 문의처\n\n| IT 헬프데스크 | 02-1234-5678 |\n'
            return out
    go(db, model(judged('NEW_GUIDE'), drafted(guide_title='VPN 새 가이드')), WithContacts())
    assert not any('개인정보' in w for w in clusters(db)[0].review_info['warnings'])


def test_receipt_number_in_body_is_rejected(db):
    t = ticket(db)
    port = model(judged('ADD_ITEM', 'IT-NET-001'), drafted(body=f'#### 이런 경우\n\n- {t.receipt_no} 처럼 끊김'), drafted())
    _, run = go(db, port)
    assert (run.created, len(draft_requests(port))) == (1, 2)               # 다시 불러 성공


def test_basis_error_keeps_tickets(db):
    t = ticket(db)
    port = model(judged('ADD_ITEM', 'IT-NET-001'), drafted())
    _, run = go(db, port, Case(fail=True))
    assert (run.failed, draft_requests(port), state(db, t).fail_code) == (1, [], 'BASIS_FAILED')


def test_embedding_failure_keeps_tickets(db):
    t = ticket(db)

    def broken(texts):
        raise FileNotFoundError('model')
    _, run = run_round(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()), searcher(), broken, Case().fns())
    assert (run.failed, state(db, t).status, state(db, t).fail_code) == (1, None, 'EMBED_FAILED')


def test_failed_ticket_is_judged_again_next_round(db):
    t = ticket(db)
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), 'not json'))
    _, run = go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    assert (run.created, state(db, t).status, state(db, t).fail_count) == (1, 'REVIEWING', 0)


def test_handling_majority_and_warning(db):
    ticket(db, 'VPN 끊김', group=1), ticket(db, 'VPN 안 됨', group=2), ticket(db, 'VPN 느림', group=1)
    go(db, model(judged('ADD_ITEM', 'IT-NET-001'), drafted()))
    c = clusters(db)[0]
    assert '**담당 부서** 네트워크팀' in c.draft_md
    assert any(w.startswith('티켓마다 담당 부서가 다릅니다 (네트워크팀 2건, 서비스데스크 1건)') for w in c.review_info['warnings'])


def test_sec_makes_no_cluster(db):
    """한 회차 전체에서도 SEC 묶음은 생기지 않는다 (M4 결정, 2026-11-10)"""
    ticket(db, category='SEC')
    port = MockAdapter()
    judged, drafted = go(db, port)
    assert (clusters(db), judged.excluded, drafted.created, port.requests) == ([], 1, 0, [])


@pytest.mark.parametrize('word, out', [('네트워크팀', '네트워크팀이'), ('서비스데스크', '서비스데스크가'), ('IT', 'IT이(가)')])
def test_subject_particle(word, out):
    assert dr._subject(word) == out


def test_prompt_has_rules():
    p = dr.SYSTEM_PROMPT
    assert '내부 절차' in p and 'doc_type 이 MANUAL 인 항목의 내용은 본문에 옮기지 않습니다' in p
    assert '"해결되지 않으면" 문단도 서버가 붙입니다' in p and 'content_hidden=true' in p
