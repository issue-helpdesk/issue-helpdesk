"""FAQ 시드·Knowledge 마이그레이션을 실제 DB로 검사한다.

TEST_DATABASE_URL 이 localhost 의 PostgreSQL 을 가리킬 때만 돈다. 그 DB 자체는 건드리지 않는다:
같은 서버에 이름이 무작위인 테스트 전용 DB(itssue_test_xxxxxxxx)를 새로 만들어 그 안에서만 작업하고, 끝나면 그 DB만 지운다.
    docker: bash 작업대/청크/임시DB/verify.sh 가 띄우는 itssue-verify-db (포트 55432)
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55432/postgres pytest tests/test_knowledge_seed_db.py
"""
import contextlib
import os
import secrets
import subprocess
import sys
from urllib.parse import urlparse

import pytest

from test_knowledge_schema import ROOT, load_seed

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE_REV = '2793dd581cae'          # 이 브랜치의 마이그레이션 바로 앞
pytestmark = pytest.mark.skipif(
    urlparse(URL).hostname not in ('localhost', '127.0.0.1'),
    reason='TEST_DATABASE_URL 이 localhost PostgreSQL 이 아니면 건너뛴다 (공유 DB 보호)')

psycopg = pytest.importorskip('psycopg')


@contextlib.contextmanager
def fresh_database():
    """같은 서버에 새 DB를 만들고 그 주소를 준다. 기존 DB는 읽지도 지우지도 않는다."""
    name = f'itssue_test_{secrets.token_hex(4)}'
    with psycopg.connect(URL, autocommit=True) as admin:
        admin.execute(f'create database {name}')
    try:
        yield urlparse(URL)._replace(path=f'/{name}').geturl()
    finally:
        with psycopg.connect(URL, autocommit=True) as admin:
            admin.execute(f'drop database if exists {name} with (force)')


def alembic(url, target):
    env = {**os.environ, 'DATABASE_URL': url, 'PYTHONIOENCODING': 'utf-8'}
    return subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], cwd=os.path.join(ROOT, 'backend'),
                          env=env, capture_output=True, text=True, encoding='utf-8')


# ── 시드 재실행 ──────────────────────────────────────────────────

@pytest.fixture(scope='module')
def db():
    """테스트 전용 DB → 마이그레이션 → 시드 1회. 임베딩 표는 아직 마이그레이션이 없어 같은 이름의 작은 표로 흉내 낸다."""
    with fresh_database() as url:
        assert alembic(url, 'head').returncode == 0
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute('create table document_chunk_embeddings (chunk_id bigint not null references document_chunks (id) '
                         'on delete cascade, model text not null, primary key (chunk_id, model))')
        saved = {k: os.environ.get(k) for k in ('DATABASE_URL', 'SEED_INITIAL_PASSWORD')}
        os.environ.update(DATABASE_URL=url, SEED_INITIAL_PASSWORD='verify-only')
        seed = load_seed()
        seed.load(seed.build(), False)
        try:
            yield seed, url
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def q(url, sql, *args):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, args).fetchall()


def faq(url, code):
    """(version_id, is_current, ingest_status, view_scope, transfer_policy, chunk_id, heading_path, content, 임베딩 수)"""
    return q(url, """select v.id, v.is_current, v.ingest_status, v.view_scope, v.transfer_policy, c.id, c.heading_path,
                            c.content, (select count(*) from document_chunk_embeddings e where e.chunk_id = c.id)
                       from knowledge_documents d join document_versions v on v.document_id = d.id
                       join document_chunks c on c.version_id = v.id where d.doc_code = %s""", code)[0]


def finish(url, code):
    """적재 스크립트가 할 일을 흉내 낸다: 임베딩 1행 + DONE + 현행."""
    vid, *_, chunk_id, _, _, _ = faq(url, code)
    with psycopg.connect(url) as conn:
        conn.execute("insert into document_chunk_embeddings values (%s, 'test-model') on conflict do nothing", (chunk_id,))
        conn.execute("update document_versions set ingest_status = 'DONE', is_current = true where id = %s", (vid,))


def run(seed, change=None):
    p = seed.build()
    if change:
        change(p)
    seed.load(p, False)


def test_new_faq_is_pending_and_not_current(db):
    _, url = db
    rows = q(url, 'select is_current, ingest_status from document_versions')
    assert len(rows) == 40 and set(rows) == {(False, 'PENDING')}
    assert all('inquiry_type_codes' in m and 'urgency' in m for (m,) in q(url, 'select meta from document_chunks'))


