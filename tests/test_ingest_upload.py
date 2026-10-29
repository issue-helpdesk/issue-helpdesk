"""업로드 적재(app.rag.ingest.upload, M2-3-1)를 검사한다.

앞부분은 DB 없이 돈다 (파일 준비·대조). 뒷부분은 test_ingest_db.py 와 같이 TEST_DATABASE_URL 이 localhost 일 때만,
같은 서버에 무작위 이름의 전용 DB를 만들어 그 안에서만 작업한다.
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres uv run pytest tests/test_ingest_upload.py
"""
import os
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.rag.chunker import chunk_document
from app.rag.ingest import GUIDES, FakeEmbedder, IngestError, activate, connect, load_manifest
from app.rag.ingest.upload import ingest_version, prepare_version, resolve_file, resume_pending, unknown_inquiry_types
from app.rag.parser import parse

URL = os.environ.get('TEST_DATABASE_URL', '')
ON_DB = urlparse(URL).hostname in ('localhost', '127.0.0.1')
needs_db = pytest.mark.skipif(not ON_DB, reason='TEST_DATABASE_URL 이 localhost PostgreSQL 이 아니면 건너뛴다 (공유 DB 보호)')
REPO = Path(__file__).resolve().parents[1]
EMB = FakeEmbedder('bge-m3')


def guide_file(code: str, fmt: str = 'md') -> str:
    """정리본 파일의 저장소 기준 상대 경로 (정리본 적재와 같은 file_path 모양)."""
    return (GUIDES / load_manifest(docs=[code])[0]['files'][fmt]).relative_to(REPO).as_posix()


def md_units(code: str) -> list[str]:
    return [c.unit_key for c in chunk_document(parse(str(REPO / guide_file(code))))]


def row(code='IT-SW-002', version='v2.0', file_path=None, scope='AGENT', title=None, category='SW'):
    """_read_version 이 돌려주는 모양의 버전 정보 (DB 없이 prepare_version 시험용)."""
    return {'id': 1, 'document_id': 1, 'version': version, 'file_path': file_path or guide_file(code), 'status': 'PENDING',
            'is_current': False, 'view_scope': scope, 'doc_code': code, 'title': title or '', 'category_code': category}


CODES = {'SW-01', 'SW-02', 'SW-03', 'HW-01', 'HW-02', 'HW-03', 'HW-06'}


# ── DB 없이 ───────────────────────────────────────────────────

@pytest.mark.parametrize('fmt', ['md', 'docx', 'pdf', 'pptx'])
def test_prepare_all_formats_same_units(fmt):
    """다섯 형식 중 정리본에 있는 네 형식: 단위가 md 와 같고, file_format 이 형식대로."""
    warnings = []
    p = prepare_version(row(file_path=guide_file('IT-SW-002', fmt)), REPO, CODES, warnings)
    assert [c.unit_key for c in p.chunks] == md_units('IT-SW-002')
    assert p.version == {'version': 'v2.0', 'file_format': fmt.upper()}
    assert all(r['meta']['inquiry_type_codes'] == ['SW-02'] for r in p.rows if r['chunk_type'] == 'ITEM')


def test_prepare_txt_without_header(tmp_path):
    """머리말 없는 txt: 문서 번호·버전은 등록값으로 (파일 이름에 기대지 않는다)."""
    f = tmp_path / 'upload_7f3a.txt'
    f.write_text('VPN 접속이 끊길 때\n앱을 다시 실행합니다.\n그래도 안 되면 서비스데스크에 문의합니다.\n', encoding='utf-8')
    p = prepare_version(row(code='IT-NET-009', version='v1.0', file_path=str(f), category='NET'), REPO, CODES, [])
    assert p.chunks and all(c.unit_key.startswith('IT-NET-009@v1.0/') for c in p.chunks)
    assert p.version['file_format'] == 'TEXT'


@pytest.mark.parametrize('kw, msg', [({'code': 'IT-SW-001', 'file_path': guide_file('IT-SW-002')}, '문서 번호(IT-SW-002)'),
                                     ({'version': 'v2.1'}, '버전(v2.0)')])
def test_prepare_mismatch_fails(kw, msg):
    with pytest.raises(IngestError) as e:
        prepare_version(row(**kw), REPO, CODES, [])
    assert msg in e.value.problems[0]


