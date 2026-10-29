"""해결 사례 가이드화(app.rag.case_guide, M2-3-2)를 검사한다.

앞부분은 DB 없이 돈다 (md 고치기·검사·민감정보 경고). 뒷부분은 test_ingest_upload.py 와 같이 TEST_DATABASE_URL 이
localhost 일 때만, 무작위 이름의 전용 DB 에서 CLS 티켓 → 초안 → 등록 → 적재 → 승인 → 검색까지 본다.
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres uv run pytest tests/test_case_guide.py
"""
import re
from datetime import date
from pathlib import Path

import pytest

from app.rag.case_guide import (CASE_DIR, CaseGuideError, Draft, _added_lines, _parse_text, add_case, candidates, check,
                                draft, next_version, receipts, register, sensitive_warnings)
from app.rag.ingest import GUIDES, activate, connect
from app.rag.ingest.upload import ingest_version
from test_ingest_upload import EMB, REPO, guide_file, needs_db, url, version  # noqa: F401  (url 은 fixture)

BASE = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
TODAY = date(2026, 10, 29)


def ticket_row(**kw):
    t = {'receipt_no': 'TK-0042', 'summary': '설치가 "대기 중"에서 멈추고 캐시 폴더가 가득 참',
         'symptom': '소프트웨어 센터에서 설치가 1시간째 대기 중\n다시 시작해도 같음', 'target_system': '소프트웨어 센터',
         'resolution_note': '1. 캐시 폴더(ccmcache)를 비웠습니다\n2. 소프트웨어 센터에서 다시 설치했습니다',
         'code': 'SW-01', 'group': '엔드포인트지원팀'}
    return {**t, **kw}


def make(md_base=BASE, version='v2.1', **kw):
    warnings = []
    md, section = add_case(md_base, ticket_row(**kw), version, TODAY, warnings)
    d = Draft(ticket_id=1, receipt_no=ticket_row(**kw)['receipt_no'], document_id=1, doc_code='IT-SW-001',
              version=version, section_no=section, base_md=md_base, md=md, current_version_id=1)
    return d, warnings


def items(md):
    return [c for c in _parse_text(md)[1] if c.chunk_type == 'item']


# ── DB 없이 ───────────────────────────────────────────────────

def test_add_case_shape():
    """버전(머리말·첫머리) → 3장 끝 새 항목 3.8 → 목차 한 줄 → 개정 이력 표에 이어지는 한 줄. 나머지 줄은 그대로."""
    d, warnings = make()
    assert warnings == [] and d.section_no == '3.8'
    assert 'version: "v2.1"' in d.md and '| 2026-10-16 | v2.1 | **사내 일반**' in d.md and 'v2.0 | **사내' not in d.md
    assert d.md.index('### 3.8 ') < d.md.index('## 4. ') and d.md.index('### 3.7 ') < d.md.index('### 3.8 ')
    assert re.search(r'^  - 3\.7 .*\n  - 3\.8 설치가', d.md, re.M)
    assert re.search(r'^\| v2\.0 \|.*\|\n\| v2\.1 \| 2026-10-29 \| 엔드포인트지원팀 \| 해결 사례 반영 \(TK-0042\)', d.md, re.M)
    removed = set(BASE.splitlines()) - set(d.md.splitlines())
    assert all('v2.0' in line for line in removed)          # 바뀐 줄은 버전 표기뿐


def test_new_item_reads_like_other_items():
    """파서·청커가 항목 하나 더 읽고, 새 항목의 문의 유형·담당 부서·처리 구분이 이름표에 들어간다."""
    d, _ = make()
    before, after = items(BASE), items(d.md)
    assert len(after) == len(before) + 1 and [c.section_no for c in after][:len(before)] == [c.section_no for c in before]
    new = after[-1]
    assert (new.section_no, new.inquiry_type_codes, new.team) == ('3.8', ['SW-01'], '엔드포인트지원팀')
    assert '캐시 폴더(ccmcache)를 비웠습니다' in new.body and new.subheadings[:2] == ['이런 경우', '조치 방법']
    assert check(d, d.md, []) == ([], [])