def test_finished_faq_kept_when_input_unchanged(db):
    seed, url = db
    finish(url, 'FAQ-001')
    before = faq(url, 'FAQ-001')
    run(seed)
    after = faq(url, 'FAQ-001')
    assert after == before and after[1:3] == (True, 'DONE') and after[-1] == 1     # 현행·DONE·임베딩·청크 id 그대로


def test_changed_answer_goes_back_to_pending(db):
    seed, url = db
    finish(url, 'FAQ-002')
    chunk_id = faq(url, 'FAQ-002')[5]

    def change(p):
        next(c for c in p.rows['document_chunks'] if c['doc_code'] == 'FAQ-002')['content'] += '\n(답변 수정)'
    run(seed, change)
    _, cur, status, *_, cid, _, content, n_emb = faq(url, 'FAQ-002')
    assert (cur, status, n_emb) == (False, 'PENDING', 0)      # 다시 적재 대상, 옛 임베딩 삭제
    assert cid == chunk_id and content.endswith('(답변 수정)')   # 같은 청크 행을 고친다


def test_changed_question_also_counts(db):
    """임베딩 입력은 질문(heading_path) + 본문이라 질문만 바뀌어도 다시 적재 대상이다."""
    seed, url = db
    finish(url, 'FAQ-005')

    def change(p):
        next(c for c in p.rows['document_chunks'] if c['doc_code'] == 'FAQ-005')['heading_path'] += ' (질문 수정)'
    run(seed, change)
    assert faq(url, 'FAQ-005')[1:3] == (False, 'PENDING') and faq(url, 'FAQ-005')[-1] == 0


def test_admin_policy_kept(db):
    seed, url = db
    vid = faq(url, 'FAQ-003')[0]
    with psycopg.connect(url) as conn:
        conn.execute("update document_versions set view_scope = 'AGENT', transfer_policy = 'BLOCKED' where id = %s", (vid,))
    run(seed)
    assert faq(url, 'FAQ-003')[3:5] == ('AGENT', 'BLOCKED')


def test_second_run_changes_nothing(db):
    seed, url = db
    snap = lambda: q(url, 'select v.id, v.is_current, v.ingest_status, v.view_scope, v.transfer_policy, c.id, c.content, '
                          'c.meta from document_versions v join document_chunks c on c.version_id = v.id order by v.id')
    run(seed)
    before = snap()
    run(seed)
    assert snap() == before


# ── 마이그레이션의 기존 행 채우기 ─────────────────────────────────

def old_rows(url, doc_type, chunks):
    """새 마이그레이션 전 상태에 문서 1건·버전 1건·청크 n개를 넣는다."""
    with psycopg.connect(url) as conn:
        did = conn.execute("insert into knowledge_documents (doc_code, doc_type, title) values ('X-001', %s, 'x') "
                           "returning id", (doc_type,)).fetchone()[0]
        vid = conn.execute("insert into document_versions (document_id, version, ingest_status, is_current) "
                           "values (%s, '1.0', 'PENDING', true) returning id", (did,)).fetchone()[0]
        for i in range(chunks):
            conn.execute("insert into document_chunks (version_id, content) values (%s, %s)", (vid, f'본문 {i}'))


def test_migration_fills_old_faq_rows():
    with fresh_database() as url:
        assert alembic(url, BASE_REV).returncode == 0
        old_rows(url, 'FAQ', 1)
        assert alembic(url, 'head').returncode == 0
        assert q(url, 'select seq, unit_key, chunk_type, part from document_chunks') == [(1, 'X-001@1.0/faq:X-001', 'FAQ', 1)]
        assert q(url, 'select is_current from document_versions') == [(False,)]      # PENDING 은 현행에서 내려간다


@pytest.mark.parametrize('doc_type, chunks, message', [
    ('GUIDE', 1, 'FAQ가 아닌 문서의 청크'),          # 가이드 청크를 FAQ로 잘못 채우지 않는다
    ('FAQ', 2, '청크가 둘 이상인 버전'),
])
def test_migration_stops_on_unexpected_old_rows(doc_type, chunks, message):
    with fresh_database() as url:
        assert alembic(url, BASE_REV).returncode == 0
        old_rows(url, doc_type, chunks)
        result = alembic(url, 'head')
        assert result.returncode != 0 and message in result.stderr
        assert q(url, 'select version_num from alembic_version') == [(BASE_REV,)]    # 한 트랜잭션이라 아무것도 반영 안 됨
        assert q(url, "select count(*) from information_schema.columns "
                      "where table_name = 'document_chunks' and column_name = 'unit_key'") == [(0,)]