def test_prepare_unknown_inquiry_type(tmp_path):
    """표에 없는 문의 유형 코드: 실패하지 않고 그 코드만 빼고 경고 (계획 5장 결정)."""
    text = (REPO / guide_file('IT-SW-002')).read_text(encoding='utf-8').replace('**문의 유형** SW-02', '**문의 유형** SW-99')
    f = tmp_path / 'IT-SW-002.md'
    f.write_text(text, encoding='utf-8')
    warnings = []
    p = prepare_version(row(file_path=str(f)), REPO, CODES, warnings)
    assert [w for w in warnings if 'SW-99' in w and '코드는 빼고' in w]
    assert all(r['meta']['inquiry_type_codes'] == [] for r in p.rows)
    assert any('SW-99' in str(r['meta']['props']) for r in p.rows)    # 원문 항목 머리는 남는다


def test_unknown_inquiry_types_lists_sections():
    chunks = chunk_document(parse(str(REPO / guide_file('IT-HW-001-M'))))
    found = unknown_inquiry_types(chunks, {'HW-01', 'HW-02'})
    assert set(found) == {'HW-03', 'HW-06'} and all(found.values())


def test_prepare_warns_but_keeps_registered_values():
    """제목·분류·열람 등급이 파일과 달라도 등록값 그대로, 경고만."""
    warnings = []
    p = prepare_version(row(scope='ALL', title='다른 제목', category='HW'), REPO, CODES, warnings)
    assert p.chunks
    assert any('제목' in w for w in warnings) and any('분류' in w for w in warnings)
    assert not any('열람' in w for w in warnings)                 # 파일(사내 일반 = ALL)이 더 좁지 않다
    m_warn = []
    prepare_version(row(code='IT-HW-001-M', file_path=guide_file('IT-HW-001-M'), scope='ALL', category='HW'),
                    REPO, CODES, m_warn)
    assert any('열람' in w for w in m_warn)                       # 매뉴얼(담당자 전용)을 ALL 로 등록


def test_resolve_file_stays_inside_root(tmp_path):
    assert resolve_file('a/b.md', tmp_path) == (tmp_path / 'a' / 'b.md').resolve()
    with pytest.raises(IngestError):
        resolve_file('../outside.md', tmp_path)
    with pytest.raises(IngestError):
        resolve_file('', tmp_path)


# ── DB ────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def url():
    """테스트 전용 DB → 마이그레이션 → 기준 데이터 시드 (가이드는 적재하지 않는다. 시험마다 문서를 등록한다)."""
    if not ON_DB:
        pytest.skip('TEST_DATABASE_URL 이 localhost PostgreSQL 이 아니면 건너뛴다 (공유 DB 보호)')
    from test_faq_seed import load_seed
    from test_ingest_db import fresh_database
    with fresh_database() as u:
        env = {**os.environ, 'DATABASE_URL': u, 'PYTHONIOENCODING': 'utf-8'}
        out = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=REPO / 'backend',
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
        yield u


def register(url, code, version='v2.0', file_path=None, scope='AGENT', policy='BLOCKED', age=timedelta(0)):
    """DC-02·07 이 하는 일: 문서 행(없으면) + 버전 행(PENDING·비현행). 버전 id."""
    category = code.split('-')[1] if code.split('-')[1] != 'STD' else None
    with connect(url) as conn:
        doc_id = conn.execute(
            "insert into knowledge_documents (doc_code, doc_type, title, category_code) values (%s, 'GUIDE', %s, %s) "
            'on conflict (doc_code) do update set doc_code = excluded.doc_code returning id',
            (code, f'{code} 제목', category)).fetchone()[0]
        vid = conn.execute(
            'insert into document_versions (document_id, version, file_path, view_scope, transfer_policy, is_current, '
            "ingest_status, registered_at) values (%s, %s, %s, %s, %s, false, 'PENDING', now() - %s) returning id",
            (doc_id, version, file_path or guide_file(code), scope, policy, age)).fetchone()[0]
        conn.commit()
    return vid


def version(url, vid):
    """(ingest_status, ingest_error, is_current, view_scope, transfer_policy, file_format, 청크 수, 임베딩 수)"""
    with connect(url) as conn:
        return conn.execute('''select v.ingest_status, v.ingest_error, v.is_current, v.view_scope, v.transfer_policy,
                                      v.file_format,
                                      (select count(*) from document_chunks c where c.version_id = v.id),
                                      (select count(*) from document_chunk_embeddings e join document_chunks c
                                          on c.id = e.chunk_id where c.version_id = v.id)
                                 from document_versions v where v.id = %s''', (vid,)).fetchone()