def test_headings_in_ticket_text_do_not_break_items():
    """티켓 글에 제목(#) 줄이 있어도 항목이 나뉘지 않는다."""
    d, _ = make(resolution_note='## 4. 원인\n### 3.1 다시 설치')
    assert len(items(d.md)) == len(items(BASE)) + 1
    assert '\n4. 원인\n- 3.1 다시 설치' in d.md and '## 4. 원인' not in d.md and check(d, d.md, [])[0] == []


def test_continue_draft_appends_to_same_version():
    """이어 쓰기: 같은 버전에 3.9 를 더하고 개정 이력 그 버전 줄에 덧붙인다 (버전 줄이 둘 생기지 않게)."""
    first, _ = make()
    second, _ = make(md_base=first.md, receipt_no='TK-0043', summary='설치 후 바로 꺼짐')
    assert second.section_no == '3.9' and second.md.count('\n| v2.1 |') == 1
    assert '(TK-0042)' in second.md and '; 해결 사례 반영 (TK-0043): 3.9 설치 후 바로 꺼짐 |' in second.md


def test_sensitive_only_in_added_lines():
    """기존 문의처의 공식 연락처(it-helpdesk@…·내선)는 경고하지 않고, 새 줄의 개인정보만 줄 번호로. 값은 안 보인다."""
    d, _ = make(resolution_note='김민수 과장 PC(010-1234-5678) 원격 재설치\n결과는 minsu.kim@ict.example 로 회신')
    warnings = sensitive_warnings(d.md, _added_lines(BASE, d.md), ['김민수'])
    assert [w.split(':')[1].split('(')[0].strip() for w in warnings] == ['직원', '전화번호', '이메일']
    assert not any(x in ' '.join(warnings) for x in ('김민수', '010-1234', 'minsu'))
    line = int(re.search(r'\((\d+)번 줄\)', warnings[0]).group(1))
    assert '김민수 과장' in d.md.splitlines()[line - 1]
    assert 'it-helpdesk@ict.example' in BASE and sensitive_warnings(BASE, list(range(1, len(BASE.splitlines()) + 1)), [])
    assert check(make()[0], make()[0].md, ['김민수'])[1] == []


def test_sensitive_secrets_warned():
    d, _ = make(resolution_note='임시 비밀번호는 Abc123! 로 안내함')
    assert any('비밀번호' in w for w in check(d, d.md, [])[1])


@pytest.mark.parametrize('edit, msg', [
    (lambda md: md.replace('version: "v2.1"', 'version: "v2.0"'), '버전이 v2.0'),
    (lambda md: md.replace('doc_no: "IT-SW-001"', 'doc_no: "IT-SW-002"'), '문서 번호가 IT-SW-002'),
    (lambda md: re.sub(r'^### 3\.2 .*$', '', md, flags=re.M), '항목이 빠졌습니다: 3.2'),
    (lambda md: md.replace('TK-0042', 'TK-XXXX'), '접수 번호 TK-0042'),
])
def test_check_problems(edit, msg):
    d, _ = make()
    problems, _ = check(d, edit(d.md), [])
    assert any(msg in p for p in problems), problems


def test_check_allows_merging_into_existing_item():
    """관리자가 새 항목 3.8 을 지우고 3.7 표에 행으로 옮겨도 된다. 개정 이력의 접수 번호만 남으면."""
    d, _ = make()
    md = d.md[:d.md.index('### 3.8 ')] + d.md[d.md.index('## 4. '):]
    md = md.replace('| \"대기 중\" 30분 이상 |', '| 캐시 폴더가 가득 참 | ccmcache 비우기 |\n| \"대기 중\" 30분 이상 |')
    assert check(d, md, [])[0] == []


def test_next_version():
    assert next_version(['v1.0', 'v2.0', 'v1.9']) == 'v2.1'
    assert next_version(['v2.9']) == 'v2.10'
    with pytest.raises(CaseGuideError):
        next_version(['2026-10'])


def test_no_chapter3_refused():
    with pytest.raises(CaseGuideError):
        add_case('# 제목\n\n## 1. 개요\n\n본문\n', ticket_row(), 'v1.1', TODAY, [])


# ── DB ───────────────────────────────────────────────────────

