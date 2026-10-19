"""FAQ 시드를 다시 돌릴 때 정책·현행·임베딩 상태를 지키는지 실제 DB로 검사한다.

TEST_DATABASE_URL 이 localhost 의 임시 DB를 가리킬 때만 돈다 (스키마를 지우고 다시 만든다).
    docker: bash 작업대/청크/임시DB/verify.sh 가 띄우는 itssue-verify-db (포트 55432)
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55432/postgres pytest tests/test_knowledge_seed_db.py
"""
import os
import subprocess
import sys
from urllib.parse import urlparse

import pytest

from test_knowledge_schema import ROOT, load_seed

URL = os.environ.get('TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    urlparse(URL).hostname not in ('localhost', '127.0.0.1'),
    reason='TEST_DATABASE_URL 이 localhost 임시 DB가 아니면 건너뛴다 (공유 DB 보호)')

psycopg = pytest.importorskip('psycopg')


@pytest.fixture(scope='module')
def seed():
    """빈 스키마 → 마이그레이션 → 시드 1회. 임베딩 표는 아직 마이그레이션이 없어 같은 이름의 작은 표로 흉내 낸다."""
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute('drop schema public cascade')
        conn.execute('create schema public')
    env = {**os.environ, 'DATABASE_URL': URL, 'PYTHONIOENCODING': 'utf-8'}
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=os.path.join(ROOT, 'backend'),
                   env=env, check=True, capture_output=True)
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute('create table document_chunk_embeddings (chunk_id bigint not null references document_chunks (id) '
                     'on delete cascade, model text not null, primary key (chunk_id, model))')
    saved = {k: os.environ.get(k) for k in ('DATABASE_URL', 'SEED_INITIAL_PASSWORD')}
    os.environ.update(DATABASE_URL=URL, SEED_INITIAL_PASSWORD='verify-only')
    module = load_seed()
    module.load(module.build(), False)
    yield module
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def q(sql, *args):
    with psycopg.connect(URL) as conn:
        return conn.execute(sql, args).fetchall()


def faq(code):
    """(version_id, is_current, ingest_status, view_scope, transfer_policy, chunk_id, heading_path, content, 임베딩 수)"""
    return q("""select v.id, v.is_current, v.ingest_status, v.view_scope, v.transfer_policy, c.id, c.heading_path,
                       c.content, (select count(*) from document_chunk_embeddings e where e.chunk_id = c.id)
                  from knowledge_documents d join document_versions v on v.document_id = d.id
                  join document_chunks c on c.version_id = v.id where d.doc_code = %s""", code)[0]


def finish(code):
    """적재 스크립트가 할 일을 흉내 낸다: 임베딩 1행 + DONE + 현행."""
    vid, *_, chunk_id, _, _, _ = faq(code)
    with psycopg.connect(URL) as conn:
        conn.execute("insert into document_chunk_embeddings values (%s, 'test-model') on conflict do nothing", (chunk_id,))
        conn.execute("update document_versions set ingest_status = 'DONE', is_current = true where id = %s", (vid,))


def run(seed, change=None):
    p = seed.build()
    if change:
        change(p)
    seed.load(p, False)


def test_new_faq_is_pending_and_not_current(seed):
    rows = q('select is_current, ingest_status from document_versions')
    assert len(rows) == 40 and set(rows) == {(False, 'PENDING')}
    metas = q('select meta from document_chunks')
    assert all('inquiry_type_codes' in m and 'urgency' in m for (m,) in metas)


def test_finished_faq_kept_when_input_unchanged(seed):
    finish('FAQ-001')
    before = faq('FAQ-001')
    run(seed)
    after = faq('FAQ-001')
    assert after == before and after[1:3] == (True, 'DONE') and after[-1] == 1     # 현행·DONE·임베딩·청크 id 그대로


def test_changed_answer_goes_back_to_pending(seed):
    finish('FAQ-002')
    chunk_id = faq('FAQ-002')[5]

    def change(p):
        c = next(c for c in p.rows['document_chunks'] if c['doc_code'] == 'FAQ-002')
        c['content'] += '\n(답변 수정)'
    run(seed, change)
    vid, cur, status, *_, cid, _, content, n_emb = faq('FAQ-002')
    assert (cur, status, n_emb) == (False, 'PENDING', 0)      # 다시 적재 대상, 옛 임베딩 삭제
    assert cid == chunk_id and content.endswith('(답변 수정)')   # 같은 청크 행을 고친다


def test_changed_question_also_counts(seed):
    """임베딩 입력은 질문(heading_path) + 본문이라 질문만 바뀌어도 다시 적재 대상이다."""
    finish('FAQ-005')

    def change(p):
        next(c for c in p.rows['document_chunks'] if c['doc_code'] == 'FAQ-005')['heading_path'] += ' (질문 수정)'
    run(seed, change)
    assert faq('FAQ-005')[1:3] == (False, 'PENDING') and faq('FAQ-005')[-1] == 0


def test_admin_policy_kept(seed):
    vid = faq('FAQ-003')[0]
    with psycopg.connect(URL) as conn:
        conn.execute("update document_versions set view_scope = 'AGENT', transfer_policy = 'BLOCKED' where id = %s", (vid,))
    run(seed)
    assert faq('FAQ-003')[3:5] == ('AGENT', 'BLOCKED')


def test_second_run_changes_nothing(seed):
    snap = lambda: q('select v.id, v.is_current, v.ingest_status, v.view_scope, v.transfer_policy, c.id, c.content, '
                     'c.meta from document_versions v join document_chunks c on c.version_id = v.id order by v.id')
    run(seed)
    before = snap()
    run(seed)
    assert snap() == before