def ingest(url, vid, **kw):
    with connect(url) as conn:
        return ingest_version(conn, vid, EMB, **kw)


@needs_db
@pytest.mark.parametrize('code, fmt', [('IT-SW-001', 'md'), ('IT-SW-003', 'docx'), ('IT-HW-002', 'pdf'), ('IT-NET-001', 'pptx')])
def test_ingest_formats(url, code, fmt):
    """형식마다 DONE, 청크·임베딩 수 = md 단위 결과, 정책은 등록값, 현행 전환은 안 함 (DC-07)."""
    vid = register(url, code, file_path=guide_file(code, fmt), scope='AGENT', policy='MASKED')
    out = ingest(url, vid)
    n = len(md_units(code))
    assert out['status'] == 'DONE' and out['chunks'] == n and not out['activated']
    assert version(url, vid) == ('DONE', None, False, 'AGENT', 'MASKED', fmt.upper(), n, n)


@needs_db
@pytest.mark.parametrize('ver, file_path, msg', [('v9.1', 'dataset/guides/없는파일.md', '파일을 찾을 수 없습니다'),
                                                 ('v9.2', '../../밖.md', '저장 폴더 밖'),
                                                 ('v2.0', guide_file('IT-SW-002'), '문서 번호(IT-SW-002)')])
def test_ingest_failure_recorded(url, ver, file_path, msg):
    """실패는 FAILED + 관리자에게 보여 줄 사유, 청크 없음."""
    vid = register(url, 'IT-ACC-001', version=ver, file_path=file_path)
    out = ingest(url, vid)
    assert out['status'] == 'FAILED' and msg in out['error']
    status, error, current, *_, chunks, _ = version(url, vid)
    assert (status, current, chunks) == ('FAILED', False, 0) and msg in error


@needs_db
def test_ingest_unsupported_and_empty(url, tmp_path):
    hwp, empty = tmp_path / 'a.hwp', tmp_path / 'b.md'
    hwp.write_bytes(b'not really hwp')
    empty.write_bytes(b'')
    for i, (f, msg) in enumerate([(hwp, 'DOCX 또는 PDF로'), (empty, '빈 파일')]):
        vid = register(url, 'IT-ACC-002', version=f'v8.{i}', file_path=str(f))
        out = ingest(url, vid)
        assert out['status'] == 'FAILED' and msg in out['error'], out


@needs_db
def test_failure_keeps_current(url):
    """새 버전이 실패해도 현행 버전과 그 청크는 그대로 (검색 영향 없음)."""
    v1 = register(url, 'IT-SEC-001')
    assert ingest(url, v1, activate_version=True)['activated']
    before = version(url, v1)
    v2 = register(url, 'IT-SEC-001', version='v2.1')               # 파일 머리말은 v2.0 → 실패
    assert ingest(url, v2)['status'] == 'FAILED'
    assert version(url, v1) == before and before[:3] == ('DONE', None, True)


@needs_db
def test_skip_done_and_current(url):
    vid = register(url, 'IT-SEC-002')
    assert ingest(url, vid)['status'] == 'DONE'
    assert ingest(url, vid)['status'] == 'SKIPPED'                 # 두 번 불러도 한 번만
    with connect(url) as conn:
        activate(conn, vid)
        conn.commit()
    assert ingest(url, vid)['status'] == 'SKIPPED'


@needs_db
def test_retry_failed_after_fix(url, tmp_path):
    """FAILED 버전은 파일을 고친 뒤 다시 부르면 DONE, ingest_error 가 지워진다."""
    f = tmp_path / 'IT-SEC-003.md'
    f.write_bytes(b'')
    vid = register(url, 'IT-SEC-003', file_path=str(f))
    assert ingest(url, vid)['status'] == 'FAILED'
    f.write_text((REPO / guide_file('IT-SEC-003')).read_text(encoding='utf-8'), encoding='utf-8')
    assert ingest(url, vid)['status'] == 'DONE'
    assert version(url, vid)[:2] == ('DONE', None)


