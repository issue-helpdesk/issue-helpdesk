"""가이드 적재(app.rag.ingest)를 실제 DB로 검사한다 (청크_메타데이터.md 7장).

TEST_DATABASE_URL 이 localhost 의 PostgreSQL(pgvector)을 가리킬 때만 돈다. 그 DB 자체는 건드리지 않는다:
같은 서버에 이름이 무작위인 테스트 전용 DB(itssue_test_xxxxxxxx)를 새로 만들어 그 안에서만 작업하고, 끝나면 그 DB만 지운다.
    docker run -d --name itssue-ingest-db -e POSTGRES_PASSWORD=verify -p 55433:5432 pgvector/pgvector:pg17
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres pytest tests/test_ingest_db.py

전용 DB 하나에 전체를 한 번 적재하고, 바꾸는 시험은 시험마다 다른 문서를 써서 순서와 상관없이 돈다.
"""
import contextlib
import os
import secrets
import subprocess
import sys
from urllib.parse import urlparse

import pytest

from app.rag.ingest import GUIDES, FakeEmbedder, IngestError, activate, connect, load_manifest, prepare, run
from test_faq_seed import ROOT, load_seed

URL = os.environ.get('TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    urlparse(URL).hostname not in ('localhost', '127.0.0.1'),
    reason='TEST_DATABASE_URL 이 localhost PostgreSQL 이 아니면 건너뛴다 (공유 DB 보호)')

psycopg = pytest.importorskip('psycopg')
KURE, BGE = 'fake-kure-v1@0000000/v1', 'fake-bge-m3@0000000/v1'


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


@pytest.fixture(scope='module')
def url():
    """테스트 전용 DB → 마이그레이션 → 기준 데이터 시드 → 가이드 전체 적재 (가짜 임베딩 두 모델)."""
    with fresh_database() as u:
        env = {**os.environ, 'DATABASE_URL': u, 'PYTHONIOENCODING': 'utf-8'}
        out = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=os.path.join(ROOT, 'backend'),
                             env=env, capture_output=True, text=True, encoding='utf-8')
        assert out.returncode == 0, out.stderr
        saved = {k: os.environ.get(k) for k in ('DATABASE_URL', 'SEED_INITIAL_PASSWORD')}
        try:
            os.environ.update(DATABASE_URL=u, SEED_INITIAL_PASSWORD='verify-only')
            seed = load_seed()
            seed.load(seed.build(), False)
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        report = run(u, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')])
        assert {r['action'] for r in report.results} == {'new'} and all(r['activated'] for r in report.results)
        yield u


def q(url, sql, *args):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, args).fetchall()


def versions(url, code):
    """{버전: (id, is_current, ingest_status, ingest_error, transfer_policy, 청크 수)}"""
    return {v: tuple(rest) for v, *rest in q(url, '''
        select v.version, v.id, v.is_current, v.ingest_status, v.ingest_error, v.transfer_policy,
               (select count(*) from document_chunks c where c.version_id = v.id)
          from document_versions v join knowledge_documents d on d.id = v.document_id where d.doc_code = %s''', code)}


def snapshot(url):
    """표마다 (건수, 최대 id) + 현행·상태. 검증 실패 뒤 DB가 그대로인지 본다."""
    return q(url, '''select (select count(*) from knowledge_documents), (select count(*) from document_versions),
                            (select count(*) || '/' || max(id) from document_chunks),
                            (select count(*) from document_chunk_embeddings), (select count(*) from audit_logs),
                            (select string_agg(id || is_current::text || ingest_status, ',' order by id) from document_versions)''')


def variant(tmp_path, code, version=None, edit=None, policy=True):
    """정리본 문서 하나를 임시 폴더로 복사해 버전·본문·manifest 값을 바꾼 준비물을 만든다."""
    entry = dict(load_manifest(docs=[code])[0])
    with open(GUIDES / entry['files']['md'], encoding='utf-8') as f:
        text = f.read()
    if version:
        old = f'version: "{entry["version"]}"'
        assert old in text
        text, entry['version'] = text.replace(old, f'version: "{version}"', 1), version
    if edit:
        assert edit[0] in text
        text = text.replace(edit[0], edit[1], 1)
    if not policy:
        entry.pop('transfer_policy')
    tmp_path.mkdir(parents=True, exist_ok=True)
    name = f'{code}.md'
    (tmp_path / name).write_text(text, encoding='utf-8')
    entry['files'] = {'md': name}
    return prepare([entry], tmp_path)


def test_full_load(url):
    """빈 DB에 전체 적재 → 문서 56 · 청크 712 · 모델마다 임베딩 712, 문서마다 현행 1개(DONE)."""
    [(docs, current, bad)] = q(url, '''select count(*), count(*) filter (where n = 1), count(*) filter (where n <> 1)
        from (select d.id, count(v.id) filter (where v.is_current) n from knowledge_documents d
              left join document_versions v on v.document_id = d.id group by d.id) t''')
    assert (docs, current, bad) == (56, 56, 0)
    assert q(url, "select count(*) from document_versions where is_current and ingest_status <> 'DONE'") == [(0,)]
    [(chunks,)] = q(url, 'select count(*) from document_chunks c join document_versions v on v.id = c.version_id '
                         'where v.is_current')
    assert chunks == 712
    for model in (KURE, BGE):
        assert q(url, '''select count(*), count(e.source_text) from document_chunk_embeddings e
                           join document_chunks c on c.id = e.chunk_id join document_versions v on v.id = c.version_id
                          where v.is_current and e.model = %s''', model) == [(712, 712)]
    # 정리본 버전의 외부 전송 값은 manifest 그대로 (가이드·공통 기준 ALLOWED 29, 매뉴얼 BLOCKED 27)
    assert dict(q(url, "select transfer_policy, count(*) from document_versions where version = 'v2.0' group by 1")) \
        == {'ALLOWED': 29, 'BLOCKED': 27}
    assert q(url, "select count(*) from audit_logs where event_type = 'DOCUMENT_VERSION_ACTIVATE' "
                  "and result like '없음 → %%'") == [(56,)]


