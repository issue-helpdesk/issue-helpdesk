"""검색(M3-2-2)·권한 필터(M3-2-3)·과거 사례 임베딩을 실제 PostgreSQL(pgvector)에서 검사한다.

TEST_DATABASE_URL 이 있을 때만 돈다. 그 서버에 임시 DB 를 새로 만들어 마이그레이션을 올리고, 끝나면 지운다.
임베딩 모델 대신 글자 조각으로 벡터를 만드는 가짜 모델을 쓴다 (모델 파일 없이 빠르게).

    TEST_DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/postgres pytest tests/test_search_db.py
"""
import hashlib
import os
import subprocess
import sys
import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.rag.search import SearchRequest
from app.rag.search.index import embed_legacy
from app.rag.search.service import search, vector_literal

ADMIN_URL = os.environ.get('TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason='TEST_DATABASE_URL 이 있을 때만 돈다')
BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend')


class FakeEmbedder:
    """글자 두 개 조각을 해시해 1024칸에 세는 가짜 임베딩. 겹치는 글자가 많을수록 가깝다."""
    model_id = 'fake@test/v1'
    dim = 1024

    def embed_documents(self, texts):
        out = []
        for t in texts:
            v = np.zeros(self.dim)
            s = ''.join(t.split())
            for i in range(len(s) - 1):
                v[int(hashlib.md5(s[i:i + 2].encode()).hexdigest(), 16) % self.dim] += 1
            out.append((v / (np.linalg.norm(v) or 1)).tolist())
        return out

    def embed_query(self, t):
        return self.embed_documents([t])[0]


@pytest.fixture(scope='module')
def engine():
    name = f'itssue_search_test_{uuid.uuid4().hex[:8]}'
    admin = create_engine(ADMIN_URL.replace('postgresql://', 'postgresql+psycopg://', 1), isolation_level='AUTOCOMMIT')
    with admin.connect() as c:
        c.execute(text(f'create database {name}'))
    url = ADMIN_URL.rsplit('/', 1)[0] + '/' + name
    env = {**os.environ, 'DATABASE_URL': url, 'PYTHONIOENCODING': 'utf-8'}
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    eng = create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1))
    with Session(eng) as s:
        seed(s)
        s.commit()
    yield eng
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f'drop database {name} with (force)'))
    admin.dispose()


PRINTER = '프린터 인쇄가 대기열에만 있고 출력되지 않음'
DOCS = [
    # doc_code, category, doc_type, view_scope, transfer, is_active, is_current, units [(unit_key, type, location, [part bodies])]
    ('IT-HW-003', 'HW', 'GUIDE', 'ALL', 'ALLOWED', True, True, [
        ('IT-HW-003@v2.0/item:3.1', 'ITEM', '3.1', ['인쇄를 보냈는데 대기열에만 있고 출력되지 않는다. 인쇄 대기열을 비웁니다.',
                                                  'PC를 재부팅한 뒤 다시 인쇄합니다.']),
        ('IT-HW-003@v2.0/item:3.7', 'ITEM', '3.7', ['토너가 떨어지면 비품함 토너로 교체합니다.'])]),
    ('IT-HW-003-M', 'HW', 'MANUAL', 'AGENT', 'MASKED', True, True, [
        ('IT-HW-003-M@v2.0/item:3.1', 'ITEM', '3.1', ['원격 지원으로 인쇄 스풀러를 다시 시작하고 대기열을 초기화한다.'])]),
    ('IT-HW-009', 'HW', 'GUIDE', 'ALL', 'ALLOWED', False, True, [            # 비활성 문서
        ('IT-HW-009@v1.0/item:3.1', 'ITEM', '3.1', ['인쇄 대기열 오래된 안내 (삭제된 문서)'])]),
    ('IT-STD-001', None, 'STANDARD', 'ALL', 'ALLOWED', True, True, [          # 공통 기준 (분류 없음)
        ('IT-STD-001@v2.0/chapter:2', 'CHAPTER', '2', ['긴급도 기준', '인쇄 장애가 여러 층이면 P2로 본다', '그 밖의 기준'])]),
    ('IT-NET-001', 'NET', 'GUIDE', 'ALL', 'ALLOWED', True, True, [
        ('IT-NET-001@v2.0/item:3.1', 'ITEM', '3.1', ['VPN 연결 시 서버에 연결할 수 없습니다 오류가 나면 재접속합니다.']),
        ('IT-NET-001@v2.0/item:3.9', 'ITEM', '3.9', ['인쇄를 보냈는데 대기열에만 있고 출력되지 않는다. 인쇄 대기열을 비웁니다.\nPC를 재부팅한 뒤 다시 인쇄합니다.'])]),
]