@needs_db
def test_concurrent_calls_load_once(url):
    """같은 버전을 동시에 두 번 불러도 하나만 적재 (잠근 뒤 상태 다시 확인)."""
    vid = register(url, 'IT-SEC-004')
    results = []
    threads = [threading.Thread(target=lambda: results.append(ingest(url, vid)['status'])) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ['DONE', 'SKIPPED']
    n = len(md_units('IT-SEC-004'))
    assert version(url, vid)[-2:] == (n, n)


@needs_db
def test_resume_pending_only_stale(url):
    stale = register(url, 'IT-ACS-001', age=timedelta(hours=1))
    fresh = register(url, 'IT-ACS-002')
    with connect(url) as conn:
        done = {r['version_id']: r['status'] for r in resume_pending(conn, EMB)}
    assert done.get(stale) == 'DONE' and fresh not in done
    assert version(url, fresh)[0] == 'PENDING'


@needs_db
def test_end_to_end_searchable_after_activate(url):
    """완료 기준: 업로드 → 적재 → 현행 전환 → search() 에 새 버전이 나온다. 전환 전에는 나오지 않는다."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.rag.search import SearchRequest
    from app.rag.search.service import search

    code = 'IT-HW-003'
    vid = register(url, code, scope='ALL', policy='ALLOWED')
    assert ingest(url, vid)['status'] == 'DONE'
    query = next(c.text for c in chunk_document(parse(str(REPO / guide_file(code)))) if c.chunk_type == 'item')
    engine = create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1))

    def found():
        with Session(engine) as s:
            resp = search(s, SearchRequest(query=query, service_role='EMPLOYEE', sources=('DOCUMENT',), top_k=3), EMB)
        return [d.doc_code for d in resp.documents]

    assert code not in found()                                    # DONE 이지만 현행 전 (DC-07)
    with connect(url) as conn:
        activate(conn, vid)
        conn.commit()
    assert found()[0] == code
    engine.dispose()


@needs_db
def test_cli_version_id(url, capsys):
    from app.rag.ingest.__main__ import main
    vid = register(url, 'IT-ACS-003')
    assert main(['--embedder', 'fake', '--database-url', url, '--version-id', str(vid)]) == 0
    assert f'버전 {vid}: DONE' in capsys.readouterr().out
    bad = register(url, 'IT-ACS-003', version='v7.0')
    assert main(['--embedder', 'fake', '--database-url', url, '--version-id', str(bad)]) == 1


def _add_inquiry_type(url, code, like='SW-02'):
    """M2-3-2 가 할 일 흉내: 문의 유형 하나 등록 (나머지 칸은 비슷한 유형에서)."""
    with connect(url) as conn:
        conn.execute('insert into inquiry_types (code, category_code, name, request_kind, default_urgency, default_group_id) '
                     "select %s, category_code, '시험 유형', request_kind, default_urgency, default_group_id "
                     'from inquiry_types where code = %s', (code, like))
        conn.commit()


def _chunks(url, vid):
    """(청크 id, 문의 유형 코드) 순번 순, 모델별 임베딩 수."""
    with connect(url) as conn:
        rows = conn.execute('select id, meta from document_chunks where version_id = %s order by seq', (vid,)).fetchall()
        models = dict(conn.execute('select e.model, count(*) from document_chunk_embeddings e join document_chunks c '
                                   'on c.id = e.chunk_id where c.version_id = %s group by e.model', (vid,)).fetchall())
    return [(i, m['inquiry_type_codes']) for i, m in rows], models


@needs_db
def test_reload_restores_dropped_code(url, tmp_path):
    """검수 P2-1: 모르는 코드를 빼고 DONE·현행이 된 버전도, 유형을 등록한 뒤 reload 하면 코드가 들어간다.
    재검수 P2: 현행은 같은 청크 id 에 이름표만 고쳐 쓰고 바뀐 칸을 경고한다. 두 모델 벡터 유지. 일반 호출은 SKIPPED."""
    f = tmp_path / 'IT-SW-002.md'
    f.write_text((REPO / guide_file('IT-SW-002')).read_text(encoding='utf-8').replace(
        '**문의 유형** SW-02', '**문의 유형** SW-98'), encoding='utf-8')
    vid = register(url, 'IT-SW-002', file_path=str(f))
    out = ingest(url, vid, activate_version=True)
    assert out['status'] == 'DONE' and out['activated']
    assert [w for w in out['warnings'] if f'--version-id {vid} --reload' in w]
    kure = FakeEmbedder('kure-v1')
    with connect(url) as conn:                                     # 청크가 같으면 id 유지, 그 모델 벡터만 더한다
        before, _ = _chunks(url, vid)
        assert ingest_version(conn, vid, kure, reload=True)['status'] == 'DONE'
    after, models = _chunks(url, vid)
    assert after == before and models == {EMB.model_id: len(before), kure.model_id: len(before)}

    _add_inquiry_type(url, 'SW-98')
    assert ingest(url, vid)['status'] == 'SKIPPED'                 # 일반 호출은 두 번 적재하지 않는다
    out = ingest(url, vid, reload=True)
    assert out['status'] == 'DONE', out
    assert '이름표 바뀜 item:3.1: inquiry_type_codes [] → ["SW-98"]' in out['warnings']
    assert not [w for w in out['warnings'] if '코드는 빼고' in w]
    after, models = _chunks(url, vid)
    assert [i for i, _ in after] == [i for i, _ in before]          # 청크 id 그대로
    assert any('SW-98' in codes for _, codes in after)
    assert models == {EMB.model_id: len(after), kure.model_id: len(after)}
    assert version(url, vid)[:3] == ('DONE', None, True)
    assert not [w for w in ingest(url, vid, reload=True)['warnings'] if '이름표' in w]   # 다시 하면 바뀐 것 없음


CHANGED = '### 원인\n- 바뀐 본문 한 줄'                         # 첫 '### 원인' 자리에 넣어 본문을 바꾼다


@needs_db
def test_reload_current_with_changed_body_refused(url, tmp_path):
    """재검수 P2: 현행의 본문이 바뀐 reload 는 거부 (새 버전으로). DB·청크 id 그대로. 현행이 아니면 교체한다."""
    text = (REPO / guide_file('IT-SYS-004')).read_text(encoding='utf-8')
    f = tmp_path / 'IT-SYS-004.md'
    f.write_text(text, encoding='utf-8')
    cur = register(url, 'IT-SYS-004', file_path=str(f))
    assert ingest(url, cur, activate_version=True)['activated']
    before, state = _chunks(url, cur), version(url, cur)
    f.write_text(text.replace('### 원인', CHANGED, 1), encoding='utf-8')
    out = ingest(url, cur, reload=True)
    assert out['status'] == 'FAILED' and '새 버전으로 올린 뒤' in out['error']
    assert (_chunks(url, cur), version(url, cur)) == (before, state)

    g = tmp_path / 'IT-SYS-005.md'
    g.write_text((REPO / guide_file('IT-SYS-005')).read_text(encoding='utf-8'), encoding='utf-8')
    other = register(url, 'IT-SYS-005', file_path=str(g))
    assert ingest(url, other)['status'] == 'DONE'
    kure = FakeEmbedder('kure-v1')
    with connect(url) as conn:
        assert ingest_version(conn, other, kure, reload=True)['status'] == 'DONE'
    ids = [i for i, _ in _chunks(url, other)[0]]
    g.write_text(g.read_text(encoding='utf-8').replace('### 원인', CHANGED, 1), encoding='utf-8')
    out = ingest(url, other, reload=True)
    assert out['status'] == 'DONE'
    after, models = _chunks(url, other)
    assert [i for i, _ in after] != ids                            # 현행이 아니면 통째로 교체
    assert models[EMB.model_id] == len(after) and 0 < models[kure.model_id] < len(after)   # 글이 같은 벡터만 옮김
    assert [w for w in out['warnings'] if f'{kure.model_id} 임베딩' in w and '빠짐' in w]


@needs_db
def test_search_during_current_relabel_is_consistent(url, tmp_path):
    """재검수 P2: 검색의 두 쿼리(점수 → 본문) 사이에 현행 reload 가 끼어도 점수와 본문이 같은 청크에서 나온다."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.rag.search import SearchRequest
    from app.rag.search.service import HITS_SQL, search

    text = (REPO / guide_file('IT-SYS-006')).read_text(encoding='utf-8')
    f = tmp_path / 'IT-SYS-006.md'
    f.write_text(text.replace('**문의 유형** SYS-13', '**문의 유형** SYS-97'), encoding='utf-8')
    vid = register(url, 'IT-SYS-006', file_path=str(f), scope='ALL', policy='ALLOWED')
    assert ingest(url, vid, activate_version=True)['activated']
    query = next(c.text for c in chunk_document(parse(str(f))) if c.chunk_type == 'item')
    _add_inquiry_type(url, 'SYS-97', like='SYS-13')

    class Interleaved:                                             # 첫 점수 쿼리 바로 뒤에 reload 를 끼운다
        fired = False

        def __init__(self, s):
            self.s = s

        def execute(self, stmt, params):
            result = self.s.execute(stmt, params)
            if stmt is HITS_SQL and not self.fired:
                self.fired = True
                rows = result.mappings().all()
                assert ingest(url, vid, reload=True)['status'] == 'DONE'
                return type('Saved', (), {'mappings': lambda self: self, 'all': lambda self: rows})()
            return result

    engine = create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1))
    try:
        with Session(engine) as s:
            resp = search(Interleaved(s), SearchRequest(query=query, service_role='EMPLOYEE', sources=('DOCUMENT',),
                                                        top_k=3), EMB)
    finally:
        engine.dispose()
    assert resp.documents and resp.documents[0].doc_code == 'IT-SYS-006'
    assert all(any(c.score is not None for c in d.chunks) for d in resp.documents)