def _current_guide(url, code='IT-SW-001'):
    """현행 가이드 하나 (file_path 는 절대 경로: 사례 파일은 tmp 저장 루트에, 기준 파일은 저장소에)."""
    with connect(url) as conn:
        doc = conn.execute("insert into knowledge_documents (doc_code, doc_type, title, category_code) "
                           "values (%s, 'GUIDE', %s, %s) on conflict (doc_code) do update set doc_code = excluded.doc_code "
                           'returning id', (code, f'{code} 제목', code.split('-')[1])).fetchone()[0]
        have = conn.execute('select id from document_versions where document_id = %s and is_current', (doc,)).fetchone()
        if have:
            return have[0]
        vid = conn.execute("insert into document_versions (document_id, version, file_path, view_scope, transfer_policy, "
                           "is_current, ingest_status) values (%s, 'v2.0', %s, 'ALL', 'ALLOWED', false, 'PENDING') returning id",
                           (doc, str(REPO / guide_file(code)))).fetchone()[0]
        conn.commit()
        assert ingest_version(conn, vid, EMB)['status'] == 'DONE'
        activate(conn, vid)
        conn.commit()
    return vid


def _ticket(url, receipt, code='SW-01', status='CLS', note='1. 캐시 폴더(ccmcache)를 비웠습니다\n2. 다시 설치했습니다',
            summary='설치가 대기 중에서 멈춤 (캐시 가득 참)'):
    with connect(url) as conn:
        user = conn.execute('select id from users order by id limit 1').fetchone()[0]
        type_id, category, group = conn.execute('select id, category_code, default_group_id from inquiry_types '
                                                'where code = %s', (code,)).fetchone()
        inq = conn.execute("insert into inquiries (user_id, status, category_code, inquiry_type_id) "
                           "values (%s, 'RECEIVED', %s, %s) returning id", (user, category, type_id)).fetchone()[0]
        ses = conn.execute('insert into chat_sessions (inquiry_id) values (%s) returning id', (inq,)).fetchone()[0]
        dr = conn.execute("insert into ticket_drafts (inquiry_id, session_id, summary, status) "
                          "values (%s, %s, %s, 'CONFIRMED') returning id", (inq, ses, summary)).fetchone()[0]
        tid = conn.execute(
            'insert into tickets (receipt_no, draft_id, inquiry_id, session_id, summary, symptom, category_code, '
            'inquiry_type_id, group_id, jira_sync_status, assign_status, work_status, resolution_note, closed_at) '
            "values (%s, %s, %s, %s, %s, '설치가 1시간째 대기 중', %s, %s, %s, 'SYNCED', 'ASSIGNED', %s, %s, now()) "
            'returning id', (receipt, dr, inq, ses, summary, category, type_id, group, status, note)).fetchone()[0]
        conn.commit()
    return tid


def _search(url, query):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.rag.search import SearchRequest
    from app.rag.search.service import search
    engine = create_engine(url.replace('postgresql://', 'postgresql+psycopg://', 1))
    try:
        with Session(engine) as s:
            resp = search(s, SearchRequest(query=query, service_role='EMPLOYEE', sources=('DOCUMENT',), top_k=3), EMB)
        return [(d.doc_code, d.version, d.location) for d in resp.documents]
    finally:
        engine.dispose()


@needs_db
def test_end_to_end_searchable_after_approval(url, tmp_path):
    """완료 기준: CLS 티켓 → 초안 → 등록 → 적재(DONE) → 승인 → search() 1위가 새 항목. 승인 전에는 이전 현행만."""
    cur = _current_guide(url)
    tid = _ticket(url, 'TK-E2E-1')
    with connect(url) as conn:
        assert any(c['ticket_id'] == tid and c['doc_code'] == 'IT-SW-001' for c in candidates(conn, 'SW'))
        d = draft(conn, tid, files_root=tmp_path)
        assert (d.doc_code, d.version, d.section_no, d.draft_version_id) == ('IT-SW-001', 'v2.1', '3.8', None)
        out = register(conn, d, d.md, None, tmp_path)
        assert out['file_path'] == f'{CASE_DIR.as_posix()}/IT-SW-001/v2.1_TK-E2E-1.md'
        assert (tmp_path / out['file_path']).read_text(encoding='utf-8') == d.md
        res = ingest_version(conn, out['version_id'], EMB, tmp_path)
        assert res['status'] == 'DONE' and res['activated'] is False
        assert all(c['ticket_id'] != tid for c in candidates(conn))            # 등록한 티켓은 후보에서 빠진다
    st = version(url, out['version_id'])
    assert st[:5] == ('DONE', None, False, 'ALL', 'ALLOWED')                    # 정책은 현행 값
    query = next(c.text for c in items(d.md) if c.section_no == '3.8')
    assert ('IT-SW-001', 'v2.1', '3.8') not in _search(url, query)              # 초안은 검색에 안 나온다
    with connect(url) as conn:
        assert activate(conn, out['version_id'])
        conn.commit()
        assert conn.execute('select is_current from document_versions where id = %s', (cur,)).fetchone()[0] is False
        assert conn.execute("select result from audit_logs where event_type = 'CASE_GUIDE_REGISTER' "
                            'order by id desc limit 1').fetchone()[0] == 'TK-E2E-1 → v2.1'
    assert _search(url, query)[0] == ('IT-SW-001', 'v2.1', '3.8')