def seed(s):
    emb = FakeEmbedder()
    s.execute(text("insert into categories (code, name) values ('HW','HW·업무 PC'),('NET','VPN·네트워크'),"
                   "('SEC','정보보안')"))
    gid = s.execute(text("insert into support_groups (name) values ('서비스데스크') returning id")).scalar()
    s.execute(text("insert into inquiry_types (code, category_code, name, request_kind, default_urgency, "
                   "default_group_id) values ('HW-07','HW','프린터','INCIDENT','P3', :g),"
                   "('SEC-01','SEC','계정 도용','INCIDENT','P1', :g)"), {'g': gid})
    for code, cat, dtype, scope, transfer, active, current, units in DOCS:
        did = s.execute(text("insert into knowledge_documents (doc_code, doc_type, title, category_code, is_active) "
                             "values (:c, :t, :title, :cat, :a) returning id"),
                        {'c': code, 't': dtype, 'title': code + ' 가이드', 'cat': cat, 'a': active}).scalar()
        vid = s.execute(text("insert into document_versions (document_id, version, view_scope, transfer_policy, "
                             "is_current, ingest_status) values (:d, 'v2.0', :vs, :tp, :cur, 'DONE') returning id"),
                        {'d': did, 'vs': scope, 'tp': transfer, 'cur': current}).scalar()
        seq = 0
        for uk, ctype, loc, parts in units:
            for part, body in enumerate(parts, start=1):
                seq += 1
                cid = s.execute(text(
                    "insert into document_chunks (version_id, heading_path, location, content, seq, unit_key, "
                    "chunk_type, part, meta) values (:v, :hp, :loc, :body, :seq, :uk, :ct, :part, "
                    "cast(:meta as jsonb)) returning id"),
                    {'v': vid, 'hp': f'3. 증상별 조치 방법 > {loc}', 'loc': loc, 'body': body, 'seq': seq, 'uk': uk,
                     'ct': ctype, 'part': part, 'meta': '{"inquiry_type_codes": ["HW-07"], "handling": "사용자 직접 조치"}'}
                ).scalar()
                s.execute(text("insert into document_chunk_embeddings (chunk_id, model, embedding, source_text) "
                               "values (:c, :m, cast(:e as vector), :src)"),
                          {'c': cid, 'm': emb.model_id, 'e': vector_literal(emb.embed_query(body)), 'src': body})
    hw = s.execute(text("select id from inquiry_types where code='HW-07'")).scalar()
    sec = s.execute(text("select id from inquiry_types where code='SEC-01'")).scalar()
    for no, typ, title, desc, cause, fix, scope, policy in [
        ('INQ-2026-00011', hw, '인쇄가 안 나와요', '인쇄 대기열에서 멈춤', '스풀러 멈춤', '스풀러 재시작', 'ALL', 'MASKED'),
        ('INQ-2026-00012', sec, '계정이 도용된 것 같아요', '모르는 로그인 알림', '비밀번호 유출', '비밀번호 초기화', 'AGENT', 'BLOCKED')]:
        s.execute(text("insert into legacy_inquiries (legacy_no, received_at, resolved_at, inquiry_type_id, title, "
                       "description, root_cause, resolution, view_scope, transfer_policy) values (:no, now(), "
                       "timestamp '2026-07-09 13:51', :t, :title, :d, :c, :f, :vs, :tp)"),
                  {'no': no, 't': typ, 'title': title, 'd': desc, 'c': cause, 'f': fix, 'vs': scope, 'tp': policy})
    assert embed_legacy(s, emb) == 2
    assert embed_legacy(s, emb) == 0                          # 같은 글은 다시 만들지 않는다


def run(engine, role='EMPLOYEE', **kw):
    with Session(engine) as s:
        return search(s, SearchRequest(query=kw.pop('query', PRINTER), service_role=role, **kw), FakeEmbedder())