@needs_db
def test_reload_failure_keeps_done(url, tmp_path):
    """reload 가 실패하면 결과는 FAILED 지만 DB 는 DONE·현행·청크 그대로 (검색 영향 없음)."""
    f = tmp_path / 'IT-SYS-001.md'
    f.write_text((REPO / guide_file('IT-SYS-001')).read_text(encoding='utf-8'), encoding='utf-8')
    vid = register(url, 'IT-SYS-001', file_path=str(f))
    assert ingest(url, vid, activate_version=True)['activated']
    before = version(url, vid)
    f.write_bytes(b'')
    out = ingest(url, vid, reload=True)
    assert out['status'] == 'FAILED' and '빈 파일' in out['error']
    assert version(url, vid) == before and before[:3] == ('DONE', None, True)


@needs_db
def test_failure_after_other_call_done_is_skipped(url):
    """검수 P2-2: 이 작업이 실패하는 사이 다른 작업이 DONE 으로 끝냈으면 FAILED 가 아니라 SKIPPED (DB 와 같게)."""
    vid = register(url, 'IT-SYS-002')

    class RacingEmbedder:
        model_id = EMB.model_id

        def embed_documents(self, texts):
            assert ingest(url, vid)['status'] == 'DONE'
            raise RuntimeError('다른 작업이 끝낸 뒤 이 작업이 실패')

    with connect(url) as conn:
        out = ingest_version(conn, vid, RacingEmbedder())
    assert (out['status'], out['error']) == ('SKIPPED', None)
    assert version(url, vid)[:2] == ('DONE', None)