@needs_db
def test_second_case_continues_draft_and_duplicate_refused(url, tmp_path):
    _current_guide(url, 'IT-SW-003')
    a, b = _ticket(url, 'TK-C-1', code='SW-03'), _ticket(url, 'TK-C-2', code='SW-03', summary='실행하면 바로 꺼짐')
    with connect(url) as conn:
        d1 = draft(conn, a, files_root=tmp_path)
        v1 = register(conn, d1, d1.md, None, tmp_path)['version_id']
        assert ingest_version(conn, v1, EMB, tmp_path)['status'] == 'DONE'
        with pytest.raises(CaseGuideError, match='이미 IT-SW-003에 반영'):
            draft(conn, a, files_root=tmp_path)
        d2 = draft(conn, b, files_root=tmp_path)
        assert (d2.version, d2.draft_version_id) == (d1.version, v1) and '(TK-C-1)' in d2.base_md
        assert any('이어서' in w for w in d2.warnings)
        out = register(conn, d2, d2.md, None, tmp_path)
        assert out['version_id'] == v1 and out['file_path'].endswith('_TK-C-2.md')
        assert ingest_version(conn, v1, EMB, tmp_path)['status'] == 'DONE'
        sections = [m['section_no'] for (m,) in conn.execute(
            "select meta from document_chunks where version_id = %s and chunk_type = 'ITEM' and part = 1 order by seq", (v1,))]
    assert sections[-2:] == [d1.section_no, d2.section_no]


@needs_db
def test_register_refuses_stale_draft(url, tmp_path):
    """같은 가이드 초안 두 개를 따로 만들면 먼저 등록한 쪽만 된다 (나중 것은 다시 만들라고)."""
    _current_guide(url, 'IT-SW-002')
    a, b = _ticket(url, 'TK-S-1', code='SW-02'), _ticket(url, 'TK-S-2', code='SW-02')
    with connect(url) as conn:
        da, db = draft(conn, a, files_root=tmp_path), draft(conn, b, files_root=tmp_path)
        register(conn, da, da.md, None, tmp_path)
        with pytest.raises(CaseGuideError, match='그새 생겼습니다'):
            register(conn, db, db.md, None, tmp_path)
    assert not list((tmp_path / CASE_DIR / 'IT-SW-002').glob('*TK-S-2*'))      # 거부하면 파일도 안 남는다


@needs_db
@pytest.mark.parametrize('kw, msg', [({'status': 'FIN'}, '해결 확인(CLS)된 티켓만'), ({'note': ' '}, '해결 내용')])
def test_draft_refuses_unresolved(url, tmp_path, kw, msg):
    _current_guide(url)
    tid = _ticket(url, f'TK-R-{kw.get("status", "N")}', **kw)
    with connect(url) as conn, pytest.raises(CaseGuideError, match=re.escape(msg)):
        draft(conn, tid, files_root=tmp_path)