def test_rerun_is_unchanged_and_reuses_vectors(url):
    """같은 명령 두 번 → 변화 없음, 청크 id 그대로, 임베딩을 새로 만들지 않는다."""
    before = q(url, "select c.id, e.model from document_chunks c join document_versions v on v.id = c.version_id "
                    "join knowledge_documents d on d.id = v.document_id join document_chunk_embeddings e on e.chunk_id = c.id "
                    "where d.doc_code = 'IT-SW-003' order by 1, 2")
    embs = [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    report = run(url, embs, docs=['IT-SW-003'])
    assert [r['action'] for r in report.results] == ['unchanged'] and [e.calls for e in embs] == [0, 0]
    assert q(url, "select c.id, e.model from document_chunks c join document_versions v on v.id = c.version_id "
                  "join knowledge_documents d on d.id = v.document_id join document_chunk_embeddings e on e.chunk_id = c.id "
                  "where d.doc_code = 'IT-SW-003' order by 1, 2") == before


def test_new_version_becomes_current(url, tmp_path):
    """한 문서 내용을 바꿔 새 버전 적재 → 새 버전만 현행, 이전 버전 비현행. 글이 같은 청크의 벡터는 다시 쓴다."""
    p = variant(tmp_path, 'IT-NET-002', 'v2.1', ('개인 기기는 게스트 Wi-Fi만', '개인 기기(휴대폰 포함)는 게스트 Wi-Fi만'))
    embs = [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    report = run(url, embs, prepared=p)
    assert report.results[0]['action'] == 'new' and report.results[0]['activated']
    v = versions(url, 'IT-NET-002')
    assert v['v2.0'][1] is False and v['v2.1'][1:3] == (True, 'DONE')
    assert v['v2.0'][5] == v['v2.1'][5] == len(p[0].chunks)            # 이전 버전 청크는 그대로 남는다
    assert [e.calls for e in embs] == [1, 1]                            # 바뀐 청크 하나만 새로
    assert q(url, "select result from audit_logs where result = 'v2.0 → v2.1'") == [('v2.0 → v2.1',)]


def test_validation_failures_leave_db_unchanged(url, tmp_path):
    """검증 실패(기준표 불일치·없는 문의 유형 코드·임베딩 누락) → DB 변화 없음."""
    before = snapshot(url)
    base = {'IT-HW-002': {'chunks': 1, 'items': 1, 'units': 1}}
    with pytest.raises(IngestError, match='검증 실패'):
        run(url, [FakeEmbedder()], docs=['IT-HW-002'], base=base)

    p = variant(tmp_path, 'IT-HW-002', 'v2.1')
    p[0].chunks[0].inquiry_type_codes = ['ZZ-99']
    with pytest.raises(IngestError) as ex:
        run(url, [FakeEmbedder()], prepared=p)
    assert any('ZZ-99' in x for x in ex.value.problems)

    class Short(FakeEmbedder):
        def embed_documents(self, texts, batch_size=16):
            return super().embed_documents(texts)[:-1]

    with pytest.raises(IngestError) as ex:
        run(url, [Short('new-model')], prepared=variant(tmp_path, 'IT-HW-002', 'v2.1'))
    assert any('임베딩' in x for x in ex.value.problems)
    assert snapshot(url) == before


def test_failure_keeps_previous_current(url, tmp_path):
    """교체 중 오류 → 새 버전 FAILED·ingest_error, 이전 현행 유지.
    고쳐서 다시 넣으면 DONE 까지만 (다른 현행이 있으므로, 재검수 R2). --force-activate 로 현행 전환."""
    p = variant(tmp_path, 'IT-HW-001', 'v2.1')
    p[0].rows[2]['part'] = 0                                            # DB 제약(part >= 1)에 걸린다
    report = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], prepared=p)
    assert report.results[0]['action'] == 'failed'
    v = versions(url, 'IT-HW-001')
    assert v['v2.0'][1:3] == (True, 'DONE')
    assert v['v2.1'][1:3] == (False, 'FAILED') and 'part' in v['v2.1'][3] and v['v2.1'][5] == 0

    embs = lambda: [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    r = run(url, embs(), prepared=variant(tmp_path, 'IT-HW-001', 'v2.1')).results[0]
    assert r['action'] == 'reloaded' and not r['activated'] and '현행 아님' in r['note']
    v = versions(url, 'IT-HW-001')
    assert v['v2.0'][1] is True and v['v2.1'][1:4] == (False, 'DONE', None)

    r = run(url, embs(), prepared=variant(tmp_path, 'IT-HW-001', 'v2.1'), force_activate=True).results[0]
    assert r['action'] == 'unchanged' and r['activated']
    v = versions(url, 'IT-HW-001')
    assert v['v2.0'][1] is False and v['v2.1'][1:4] == (True, 'DONE', None)


def test_missing_transfer_policy_loads_blocked(url, tmp_path):
    """manifest 에 transfer_policy 가 없으면 경고 + BLOCKED."""
    report = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')],
                 prepared=variant(tmp_path, 'IT-ACC-001', 'v2.1', policy=False))
    assert any('BLOCKED' in w for w in report.warnings)
    v = versions(url, 'IT-ACC-001')
    assert v['v2.0'][4] == 'ALLOWED' and v['v2.1'][4] == 'BLOCKED'