def codes(resp):
    return [d.doc_code for d in resp.documents]


def test_employee_cannot_see_agent_manual(engine):
    """권한 필터 (M3-2-3): 일반 임직원 결과·also_in 어디에도 매뉴얼(AGENT)이 없다."""
    resp = run(engine, 'EMPLOYEE', top_k=10)
    assert 'IT-HW-003' in codes(resp)                        # 가이드는 보이고
    assert 'IT-HW-003-M' not in codes(resp)
    assert not any('IT-HW-003-M' in a for d in resp.documents for a in d.also_in)
    assert all(d.view_scope == 'ALL' for d in resp.documents)


def test_agent_sees_manual(engine):
    assert 'IT-HW-003-M' in codes(run(engine, 'AGENT', top_k=10))


def test_inactive_document_excluded(engine):
    assert 'IT-HW-009' not in codes(run(engine, 'ADMIN', top_k=10))


def test_item_restored_with_all_parts(engine):
    """항목은 나뉜 조각을 모두 붙이고, 맞지 않은 조각의 점수는 None."""
    top = run(engine, top_k=3).documents[0]
    assert top.unit_key == 'IT-HW-003@v2.0/item:3.1'
    assert [c.part for c in top.chunks] == [1, 2] and 'PC를 재부팅한 뒤' in top.text
    assert any(c.score is not None for c in top.chunks)
    assert top.citation == 'IT-HW-003 3.1' and top.evidence and all(e in top.text for e in top.evidence)


def test_duplicate_body_merged(engine):
    """본문이 같고 전송 정책도 같은 단위는 하나로 묶고 나머지는 also_in. 대표는 문의 분류와 같은 문서."""
    resp = run(engine, top_k=5, category_code='HW')
    assert 'IT-NET-001' not in codes(resp)                 # 분류 필터 (NET 제외)
    resp = run(engine, top_k=5)
    same = [d for d in resp.documents if d.unit_key in ('IT-HW-003@v2.0/item:3.1', 'IT-NET-001@v2.0/item:3.9')]
    assert len(same) == 1                                   # 둘 중 하나만 남고
    other = ({'IT-HW-003@v2.0/item:3.1', 'IT-NET-001@v2.0/item:3.9'} - {same[0].unit_key}).pop()
    assert same[0].also_in == (other,)                      # 나머지는 also_in
    hw = run(engine, top_k=5, category_code='HW').documents[0]
    assert hw.unit_key == 'IT-HW-003@v2.0/item:3.1'          # 분류를 주면 같은 분류 문서가 대표


def test_category_filter_keeps_common_standard(engine):
    assert 'IT-STD-001' in codes(run(engine, top_k=10, category_code='HW'))


def test_chapter_restores_only_neighbours(engine):
    std = next(d for d in run(engine, top_k=10, query='인쇄 장애가 여러 층이면 긴급도').documents
               if d.doc_code == 'IT-STD-001')
    assert {c.part for c in std.chunks} <= {1, 2, 3} and any(c.score is not None for c in std.chunks)


def test_legacy_scope_and_no_person_fields(engine):
    emp = run(engine, 'EMPLOYEE', sources=('LEGACY',), query='계정이 도용된 것 같아요')
    assert [r.legacy_no for r in emp.legacy] == ['INQ-2026-00011']   # 보안 사례(AGENT)는 안 보인다
    agent = run(engine, 'AGENT', sources=('LEGACY',), query='계정이 도용된 것 같아요')
    assert agent.legacy[0].legacy_no == 'INQ-2026-00012'
    r = agent.legacy[0]
    assert r.inquiry_type_code == 'SEC-01' and r.resolved_at == '2026-07-09 13:51'
    assert '제목: 계정이 도용된 것 같아요' in r.text and r.citation.startswith('과거 처리 사례 참고')


def test_legacy_only_is_not_sufficient(engine):
    resp = run(engine, 'EMPLOYEE', sources=('LEGACY',))
    assert resp.legacy and resp.documents == () and resp.sufficient is False


def test_unknown_role_gets_nothing(engine):
    """모르는 역할은 SearchRequest 단계에서 막히고, 형식상 범위도 비어 있다."""
    with pytest.raises(ValueError):
        run(engine, 'GUEST')