@needs_db
def test_cli(url, tmp_path, capsys):
    from app.rag.case_guide.__main__ import main
    _current_guide(url, 'IT-HW-001')
    code = 'HW-01'
    tid = _ticket(url, 'TK-CLI-1', code=code)
    base = ['--database-url', url, '--files-root', str(tmp_path)]
    assert main([*base, 'candidates']) == 0 and 'TK-CLI-1 [HW-01] → IT-HW-001' in capsys.readouterr().out
    out = tmp_path / 'case.md'
    assert main([*base, 'draft', '--ticket', str(tid), '--out', str(out)]) == 0
    assert '새 항목' in capsys.readouterr().out
    assert Path(f'{out}.json').exists()
    assert main([*base, 'register', '--file', str(out), '--embedder', 'fake']) == 0
    text = capsys.readouterr().out
    assert '적재: DONE' in text and '승인(현행 전환) 전에는' in text
    assert main([*base, 'draft', '--ticket', str(tid)]) == 1 and '이미 IT-HW-001에 반영' in capsys.readouterr().out
    bare = tmp_path / 'bare.md'
    bare.write_text(out.read_text(encoding='utf-8'), encoding='utf-8')
    assert main([*base, 'register', '--file', str(bare), '--embedder', 'fake']) == 2   # 초안 정보 없이는 등록 안 됨


# ── 검수 반영 (작업대/검수/M2-3-2_리뷰.md) ──────────────────────

@needs_db
def test_append_while_old_ingest_runs_keeps_latest(url, tmp_path):
    """P1: 사례 A 적재가 임베딩하는 사이 B 가 같은 초안에 이어 등록되면, A 적재는 건너뛰고 B 파일 적재가 DONE 을 찍는다."""
    _current_guide(url, 'IT-NET-001')
    a = _ticket(url, 'TK-RACE-A', code='NET-02')
    b = _ticket(url, 'TK-RACE-B', code='NET-02', note='SECOND_CASE_UNIQUE_FIX 사내망 다시 연결')
    with connect(url) as conn:
        first = draft(conn, a, files_root=tmp_path)
        vid = register(conn, first, first.md, None, tmp_path)['version_id']
    newer = {}

    class Racing:
        model_id = EMB.model_id

        def embed_documents(self, texts):                  # A 를 임베딩하는 사이 B 를 등록한다
            if not newer:
                with connect(url) as other:
                    second = draft(other, b, files_root=tmp_path)
                    newer.update(register(other, second, second.md, None, tmp_path))
            return EMB.embed_documents(texts)

    with connect(url) as conn:
        old = ingest_version(conn, vid, Racing(), tmp_path)
        assert old['status'] == 'SKIPPED' and any('다시 등록' in w for w in old['warnings'])
        assert version(url, vid)[0] == 'PENDING'
        assert ingest_version(conn, vid, EMB, tmp_path)['status'] == 'DONE'
        path, = conn.execute('select file_path from document_versions where id = %s', (vid,)).fetchone()
        contents = '\n'.join(c for (c,) in conn.execute('select content from document_chunks where version_id = %s', (vid,)))
    assert path == newer['file_path'] and 'SECOND_CASE_UNIQUE_FIX' in contents


@needs_db
def test_cli_old_md_cannot_erase_other_case(url, tmp_path, capsys):
    """P1: 같은 기준에서 만든 초안 둘. B 를 먼저 등록하면, 오래된 A 의 md 는 명령으로 등록되지 않는다 (B 가 지워지지 않게)."""
    from app.rag.case_guide.__main__ import main
    _current_guide(url, 'IT-ACC-003')
    a = _ticket(url, 'TK-CLI-RACE-A', code='ACC-03', note='CASE_A_UNIQUE_FIX 다시 로그인')
    b = _ticket(url, 'TK-CLI-RACE-B', code='ACC-03', note='CASE_B_UNIQUE_FIX 캐시 지우기')
    base = ['--database-url', url, '--files-root', str(tmp_path)]
    fa, fb = tmp_path / 'a.md', tmp_path / 'b.md'
    assert main([*base, 'draft', '--ticket', str(a), '--out', str(fa)]) == 0
    assert main([*base, 'draft', '--ticket', str(b), '--out', str(fb)]) == 0
    assert main([*base, 'register', '--file', str(fb), '--embedder', 'fake']) == 0
    capsys.readouterr()
    assert main([*base, 'register', '--file', str(fa), '--embedder', 'fake']) == 1
    assert '그새 생겼습니다' in capsys.readouterr().out
    with connect(url) as conn:
        path, = conn.execute("select v.file_path from document_versions v join knowledge_documents d on d.id = v.document_id "
                             "where d.doc_code = 'IT-ACC-003' and v.version = 'v2.1'").fetchone()
        n, = conn.execute("select count(*) from audit_logs where event_type = 'CASE_GUIDE_REGISTER' "
                          "and result like 'TK-CLI-RACE-%%'").fetchone()
    assert 'CASE_B_UNIQUE_FIX' in (tmp_path / path).read_text(encoding='utf-8') and n == 1