def test_same_version_reload_replaces_all_chunks(url, tmp_path):
    """같은 버전 다시 적재: 그 버전 청크를 통째로 지우고 새로 넣는다 (id 새로). 현행은 그대로."""
    old_ids = {i for (i,) in q(url, "select c.id from document_chunks c join document_versions v on v.id = c.version_id "
                                    "join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-NET-001'")}
    p = variant(tmp_path, 'IT-NET-001', edit=('## 1. 개요', '## 1. 개요\n\n시험용으로 덧붙인 문장입니다.'))
    embs = [FakeEmbedder('kure-v1')]                                    # bge-m3 는 지정하지 않음 → 다시 쓸 수 있는 것만 남김
    report = run(url, embs, prepared=p)
    r = report.results[0]
    assert r['action'] == 'reloaded' and not r['activated'] and r['dropped'] == {BGE: 1}
    new_ids = {i for (i,) in q(url, "select c.id from document_chunks c join document_versions v on v.id = c.version_id "
                                    "join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-NET-001'")}
    assert len(new_ids) == len(old_ids) and not new_ids & old_ids
    assert versions(url, 'IT-NET-001')['v2.0'][1:3] == (True, 'DONE')
    counts = dict(q(url, '''select e.model, count(*) from document_chunk_embeddings e join document_chunks c on c.id = e.chunk_id
                             where c.id = any(%s) group by 1''', list(new_ids)))
    assert counts == {KURE: len(new_ids), BGE: len(new_ids) - 1}


def test_activate_rules(url, tmp_path):
    """활성화 함수: DONE 이 아니면 거부, 이미 현행이면 False, 전환은 한 트랜잭션."""
    run(url, [FakeEmbedder('kure-v1')], prepared=variant(tmp_path, 'IT-SYS-002', 'v2.1'), activate_version=False)
    v = versions(url, 'IT-SYS-002')
    assert v['v2.0'][1] is True and v['v2.1'][1:3] == (False, 'DONE')
    with connect(url) as conn:
        conn.execute("update document_versions set ingest_status = 'PENDING' where id = %s", (v['v2.1'][0],))
        with pytest.raises(ValueError, match='DONE'):
            activate(conn, v['v2.1'][0])
        conn.rollback()
        assert activate(conn, v['v2.0'][0]) is False
        assert activate(conn, v['v2.1'][0]) is True
        conn.rollback()                                                 # 부른 쪽이 commit 하지 않으면 반영되지 않는다
    assert versions(url, 'IT-SYS-002')['v2.0'][1] is True


def test_activated_at_first_time_and_kept(url, tmp_path):
    """activated_at: 처음 현행이 될 때 기록, 현행에서 내려가도 보존, 다시 현행이 돼도 처음 시각 그대로 (API 04)."""
    def stamps():
        return dict(q(url, '''select v.version, v.activated_at from document_versions v join knowledge_documents d
                               on d.id = v.document_id where d.doc_code = 'IT-SW-002' '''))

    first = stamps()['v2.0']
    assert first is not None and q(url, "select count(*) from document_versions where is_current and activated_at is null") == [(0,)]
    run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], prepared=variant(tmp_path, 'IT-SW-002', 'v2.1'))
    s = stamps()
    assert s['v2.0'] == first and s['v2.1'] is not None and s['v2.1'] >= first     # 내려간 v2.0 도 시각 보존
    vid = versions(url, 'IT-SW-002')['v2.0'][0]
    with connect(url) as conn:
        assert activate(conn, vid)                                      # v2.0 을 다시 현행으로
        conn.commit()
    assert stamps() == s


# ── 적재 회귀 시험 (코드 검수 반영) ──────────────────

def test_failed_replace_rolls_back_document_columns(url, tmp_path):
    """교체가 실패하면 문서 칸(제목 등) 변경도 같이 롤백된다 (검수 #2)."""
    old = q(url, "select title from knowledge_documents where doc_code = 'IT-ACS-001'")
    p = variant(tmp_path, 'IT-ACS-001', 'v2.1')
    p[0].document['title'] = '바뀐 제목'
    p[0].rows[2]['part'] = 0                                            # DB 제약에 걸린다
    report = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], prepared=p, apply_document=True)
    assert report.results[0]['action'] == 'failed'
    assert q(url, "select title from knowledge_documents where doc_code = 'IT-ACS-001'") == old