@needs_db
def test_file_registered_again_during_ingest(url):
    """M2-3-2 검수 P1: 적재하는 사이 같은 버전에 파일이 다시 등록되면(file_path 바뀜) 이전 파일로 DONE·FAILED 를 남기지 않는다."""
    vid = register(url, 'IT-SYS-007')

    def move(fmt):
        with connect(url) as other:
            other.execute('update document_versions set file_path = %s where id = %s', (guide_file('IT-SYS-007', fmt), vid))
            other.commit()

    class Moving:
        model_id = EMB.model_id

        def __init__(self, fail, fmt):
            self.fail, self.fmt = fail, fmt

        def embed_documents(self, texts):
            move(self.fmt)
            if self.fail:
                raise RuntimeError('이전 파일 적재가 실패')
            return EMB.embed_documents(texts)

    for fail, fmt in ((False, 'docx'), (True, 'pdf')):
        with connect(url) as conn:
            out = ingest_version(conn, vid, Moving(fail, fmt))
        assert (out['status'], out['error']) == ('SKIPPED', None)
        assert version(url, vid)[:2] == ('PENDING', None) and version(url, vid)[6] == 0
    assert ingest(url, vid)['status'] == 'DONE' and version(url, vid)[5] == 'PDF'      # 새 파일 적재는 된다


@needs_db
def test_cli_reload(url, capsys):
    from app.rag.ingest.__main__ import main
    vid = register(url, 'IT-SYS-003')
    assert main(['--embedder', 'fake', '--database-url', url, '--version-id', str(vid)]) == 0
    assert main(['--embedder', 'fake', '--database-url', url, '--version-id', str(vid)]) == 0
    assert f'버전 {vid}: SKIPPED' in capsys.readouterr().out
    assert main(['--embedder', 'fake', '--database-url', url, '--version-id', str(vid), '--reload']) == 0
    assert f'버전 {vid}: DONE' in capsys.readouterr().out
    assert main(['--embedder', 'fake', '--database-url', url, '--reload']) == 2