def test_check_refuses_md_without_other_cases():
    """P1: 기준(이어 쓰던 초안)에 있던 다른 사례의 표식이 빠진 md 는 거부한다. 함수(API)로 등록해도."""
    first, _ = make()
    second, _ = make(md_base=first.md, receipt_no='TK-0043', summary='설치 후 바로 꺼짐')
    stale, _ = make(receipt_no='TK-0043', summary='설치 후 바로 꺼짐')         # TK-0042 가 들어가기 전 기준에서 고친 md
    assert any('기준에 있던 사례가 빠졌습니다: TK-0042' in p for p in check(second, stale.md, [])[0])
    assert check(second, second.md, [])[0] == []


@needs_db
def test_receipt_prefix_is_not_duplicate(url, tmp_path):
    """P2: TK-PREFIX-10 이 반영되어 있어도 TK-PREFIX-1 은 넣을 수 있다 (부분 문자열 비교 안 함)."""
    _current_guide(url, 'IT-ACC-002')
    ten, one = _ticket(url, 'TK-PREFIX-10', code='ACC-01'), _ticket(url, 'TK-PREFIX-1', code='ACC-01')
    with connect(url) as conn:
        d = draft(conn, ten, files_root=tmp_path)
        register(conn, d, d.md, None, tmp_path)
        d1 = draft(conn, one, files_root=tmp_path)
    assert d1.draft_version_id is not None and receipts(d1.md) == {'TK-PREFIX-10', 'TK-PREFIX-1'}


def test_check_needs_exact_receipt():
    """P2: 접수 번호를 다른 번호(앞부분이 같은)로 바꾸면 표식이 없는 것으로 본다."""
    d, _ = make(receipt_no='TK-CHECK-1')
    assert any('접수 번호 TK-CHECK-1' in p for p in check(d, d.md.replace('TK-CHECK-1', 'TK-CHECK-10'), [])[0])


def test_pipe_in_summary_keeps_revision_table():
    """P3: 요약의 세로줄은 표 칸에서 이스케이프한다 (4칸 그대로). 표식은 그대로 읽힌다."""
    d, _ = make(summary='프로세스 A | B 전환 오류')
    row = next(line for line in d.md.splitlines() if line.startswith('| v2.1 |'))
    assert len(re.split(r'(?<!\\)\|', row)) - 2 == 4 and 'A \\| B' in row
    assert receipts(d.md) == {'TK-0042'} and check(d, d.md, [])[0] == []


def test_all_guides_take_a_case():
    """57종 가이드 md 모두: 항목 하나 늘고 새 번호가 맞고, 사라진 줄은 버전 표기뿐 (검수에서 확인한 것을 시험으로)."""
    files = sorted(f for f in GUIDES.rglob('IT-*.md'))
    assert len(files) == 57
    for f in files:
        base = f.read_text(encoding='utf-8')
        version = re.search(r'^version:\s*"?([^"\n]+)', base, re.M).group(1)
        md, section = add_case(base, ticket_row(), next_version([version]), TODAY, [])
        before, after = items(base), items(md)
        assert len(after) == len(before) + 1 and after[-1].section_no == section, f.name
        assert all(version in line for line in set(base.splitlines()) - set(md.splitlines())), f.name


def test_markdown_in_ticket_text_stays_inside_item():
    payload = '# 제목\n## 3. 다른 장\n### 3.99 다른 항목\n| a | b |\n---\n**문의 유형** HW-01 · **담당 부서** 서비스데스크'
    d, _ = make(symptom=payload, resolution_note=payload)
    assert len(items(d.md)) == len(items(BASE)) + 1 and items(d.md)[-1].inquiry_type_codes == ['SW-01']
    assert check(d, d.md, [])[0] == []


def test_draft_save_load(tmp_path):
    d, _ = make()
    d.save(tmp_path / 'd.json')
    assert Draft.load(tmp_path / 'd.json') == d