def test_header_change_drops_stale_unselected_vectors(url, tmp_path):
    """청크 행은 같은데 머리말(문서 제목)만 바뀌면: 청크 id 는 두고, 지정한 모델은 새 입력으로,
    지정하지 않은 모델의 예전 입력 벡터는 지우고 알린다 (검수 #3)."""
    p = variant(tmp_path, 'IT-ACS-002')
    title = p[0].document['title']
    p[0].document['title'] = title + ' 개정'
    changed = 0
    for c in p[0].chunks:
        new = c.text.replace(title, title + ' 개정', 1)
        changed += new != c.text
        c.text = new
    assert changed
    report = run(url, [FakeEmbedder('kure-v1')], prepared=p)
    r = report.results[0]
    assert r['action'] == 'unchanged' and r['dropped'] == {BGE: changed}
    rows = q(url, '''select c.seq, e.model, e.source_text from document_chunks c join document_versions v on v.id = c.version_id
                      join knowledge_documents d on d.id = v.document_id join document_chunk_embeddings e on e.chunk_id = c.id
                     where d.doc_code = 'IT-ACS-002' ''')
    assert [(seq, m) for seq, m, t in rows if t != p[0].texts[seq - 1]] == []
    assert sum(m == KURE for _, m, _ in rows) == len(p[0].chunks)


def test_replace_and_admin_activate_do_not_deadlock(url, tmp_path, monkeypatch):
    """적재 교체와 관리자 API 전환이 겹쳐도 교착되지 않는다 (검수 #5). 둘 다 문서 → 버전 순으로 잠근다.
    write_document 가 버전을 바꾼 뒤 전환하기 직전에 멈춰 두고, 그사이 다른 연결이 같은 버전을 전환한다."""
    import threading
    import time

    import app.rag.ingest as ingest

    run(url, [FakeEmbedder()], prepared=variant(tmp_path / 'a', 'IT-SYS-001', 'v2.1'), activate_version=False)
    vid = versions(url, 'IT-SYS-001')['v2.1'][0]
    with psycopg.connect(url) as conn:                                  # 다시 넣을 때 전환까지 가도록 (DONE 이 아닌 버전)
        conn.execute("update document_versions set ingest_status = 'FAILED' where id = %s", (vid,))
    p = variant(tmp_path / 'b', 'IT-SYS-001', 'v2.1')
    real, paused, go, results, errors = ingest.activate, threading.Event(), threading.Event(), {}, []

    def held(conn, version_id, actor_id=None):
        paused.set()
        go.wait(10)
        return real(conn, version_id, actor_id)

    def writer():
        try:
            results['writer'] = run(url, [FakeEmbedder()], prepared=p, force_activate=True).results[0]
        except Exception as ex:
            errors.append(repr(ex))

    def api():
        try:
            with connect(url) as conn:
                conn.execute("set statement_timeout = '8s'")
                results['api'] = real(conn, vid)
        except Exception as ex:
            errors.append(repr(ex))

    monkeypatch.setattr(ingest, 'activate', held)
    tw = threading.Thread(target=writer)
    tw.start()
    assert paused.wait(10)
    ta = threading.Thread(target=api)
    ta.start()
    time.sleep(1)                                                       # api 가 문서 잠금을 기다리게 한다
    go.set()
    tw.join(15), ta.join(15)
    assert not tw.is_alive() and not ta.is_alive() and errors == []
    assert results['writer']['action'] == 'reloaded' and results['writer']['activated'] and results['api'] is False
    assert versions(url, 'IT-SYS-001')['v2.1'][1:3] == (True, 'DONE')


def test_rerun_keeps_admin_chosen_current(url, tmp_path):
    """관리자가 다른 버전을 현행으로 바꾼 뒤 적재를 다시 돌려도 manifest 버전으로 되돌리지 않는다 (검수 #6, J3)."""
    run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], prepared=variant(tmp_path, 'IT-SEC-001', 'v2.1'),
        activate_version=False)
    vid = versions(url, 'IT-SEC-001')['v2.1'][0]
    with connect(url) as conn:
        assert activate(conn, vid, actor_id=None)
        conn.commit()
    report = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], docs=['IT-SEC-001'])
    r = report.results[0]
    assert r['action'] == 'unchanged' and not r['activated'] and '현행 아님' in r['note']
    v = versions(url, 'IT-SEC-001')
    assert v['v2.0'][1] is False and v['v2.1'][1] is True


