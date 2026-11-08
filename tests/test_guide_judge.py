"""해결 사례 가이드화 티켓별 판단 (app.agent.guide). Mock 모델과 SQLite 메모리 DB 만 쓴다. 외부로 아무것도 보내지 않는다."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent.guide import judge_round
from app.agent.guide.judge import SYSTEM_PROMPT, CompareItem, GuideDoc, check, GuideJudgment
from app.agent.llm.mock import MockAdapter
from app.agent.llm.port import LLMError
from app.models import (Category, DocumentVersion, GuideCluster, KnowledgeDocument, LlmCall, TicketGuideState)
from app.rag.search.result import ChunkHit, DocumentResult, SearchResponse
from test_auth import TABLES, add_user
from test_dashboard import add_ticket
from test_inquiries import create_sqlite_tables

NOTE = 'VPN 패스스루 설정을 켜도록 안내해 해결했습니다. 공유기 관리 화면에서 설정합니다.'


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ['categories', 'inquiry_types', 'inquiries', 'tickets', 'knowledge_documents',
                                           'document_versions', 'guide_clusters', 'ticket_guide_states', 'llm_calls'])
    with Session(engine) as session:
        add_user(session, 'E0001', name='김민지')
        session.add_all([Category(code='NET', name='VPN·네트워크'), Category(code='SEC', name='보안')])
        for code, doc_type in (('IT-NET-001', 'GUIDE'), ('IT-NET-001-M', 'MANUAL')):
            doc = KnowledgeDocument(doc_code=code, doc_type=doc_type, title=code, category_code='NET', is_active=True)
            session.add(doc)
            session.flush()
            session.add(DocumentVersion(document_id=doc.id, version='v2.0', is_current=True, ingest_status='DONE',
                                        view_scope='ALL', transfer_policy='ALLOWED' if doc_type == 'GUIDE' else 'BLOCKED'))
        session.commit()
        yield session
    engine.dispose()


def cls_ticket(db, note=NOTE, category='NET', summary='VPN 연결 시 인터넷 끊김 (김민지 010-1234-5678)'):
    t = add_ticket(db, 1, work='CLS', category=category)
    t.summary, t.resolution_note = summary, note
    db.commit()
    return t


def result(doc_code, location, policy, text='본문'):
    return DocumentResult(unit_key=f'{doc_code}@v2.0/item:{location}', chunk_type='ITEM', doc_code=doc_code,
                          title=doc_code, version='v2.0', location=location, heading_path=f'3장 > {location} 제목',
                          text=text, chunks=(ChunkHit(1, 1, 0.8),), unit_score=0.8, score_type='cosine:m',
                          view_scope='ALL', transfer_policy=policy)


def search_fn(request):
    return SearchResponse(query=request.query, model='m', threshold=0.5, documents=(
        result('IT-NET-001', '3.3', 'ALLOWED', '재시작 안내'), result('IT-NET-001-M', '3.2', 'BLOCKED', '본인 확인 절차')))


def reply(judgment, target_doc=None, target_item=None, handling='AGENT', reason='가이드에 공유기 설정이 없음'):
    return json.dumps({'judgment': judgment, 'reason': reason, 'target_doc': target_doc,
                       'target_item': target_item, 'handling': handling})


def state(db, t):
    return db.get(TicketGuideState, t.id)


def test_add_item_forwarded_and_sent_text_is_filtered(db):
    t = cls_ticket(db)
    port = MockAdapter([reply('ADD_ITEM', 'IT-NET-001')])
    run = judge_round(db, port, search_fn)

    assert [f.outcome.judgment.judgment for f in run.forwarded] == ['ADD_ITEM']
    assert run.forwarded[0].outcome.compared == ({'doc_code': 'IT-NET-001', 'version': 'v2.0', 'location': '3.3'},
                                                 {'doc_code': 'IT-NET-001-M', 'version': 'v2.0', 'location': '3.2'})
    assert state(db, t) is None                     # 묶기 전이라 상태 행을 만들지 않는다
    sent = json.loads(port.requests[0][1])
    assert '김민지' not in port.requests[0][1] and '010-1234-5678' not in port.requests[0][1]
    assert sent['ticket']['summary'] == 'VPN 연결 시 인터넷 끊김 ([직원1] [전화번호1])'
    manual = sent['items'][1]
    assert manual == {'doc_code': 'IT-NET-001-M', 'doc_type': 'MANUAL', 'location': '3.2', 'title': '3장 > 3.2 제목',
                      'content': None, 'content_hidden': True}
    assert sent['items'][0]['content'] == '재시작 안내'
    assert port.thinks == [True]
    call = db.scalars(select(LlmCall)).one()
    assert (call.purpose, call.inquiry_id, call.success) == ('GUIDE_JUDGE', t.inquiry_id, True)


@pytest.mark.parametrize('judgment, target_doc, target_item, reason_start', [
    ('NOT_TARGET', None, None, '대상 아님: '),
    ('EXISTS', 'IT-NET-001-M', '3.2', '이미 있음 (IT-NET-001-M 3.2): '),
])
def test_excluded(db, judgment, target_doc, target_item, reason_start):
    t = cls_ticket(db)
    run = judge_round(db, MockAdapter([reply(judgment, target_doc, target_item)]), search_fn)
    s = state(db, t)
    assert (run.excluded, s.status, s.cluster_id) == (1, 'EXCLUDED', None)
    assert s.exclude_reason.startswith(reason_start)


@pytest.mark.parametrize('note, category, reason', [
    ('', 'NET', '처리 결과 없음'),
    ('처리 완료', 'NET', '처리 결과가 짧아 해결 방법을 알 수 없음 (20자 미만)'),
    ('확인 완료', 'SEC', '처리 결과가 짧아 해결 방법을 알 수 없음 (20자 미만)'),     # SEC 도 묶음을 만들지 않는다
])
def test_precheck_excluded_without_ai(db, note, category, reason):
    t = cls_ticket(db, note=note, category=category)
    port = MockAdapter()
    judge_round(db, port, search_fn)
    assert (state(db, t).status, state(db, t).exclude_reason, port.requests) == ('EXCLUDED', reason, [])


def test_no_category_excluded(db):
    t = cls_ticket(db)
    t.category_code = None
    db.commit()
    judge_round(db, MockAdapter(), search_fn)
    assert state(db, t).exclude_reason == '분류 없음'


def test_sec_becomes_cluster_without_ai(db):
    t = cls_ticket(db, category='SEC')
    port = MockAdapter()
    run = judge_round(db, port, search_fn)
    cluster = db.scalars(select(GuideCluster)).one()
    assert (run.sec, port.requests) == (1, [])
    assert (cluster.judgment, cluster.status, cluster.category_code, cluster.draft_md) == ('SEC_MANUAL', 'REVIEWING', 'SEC', None)
    assert (state(db, t).status, state(db, t).cluster_id) == ('REVIEWING', cluster.id)


def test_failure_keeps_status_and_counts(db):
    t = cls_ticket(db)
    port = MockAdapter([LLMError('TIMEOUT')])
    judge_round(db, port, search_fn)
    judge_round(db, port, search_fn)            # 다음 회차에 다시 모인다
    s = state(db, t)
    assert (s.status, s.fail_code, s.fail_count, len(port.requests)) == (None, 'TIMEOUT', 2, 2)

    judge_round(db, MockAdapter([reply('ADD_ITEM', 'IT-NET-001')]), search_fn)
    assert (state(db, t).fail_code, state(db, t).fail_count) == (None, 0)     # 성공하면 0


def test_wrong_reference_retried_then_failed(db):
    """항목 추가 대상이 매뉴얼이면 참조 오류. 한 번 다시 부르고 그래도 틀리면 실패."""
    t = cls_ticket(db)
    port = MockAdapter([reply('ADD_ITEM', 'IT-NET-001-M')])
    judge_round(db, port, search_fn)
    assert (len(port.requests), state(db, t).fail_code) == (2, 'INVALID_REFERENCE')


def test_retry_succeeds(db):
    t = cls_ticket(db)
    run = judge_round(db, MockAdapter(['not json', reply('NEW_GUIDE', 'IT-NET-001', '3.3')]), search_fn)
    j = run.forwarded[0].outcome.judgment
    assert (j.judgment, j.target_doc, j.target_item) == ('NEW_GUIDE', None, None)   # 쓰지 않는 칸은 비운다
    assert len(db.scalars(select(LlmCall)).all()) == 2 and state(db, t) is None


def test_only_cls_and_open_states_collected(db):
    done = cls_ticket(db)
    db.add(TicketGuideState(ticket_id=done.id, status='EXCLUDED', exclude_reason='이미 판단함', fail_count=0))
    waiting = cls_ticket(db)
    db.add(TicketGuideState(ticket_id=waiting.id, status='WAITING', fail_count=0))
    fin = add_ticket(db, 1, work='FIN')
    fin.resolution_note = NOTE
    db.commit()
    port = MockAdapter([reply('ADD_ITEM', 'IT-NET-001')])
    run = judge_round(db, port, search_fn)
    assert [f.ticket.ticket_id for f in run.forwarded] == [waiting.id]


def test_search_failure_is_recorded(db):
    t = cls_ticket(db)

    def broken(request):
        raise FileNotFoundError('model')
    port = MockAdapter()
    judge_round(db, port, broken)
    assert (state(db, t).fail_code, port.requests) == ('SEARCH_FAILED', [])


GUIDES = [GuideDoc('IT-NET-001', 'VPN')]
ITEMS = [CompareItem('IT-NET-001', 'GUIDE', 'v2.0', '3.3', 'ITEM', 'h', 't', 'ALLOWED'),
         CompareItem('IT-NET-001-M', 'MANUAL', 'v2.0', '3.2', 'ITEM', 'h', 't', 'BLOCKED')]


@pytest.mark.parametrize('judgment, doc, item, ok', [
    ('CHANGE', 'IT-NET-001', '3.3', True),
    ('CHANGE', 'IT-NET-001', '3.9', False),          # 보내지 않은 항목
    ('CHANGE', 'IT-NET-001-M', '3.2', False),        # 변경 대상은 가이드만
    ('EXISTS', 'IT-NET-001-M', '3.2', True),         # 이미 있음은 매뉴얼도 된다
    ('ADD_ITEM', 'IT-NET-002', None, False),         # 같은 분류 가이드 목록 밖
    ('MANUAL_CANDIDATE', None, None, True),
])
def test_check_references(judgment, doc, item, ok):
    j = GuideJudgment(judgment=judgment, reason='이유', target_doc=doc, target_item=item, handling='AGENT')
    assert (check(j, GUIDES, ITEMS) is not None) == ok


def test_prompt_has_rules():
    assert 'content_hidden=true' in SYSTEM_PROMPT and 'MANUAL_CANDIDATE 로 고르세요' in SYSTEM_PROMPT