def test_policy_existing_version(url):
    """이미 있는 버전의 정책 (J1): manifest 가 더 좁으면 검증 실패, --apply-policy 면 바꾸고 감사 로그.
    manifest 가 더 넓으면 DB 값 유지 + 경고."""
    def policy(code):
        return versions(url, code)['v2.0'][4]

    def set_policy(code, value):
        with psycopg.connect(url) as conn:
            conn.execute('''update document_versions v set transfer_policy = %s from knowledge_documents d
                             where d.id = v.document_id and d.doc_code = %s and v.version = 'v2.0' ''', (value, code))

    embs = lambda: [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    set_policy('IT-ACC-002-M', 'ALLOWED')                               # manifest 는 BLOCKED (매뉴얼)
    before = snapshot(url)
    with pytest.raises(IngestError) as ex:
        run(url, embs(), docs=['IT-ACC-002-M'])
    assert any('더 좁음' in x for x in ex.value.problems) and snapshot(url) == before
    report = run(url, embs(), docs=['IT-ACC-002-M'], apply_policy=True)
    assert report.results[0]['action'] == 'unchanged' and policy('IT-ACC-002-M') == 'BLOCKED'
    assert q(url, "select result from audit_logs where event_type = 'DOCUMENT_POLICY_CHANGE'") \
        == [('v2.0 AGENT/ALLOWED → AGENT/BLOCKED',)]

    set_policy('IT-ACC-003', 'BLOCKED')                                 # manifest 는 ALLOWED (가이드)
    try:
        report = run(url, embs(), docs=['IT-ACC-003'])
        assert any('DB 정책 유지' in w for w in report.warnings) and policy('IT-ACC-003') == 'BLOCKED'
    finally:
        set_policy('IT-ACC-003', 'ALLOWED')


def test_policy_widened_after_check_stops_document(url, tmp_path):
    """검증 뒤 임베딩하는 사이에 DB 정책이 manifest 보다 넓어지면 그 문서는 멈춘다 (재검수 R1).
    임베딩기가 도는 동안 다른 연결이 정책을 바꾼다 (검증과 쓰기 사이에 끼워 넣기)."""
    code = 'IT-SEC-004-M'                                               # manifest AGENT/BLOCKED
    before = q(url, '''select c.id from document_chunks c join document_versions v on v.id = c.version_id
                        join knowledge_documents d on d.id = v.document_id where d.doc_code = %s order by c.id''', code)

    class Widening(FakeEmbedder):
        def embed_documents(self, texts, batch_size=16):
            with psycopg.connect(url) as conn:
                conn.execute('''update document_versions v set view_scope = 'ALL', transfer_policy = 'ALLOWED'
                                 from knowledge_documents d where d.id = v.document_id and d.doc_code = %s''', (code,))
            return super().embed_documents(texts)

    p = variant(tmp_path, code, edit=('## 1. 개요', '## 1. 개요\n\n시험용으로 덧붙인 문장입니다.'))
    try:
        r = run(url, [Widening('kure-v1'), FakeEmbedder('bge-m3')], prepared=p).results[0]
        assert r['action'] == 'failed' and '검증 뒤 DB 정책이 바뀜' in r['error']
        assert versions(url, code)['v2.0'][1:3] == (True, 'DONE')       # 현행이라 FAILED 로 바꾸지 않고 그대로
        assert q(url, '''select c.id from document_chunks c join document_versions v on v.id = c.version_id
                          join knowledge_documents d on d.id = v.document_id where d.doc_code = %s order by c.id''', code) == before
    finally:
        with psycopg.connect(url) as conn:
            conn.execute('''update document_versions v set view_scope = 'AGENT', transfer_policy = 'BLOCKED'
                             from knowledge_documents d where d.id = v.document_id and d.doc_code = %s''', (code,))


def test_document_info_kept_unless_applied(url, tmp_path):
    """이미 있는 문서의 제목 등은 관리자가 고쳤을 수 있어 덮어쓰지 않고 알린다. --apply-document 면 파일 값으로."""
    code = 'IT-NET-003'
    with psycopg.connect(url) as conn:                                  # 관리자가 화면(DC-04)에서 제목을 고친 상태
        conn.execute("update knowledge_documents set title = '관리자가 고친 제목' where doc_code = %s", (code,))
    embs = lambda: [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    report = run(url, embs(), docs=[code])
    assert report.results[0]['action'] == 'unchanged' and any('DB 문서 정보 유지' in w for w in report.warnings)
    assert q(url, 'select title from knowledge_documents where doc_code = %s', code) == [('관리자가 고친 제목',)]

    report = run(url, embs(), docs=[code], apply_document=True)
    assert any('파일 값으로 바꿈' in w for w in report.warnings)
    [(title,)] = q(url, 'select title from knowledge_documents where doc_code = %s', code)
    assert title == load_manifest(docs=[code])[0]['title']


def test_document_type_mismatch_stops_unless_applied(url):
    """PR #364 검수 1: 매뉴얼 내용 전송 판정은 파일 종류로 한다. DB 종류가 다르면 (DB 를 두면 판정과 어긋나) 멈추고,
    --apply-document 면 파일 종류로 맞춰 판정과 같아진다. 반대 방향(DB MANUAL·파일 GUIDE)도 같다."""
    for code, other in (('IT-ACS-002-M', 'GUIDE'), ('IT-ACS-002', 'MANUAL')):
        with psycopg.connect(url) as conn:
            conn.execute('update knowledge_documents set doc_type = %s where doc_code = %s', (other, code))
        before = snapshot(url)
        with pytest.raises(IngestError) as e:                          # 검증 실패 → DB 에 아무것도 쓰지 않음
            run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], docs=[code])
        assert any(f'{code}: 문서 종류가 DB({other})와 파일' in p for p in e.value.problems) and snapshot(url) == before
        report = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], docs=[code], apply_document=True)
        assert not report.problems and report.results[0]['error'] is None
        file_type = 'MANUAL' if code.endswith('-M') else 'GUIDE'
        assert q(url, 'select doc_type from knowledge_documents where doc_code = %s', code) == [(file_type,)]
        got = {p for (p,) in q(url, '''select c.content_transfer_policy from document_chunks c join document_versions v
                                       on v.id = c.version_id and v.is_current join knowledge_documents d
                                       on d.id = v.document_id where d.doc_code = %s''', code)}
        assert got == ({'BLOCKED'} if file_type == 'MANUAL' else {None})


def test_document_type_changed_before_lock(url, monkeypatch):
    """검증 뒤 잠그기 전에 관리자가 문서 종류를 바꾸면 그 문서는 실패 (판정과 어긋난 값을 쓰지 않음)."""
    import app.rag.ingest as ingest
    code, real = 'IT-HW-003-M', ingest._lock_document

    def change_then_lock(conn, doc_id):
        with psycopg.connect(url) as other:
            other.execute("update knowledge_documents set doc_type = 'GUIDE' where id = %s", (doc_id,))
        real(conn, doc_id)
    monkeypatch.setattr(ingest, '_lock_document', change_then_lock)
    r = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], docs=[code]).results[0]
    assert r['action'] == 'failed' and '검증 뒤 문서 종류가 바뀜: DB GUIDE, 파일 MANUAL' in r['error']


def test_new_version_policy_widened_before_lock(url, tmp_path, monkeypatch):
    """새 버전 PENDING 행을 커밋한 뒤 문서를 잠그기 전에 정책이 넓어지면 그 버전은 FAILED, 현행 그대로 (PR #96 리뷰 P2)."""
    import app.rag.ingest as ingest

    code = 'IT-SEC-003-M'                                               # manifest AGENT/BLOCKED
    real, done = ingest._lock_document, []

    def widen_then_lock(conn, doc_id):
        if not done:                                                    # write_document 의 첫 잠금 직전에 한 번
            done.append(1)
            with psycopg.connect(url) as other:
                other.execute("""update document_versions set view_scope = 'ALL', transfer_policy = 'ALLOWED'
                                  where document_id = %s and version = 'v2.1'""", (doc_id,))
        real(conn, doc_id)

    monkeypatch.setattr(ingest, '_lock_document', widen_then_lock)
    r = run(url, [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')], prepared=variant(tmp_path, code, 'v2.1')).results[0]
    assert done and r['action'] == 'failed' and '검증 뒤 DB 정책이 바뀜' in r['error'] and not r['activated']
    v = versions(url, code)
    assert v['v2.0'][1:3] == (True, 'DONE') and v['v2.1'][1:3] == (False, 'FAILED') and v['v2.1'][5] == 0


def test_label_only_change_keeps_chunk_ids(url):
    """뼈대·본문이 같고 이름표만 다르면 (예: 청커가 FAQ 코드를 이어받게 된 뒤 다시 적재) 같은 id 에 이름표만 고쳐 쓴다.
    현행 청크 id 가 바뀌면 그 사이에 낀 검색이 깨진다. 벡터는 다시 만들지 않는다."""
    chunks = '''select c.id, c.unit_key, c.meta from document_chunks c join document_versions v on v.id = c.version_id
                join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-ACC-002' order by c.seq'''
    before = q(url, chunks)
    with psycopg.connect(url) as conn:                                  # 예전 청커가 넣은 것처럼 FAQ 코드를 비운다
        conn.execute("update document_chunks set meta = jsonb_set(meta, '{inquiry_type_codes}', '[]') "
                     "where id = any(%s) and unit_key like '%%/faq:%%'", ([i for i, *_ in before],))
    embs = [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    r = run(url, embs, docs=['IT-ACC-002']).results[0]
    assert r['action'] == 'relabeled' and not r['dropped'] and [e.calls for e in embs] == [0, 0]
    assert any('faq:FAQ-001: inquiry_type_codes [] → ["ACC-01"]' in c for c in r['changed'])
    assert r['changed'] and all(c.startswith('이름표 바뀜 faq:') and c.count(' → ') == 1 and 'inquiry_type_codes' in c
                                for c in r['changed'])               # FAQ 의 코드 칸만 바뀜
    assert q(url, chunks) == before                                     # id·이름표 모두 원래대로
    assert versions(url, 'IT-ACC-002')['v2.0'][1:3] == (True, 'DONE')
    assert run(url, embs, docs=['IT-ACC-002']).results[0]['action'] == 'unchanged'


def test_transfer_policy_only_change_keeps_chunk_ids(url):
    """매뉴얼 항목별 내용 전송 칸만 DB 와 다르면 (예: 허용 목록을 고친 뒤 다시 적재) 같은 id 에 그 칸만 고쳐 쓴다.
    전체 적재는 목록대로 넣는다 (지금 목록은 값이 비어 매뉴얼은 모두 BLOCKED). 벡터는 다시 만들지 않는다."""
    chunks = '''select c.id, c.content_transfer_policy from document_chunks c join document_versions v on v.id = c.version_id
                join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-SW-001-M' order by c.seq'''
    before = q(url, chunks)
    assert before and all(p == 'BLOCKED' for _, p in before)
    item = q(url, '''select c.unit_key from document_chunks c join document_versions v on v.id = c.version_id
                     join knowledge_documents d on d.id = v.document_id
                     where d.doc_code = 'IT-SW-001-M' and c.unit_key like '%%/item:%%' order by c.seq limit 1''')[0][0]
    with psycopg.connect(url) as conn:                                  # 예전 목록으로 허용됐던 것처럼
        conn.execute("update document_chunks set content_transfer_policy = 'ALLOWED' where unit_key = %s", (item,))
    embs = [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    r = run(url, embs, docs=['IT-SW-001-M']).results[0]
    assert r['action'] == 'relabeled' and not r['dropped'] and [e.calls for e in embs] == [0, 0]
    assert r['changed'] and all('content_transfer_policy "ALLOWED" → "BLOCKED"' in c for c in r['changed'])
    assert q(url, chunks) == before                                     # id 그대로, 값은 목록대로 다시 BLOCKED
    assert run(url, embs, docs=['IT-SW-001-M']).results[0]['action'] == 'unchanged'


def test_allowlist_change_relabels_manual(url, tmp_path, monkeypatch):
    """허용 목록에서 한 항목을 ALLOWED 로 채우고 다시 적재하면 그 항목 조각만 ALLOWED (같은 id·벡터 그대로).
    목록 지문과 지금 내용이 다르면 차단하고 경고한다."""
    import json
    from app.rag.ingest import allowlist as al
    data = json.loads(al.ALLOWLIST.read_text(encoding='utf-8'))
    row = next(r for r in data['items'] if r['doc_no'] == 'IT-SW-002-M')
    row['content'] = 'ALLOWED'
    f = tmp_path / 'allow.json'
    f.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(al, 'ALLOWLIST', f)
    monkeypatch.setattr(al.load, '__defaults__', (f,))
    pol = '''select c.unit_key, c.content_transfer_policy from document_chunks c join document_versions v on v.id = c.version_id
             join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-SW-002-M' order by c.seq'''
    ids = '''select c.id from document_chunks c join document_versions v on v.id = c.version_id
             join knowledge_documents d on d.id = v.document_id where d.doc_code = 'IT-SW-002-M' order by c.seq'''
    before = q(url, ids)
    embs = [FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')]
    report = run(url, embs, docs=['IT-SW-002-M'])
    assert report.results[0]['action'] == 'relabeled' and [e.calls for e in embs] == [0, 0] and q(url, ids) == before
    got = {u.rsplit(':', 1)[-1]: p for u, p in q(url, pol)}
    assert got[row['section']] == 'ALLOWED' and {p for s, p in got.items() if s != row['section']} == {'BLOCKED'}

    row['fingerprint'] = 'sha256:' + '0' * 64                          # 목록 이후 내용이 바뀐 것처럼
    f.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    report = run(url, embs, docs=['IT-SW-002-M'])
    assert {p for _, p in q(url, pol)} == {'BLOCKED'}
    assert any(f"IT-SW-002-M {row['section']}: 허용 목록 이후 내용이 바뀌어 차단" in w for w in report.warnings)


# ── 정책만 다시 반영 (allowlist reapply, M4 Q12) ──────────────

def _policies(url, code):
    return q(url, '''select c.id, c.unit_key, c.content_transfer_policy from document_chunks c
                     join document_versions v on v.id = c.version_id join knowledge_documents d on d.id = v.document_id
                     where d.doc_code = %s order by v.id, c.seq''', code)


def _emb_count(url, code):
    return q(url, '''select count(*) from document_chunk_embeddings e join document_chunks c on c.id = e.chunk_id
                     join document_versions v on v.id = c.version_id join knowledge_documents d on d.id = v.document_id
                     where d.doc_code = %s''', code)[0][0]


def _reapply(url, allow, apply=True):
    from app.rag.ingest.allowlist import reapply
    with connect(url) as conn:
        out = reapply(conn, allow)
        (conn.commit if apply else conn.rollback)()
    return out


def test_reapply_fixes_only_policy_column(url):
    """어긋난 값(매뉴얼 청크 ALLOWED·가이드 청크 BLOCKED)을 목록대로 고친다 — 그 칸만 (청크 id·임베딩 그대로), 감사 로그.
    미리보기는 DB 를 바꾸지 않는다. 다시 하면 바뀐 것 없음."""
    from app.rag.ingest.allowlist import load, _report
    allow, _ = load()
    man, guide = 'IT-NET-001-M', 'IT-NET-002'
    m0, g0 = _policies(url, man), _policies(url, guide)
    with psycopg.connect(url) as conn:
        conn.execute("update document_chunks set content_transfer_policy = 'ALLOWED' where id = %s", (m0[0][0],))
        conn.execute("update document_chunks set content_transfer_policy = 'BLOCKED' where id = %s", (g0[0][0],))
    embs = (_emb_count(url, man), _emb_count(url, guide))
    before_audit = q(url, "select count(*) from audit_logs where event_type = 'DOCUMENT_POLICY_CHANGE'")[0][0]

    preview = _reapply(url, allow, apply=False)
    assert _policies(url, man)[0][2] == 'ALLOWED'                       # 미리보기는 되돌림
    assert any(c['doc'] == man and 'ALLOWED' in c['old'] and c['new'] == 'BLOCKED' for c in preview['changes'])
    assert any(c['doc'] == guide and c['old'] == ['BLOCKED'] and c['new'] is None for c in preview['changes'])
    out = _reapply(url, allow)
    assert _policies(url, man) == m0 and _policies(url, guide) == g0      # 같은 id, 값은 목록대로
    assert (_emb_count(url, man), _emb_count(url, guide)) == embs
    assert q(url, "select count(*) from audit_logs where event_type = 'DOCUMENT_POLICY_CHANGE'")[0][0] > before_audit
    report = _report(out, True)                                        # 실제 전송 결과로: 매뉴얼은 허용→차단,
    assert f'{man} v2.0 ' in report and ': ALLOWED → BLOCKED' in report  # 가이드는 버전이 ALLOWED 라 차단→허용
    assert f'{guide} v2.0 ' in report and ': BLOCKED → ALLOWED' in report
    assert _reapply(url, allow)['changes'] == []


def test_reapply_opens_listed_item_all_pieces(url):
    """목록에 ALLOWED 를 채우면 그 항목의 모든 조각이 ALLOWED (같은 id), 보고에 '차단 → 허용' 한 줄. 지문이 다르면 그대로 차단."""
    from app.rag.ingest.allowlist import load, _report
    code = 'IT-NET-002-M'
    allow, _ = load()
    section = next(s for (d, s) in allow if d == code)
    before = _policies(url, code)
    opened = {**allow, (code, section): ('ALLOWED', allow[(code, section)][1])}
    out = _reapply(url, opened)
    after = _policies(url, code)
    assert [i for i, *_ in after] == [i for i, *_ in before]
    assert {p for _, u, p in after if u.endswith(f'/item:{section}')} == {'ALLOWED'}
    assert {p for _, u, p in after if not u.endswith(f'/item:{section}')} == {'BLOCKED'}
    assert f'{code} v2.0 item:{section}: BLOCKED → ALLOWED' in _report(out, True)
    stale = {**allow, (code, section): ('ALLOWED', 'sha256:' + '0' * 64)}
    out = _reapply(url, stale)                                          # 목록 이후 내용이 바뀐 것처럼
    assert {p for _, _, p in _policies(url, code)} == {'BLOCKED'}
    assert any(f'{code} {section}: 허용 목록 이후 내용이 바뀌어 차단' in w for w in out['warnings'])


def test_reapply_skips_version_whose_file_differs(url):
    """버전 파일의 청크 구성이 DB 와 다르면 추측하지 않고 건너뛴다 (값 그대로)."""
    from app.rag.ingest.allowlist import load
    code = 'IT-NET-003-M'
    with psycopg.connect(url) as conn:                                  # 다른 매뉴얼 파일을 가리키게
        conn.execute('''update document_versions set file_path = (select v2.file_path from document_versions v2
                        join knowledge_documents d2 on d2.id = v2.document_id where d2.doc_code = 'IT-NET-001-M' limit 1)
                        where document_id = (select id from knowledge_documents where doc_code = %s)''', (code,))
        conn.execute('''update document_chunks set content_transfer_policy = 'ALLOWED' where version_id in
                        (select v.id from document_versions v join knowledge_documents d on d.id = v.document_id
                         where d.doc_code = %s)''', (code,))
    out = _reapply(url, load()[0])
    assert any(s.startswith(f'{code} ') and '구성·본문)가 파일과 달라' in s for s in out['skipped'])
    assert {p for _, _, p in _policies(url, code)} == {'ALLOWED'}         # 건드리지 않음


def test_reapply_cli_guards_remote(capsys):
    from app.rag.ingest.allowlist import main
    assert main(['reapply', '--database-url', 'postgresql://u:p@db.example.com:5432/x']) == 2
    assert '--allow-remote' in capsys.readouterr().err


def test_reapply_skips_when_db_body_differs_from_file(url):
    """#369 검수 1: 항목 번호는 같아도 DB 에 예전 본문이 남아 있으면 (파일 지문으로 승인한 허용을 예전 본문에 붙이지 않게)
    건너뛴다 — 값 그대로, 다시 적재 필요."""
    from app.rag.ingest.allowlist import load
    code = 'IT-HW-001-M'
    allow, _ = load()
    section = next(s for (d, s) in allow if d == code)
    with psycopg.connect(url) as conn:                                  # 예전 본문이 남은 것처럼
        conn.execute('''update document_chunks set content = content || ' (예전 문장)' where unit_key like %s''',
                     (f'{code}@%/item:{section}',))
    out = _reapply(url, {**allow, (code, section): ('ALLOWED', allow[(code, section)][1])})
    assert any(s.startswith(f'{code} ') and '구성·본문)가 파일과 달라' in s for s in out['skipped'])
    assert {p for _, _, p in _policies(url, code)} == {'BLOCKED'}


def test_reapply_reads_kind_after_lock(url, monkeypatch):
    """#369 검수 2: 잠근 뒤에 문서 종류를 읽는다 — 잠그기를 기다리는 사이 종류가 바뀌어도 바뀐 종류로 판정."""
    import app.rag.ingest as ingest
    from app.rag.ingest.allowlist import load
    code, real = 'IT-HW-002-M', ingest._lock_document
    doc_id = q(url, 'select id from knowledge_documents where doc_code = %s', code)[0][0]

    def change_then_lock(conn, did):
        if did == doc_id:
            with psycopg.connect(url) as other:
                other.execute("update knowledge_documents set doc_type = 'GUIDE' where id = %s", (did,))
        real(conn, did)
    monkeypatch.setattr(ingest, '_lock_document', change_then_lock)
    _reapply(url, load()[0])
    assert {p for _, _, p in _policies(url, code)} == {None}             # 잠근 뒤 읽은 GUIDE → 빈칸
