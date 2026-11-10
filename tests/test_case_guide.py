"""해결 사례 가이드화(app.rag.case_guide, M2-3-2)를 검사한다.

앞부분은 DB 없이 돈다 (md 고치기·검사·민감정보 경고). 뒷부분은 test_ingest_upload.py 와 같이 TEST_DATABASE_URL 이
localhost 일 때만, 무작위 이름의 전용 DB 에서 CLS 티켓 → 초안 → 등록 → 적재 → 승인 → 검색까지 본다.
    TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres uv run pytest tests/test_case_guide.py
"""
import re
from datetime import date
from pathlib import Path

import pytest

from app.rag.case_guide import (CASE_DIR, CaseGuideError, Draft, _added_lines, _base_md, _parse_text, add_case, candidates,
                                check, draft, next_version, receipts, register, sensitive_warnings)
from app.rag.ingest import GUIDES, activate, connect
from app.rag.ingest.upload import ingest_version
from app.rag.parser import parse
from app.rag.parser.models import Element
from app.rag.parser.to_md import to_guide_md
from test_ingest_upload import EMB, REPO, guide_file, needs_db, url, version  # noqa: F401  (url 은 fixture)

BASE = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
TODAY = date(2026, 10, 29)
POLICY = {'view_scope': 'ALL', 'transfer_policy': 'ALLOWED'}         # 관리자가 고른 값 (시험 가이드의 현행과 같다)
POLICY_ARGS = ['--view-scope', 'ALL', '--transfer-policy', 'ALLOWED']


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
    assert re.search(r'^\| 3\.7 \|.*\|\n\| 3\.8 \| 설치가 "대기 중"에서 멈추고 캐시 폴더가 가득 참 \| SW-01 \| 🔵 IT 담당자 처리 \| '
                     r'엔드포인트지원팀 \|$', d.md, re.M)              # 3장 항목 표 끝에 한 줄
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
    assert re.search(r'^\| 3\.8 \| 설치가 .*\|\n\| 3\.9 \| 설치 후 바로 꺼짐 \|', second.md, re.M)   # 항목 표도 이어서


def test_item_table_unknown_shape_left_alone():
    """3장 항목 표 머리줄이 가이드 5열과 다르거나 표가 없으면 표는 고치지 않고 경고. 항목·목차·개정 이력은 그대로 더한다."""
    head = '| 번호 | 제목 | 문의 유형 | 처리 구분 | 담당 부서 |'
    assert head in BASE
    other = BASE.replace(head, '| 번호 | 제목 | 문의 유형 | 담당 부서 |', 1)
    d, warnings = make(md_base=other)
    assert warnings == ['3장 항목 표 머리줄(번호 | 제목 | 문의 유형 | 담당 부서)이 예상과 달라 표는 고치지 않았습니다']
    assert not re.search(r'^\| 3\.8 \|', d.md, re.M) and d.section_no == '3.8' and len(items(d.md)) == len(items(BASE)) + 1
    table = re.search(r'^\| 번호 \|.*\n(?:\|.*\n)*', BASE, re.M).group(0)
    d, warnings = make(md_base=BASE.replace(table, '', 1))
    assert warnings == ['3장 항목 표를 찾지 못해 표는 고치지 않았습니다'] and d.section_no == '3.8'
    assert check(d, d.md, [])[0] == []


TABLE_HEAD = '| 번호 | 제목 | 문의 유형 | 처리 구분 | 담당 부서 |'


def _first_table_end(md):
    """BASE 의 3장 항목 표 마지막 줄 (그 뒤에 무엇을 끼워 넣는 시험용)."""
    return re.search(r'^\| 번호 \|.*\n(?:\|.*\n)*', md, re.M).end()


@pytest.mark.parametrize('gap', ['\n', '\n   \n'])
def test_item_table_ends_at_blank_line(gap):
    """PR #349 검수: 빈 줄(공백만 든 빈 줄도) 뒤의 다른 표는 다른 표다 (md 파서도 따로 읽는다). 항목 표에만 한 줄."""
    at = _first_table_end(BASE)
    base = BASE[:at] + gap + '| 참고 | 설명 |\n| --- | --- |\n| a | b |\n' + BASE[at:]
    d, warnings = make(md_base=base)
    assert warnings == []
    assert re.search(r'^\| 3\.7 \|.*\|\n\| 3\.8 \| 설치가', d.md, re.M) and '| a | b |\n\n' in d.md + '\n'
    assert not re.search(r'^\| a \| b \|\n\| 3\.8', d.md, re.M)


def test_item_table_skips_code_block():
    """PR #349 검수: 3장 앞 코드 블록 안의 같은 모양 표 예시는 건너뛰고 실제 항목 표에 한 줄."""
    chapter = re.search(r'^## 3\. .*\n', BASE, re.M).end()
    example = f'\n```\n{TABLE_HEAD}\n| --- | --- | --- | --- | --- |\n```\n'
    d, warnings = make(md_base=BASE[:chapter] + example + BASE[chapter:])
    assert warnings == [] and example in d.md                       # 예시는 그대로
    assert re.search(r'^\| 3\.7 \|.*\|\n\| 3\.8 \| 설치가', d.md, re.M)


def test_item_table_crlf():
    """줄 끝이 CRLF 인 md 도 표를 찾고 같은 줄 끝으로 한 줄을 넣는다."""
    d, warnings = make(md_base=BASE.replace('\n', '\r\n'))
    assert not [w for w in warnings if '항목 표' in w]
    assert re.search(r'^\| 3\.7 \|.*\|\r\n\| 3\.8 \| 설치가 .*\|\r\n', d.md, re.M)


def test_item_table_mismatch_warned_for_old_draft():
    """이 기능 전에 만든 초안(표에 3.8 줄 없음)에 이어 쓰면 3.9 줄만 더하고, 빠진 번호를 경고한다 (지난 줄은 채우지 않음)."""
    first, _ = make()
    old = re.sub(r'^\| 3\.8 \|.*\n', '', first.md, flags=re.M)
    second, warnings = make(md_base=old, receipt_no='TK-0043', summary='설치 후 바로 꺼짐')
    assert warnings == ['3장 항목 표와 항목 번호가 다릅니다 (표에 없음 3.8). 표를 확인해 주세요']
    assert re.search(r'^\| 3\.7 \|.*\|\n\| 3\.9 \| 설치 후 바로 꺼짐', second.md, re.M)


def test_item_table_odd_row_does_not_crash():
    """표 안에 세로줄 하나뿐인 줄이 있어도 멈추지 않고 한 줄을 더한다 (번호가 맞지 않으니 경고)."""
    at = _first_table_end(BASE)
    d, warnings = make(md_base=BASE[:at] + '|\n' + BASE[at:])
    assert re.search(r'^\|\n\| 3\.8 \| 설치가', d.md, re.M) and len(warnings) == 1 and '항목에 없음' in warnings[0]


def test_item_table_row_escapes_pipe_and_empty_cells():
    """표 줄도 세로줄을 이스케이프해 5칸 그대로. 문의 유형·담당 부서가 없으면 빈칸."""
    d, _ = make(summary='프로세스 A | B 전환 오류', code=None, group=None)
    row = next(line for line in d.md.splitlines() if line.startswith('| 3.8 |'))
    assert len(re.split(r'(?<!\\)\|', row)) - 2 == 5 and 'A \\| B' in row and row.endswith('| 🔵 IT 담당자 처리 |  |')


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

def _current_guide(url, code='IT-SW-001', fmt='md'):
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
                           (doc, str(REPO / guide_file(code, fmt)))).fetchone()[0]
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
        out = register(conn, d, d.md, None, tmp_path, **POLICY)
        assert out['file_path'] == f'{CASE_DIR.as_posix()}/IT-SW-001/v2.1_TK-E2E-1.md'
        assert (tmp_path / out['file_path']).read_text(encoding='utf-8') == d.md
        res = ingest_version(conn, out['version_id'], EMB, tmp_path)
        assert res['status'] == 'DONE' and res['activated'] is False
        assert all(c['ticket_id'] != tid for c in candidates(conn))            # 등록한 티켓은 후보에서 빠진다
    st = version(url, out['version_id'])
    assert st[:5] == ('DONE', None, False, 'ALL', 'ALLOWED')                    # 정책은 관리자가 고른 값
    assert not any('현행(' in w for w in out['warnings'])                       # 현행과 같으면 경고 없음
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
        v1 = register(conn, d1, d1.md, None, tmp_path, **POLICY)['version_id']
        assert ingest_version(conn, v1, EMB, tmp_path)['status'] == 'DONE'
        with pytest.raises(CaseGuideError, match='이미 IT-SW-003에 반영'):
            draft(conn, a, files_root=tmp_path)
        d2 = draft(conn, b, files_root=tmp_path)
        assert (d2.version, d2.draft_version_id) == (d1.version, v1) and '(TK-C-1)' in d2.base_md
        assert any('이어서' in w for w in d2.warnings)
        out = register(conn, d2, d2.md, None, tmp_path, **POLICY)
        assert out['version_id'] == v1 and out['file_path'].endswith('_TK-C-2.md')
        assert ingest_version(conn, v1, EMB, tmp_path)['status'] == 'DONE'
        sections = [m['section_no'] for (m,) in conn.execute(
            "select meta from document_chunks where version_id = %s and chunk_type = 'ITEM' and part = 1 order by seq", (v1,))]
    assert sections[-2:] == [d1.section_no, d2.section_no]


@needs_db
def test_register_uses_chosen_policy(url, tmp_path):
    """docs/10 1.3: 해결 사례를 Guide 로 쓸 때 정책은 관리자가 고른다. 현행과 다르면 경고, 이어 쓰기도 고른 값으로 바꾼다.
    없는 값은 파일을 쓰기 전에 거부한다."""
    _current_guide(url, 'IT-HW-002')
    a, b = _ticket(url, 'TK-P-1', code='HW-05'), _ticket(url, 'TK-P-2', code='HW-05', summary='교체 신청 뒤 연락 없음')
    with connect(url) as conn:
        d1 = draft(conn, a, files_root=tmp_path)
        with pytest.raises(CaseGuideError, match='없는 값입니다: 전송 정책 OPEN'):
            register(conn, d1, d1.md, None, tmp_path, view_scope='ALL', transfer_policy='OPEN')
        assert not (tmp_path / CASE_DIR).exists()
        out = register(conn, d1, d1.md, None, tmp_path, view_scope='AGENT', transfer_policy='BLOCKED')
        assert any('현행(ALL·ALLOWED)과 다르게 AGENT·BLOCKED' in w for w in out['warnings'])
        assert version(url, out['version_id'])[3:5] == ('AGENT', 'BLOCKED')
        d2 = draft(conn, b, files_root=tmp_path)                                 # 같은 초안에 이어 쓰기
        again = register(conn, d2, d2.md, None, tmp_path, view_scope='ADMIN', transfer_policy='MASKED')
    assert again['version_id'] == out['version_id']                              # 초안 값·현행 값 어느 쪽도 아닌 고른 값
    assert version(url, out['version_id'])[3:5] == ('ADMIN', 'MASKED')


@needs_db
def test_register_refuses_stale_draft(url, tmp_path):
    """같은 가이드 초안 두 개를 따로 만들면 먼저 등록한 쪽만 된다 (나중 것은 다시 만들라고)."""
    _current_guide(url, 'IT-SW-002')
    a, b = _ticket(url, 'TK-S-1', code='SW-02'), _ticket(url, 'TK-S-2', code='SW-02')
    with connect(url) as conn:
        da, db = draft(conn, a, files_root=tmp_path), draft(conn, b, files_root=tmp_path)
        register(conn, da, da.md, None, tmp_path, **POLICY)
        with pytest.raises(CaseGuideError, match='그새 생겼습니다'):
            register(conn, db, db.md, None, tmp_path, **POLICY)
    assert not list((tmp_path / CASE_DIR / 'IT-SW-002').glob('*TK-S-2*'))      # 거부하면 파일도 안 남는다


@needs_db
@pytest.mark.parametrize('kw, msg', [({'status': 'FIN'}, '해결 확인(CLS)된 티켓만'), ({'note': ' '}, '해결 내용')])
def test_draft_refuses_unresolved(url, tmp_path, kw, msg):
    _current_guide(url)
    tid = _ticket(url, f'TK-R-{kw.get("status", "N")}', **kw)
    with connect(url) as conn, pytest.raises(CaseGuideError, match=re.escape(msg)):
        draft(conn, tid, files_root=tmp_path)


@needs_db
def test_reopened_ticket_warns_without_text(url, tmp_path, capsys):
    """다시 처리(FIN→WIP)된 접수는 횟수·이력 위치만 경고하고, 앞선 처리 결과·남은 증상 원문은 경고·본문·초안 정보에 넣지 않는다.

    ITSSUE·JIRA 어느 쪽에서 온 이력이든 세고, 다른 티켓의 이력은 섞지 않는다. 명령 draft 출력에도 나온다 (PR #269 검수 3).
    """
    from app.rag.case_guide.__main__ import main
    _current_guide(url, 'IT-NET-003')                                        # 다른 시험의 사례 초안이 없는 가이드
    note = '1. 스위치 포트를 바꿨습니다\n2. 다시 연결했습니다'
    once, twice = _ticket(url, 'TK-RO-0', code='NET-03', note=note), _ticket(url, 'TK-RO-2', code='NET-03', note=note)
    old = ['OLD_FIX_A_MARK', 'OLD_FIX_B_MARK', 'LEFT_SYMPTOM_1_MARK', 'LEFT_SYMPTOM_2_MARK']
    with connect(url) as conn:
        steps = [(None, 'RDY', 'JIRA', None, None), ('RDY', 'WIP', 'ITSSUE', None, None),
                 ('WIP', 'FIN', 'ITSSUE', None, old[0]), ('FIN', 'WIP', 'ITSSUE', old[2], None),
                 ('WIP', 'FIN', 'JIRA', None, old[1]), ('FIN', 'WIP', 'JIRA', old[3], None),       # Jira 에서 되돌림
                 ('WIP', 'FIN', 'ITSSUE', None, note), ('FIN', 'CLS', 'ITSSUE', None, None)]
        for frm, to, source, reason, result in steps:
            conn.execute('insert into ticket_status_history (ticket_id, from_status, to_status, source, reason, '
                         'resolution_note) values (%s, %s, %s, %s, %s, %s)', (twice, frm, to, source, reason, result))
        for frm, to in [(None, 'RDY'), ('RDY', 'WIP'), ('WIP', 'FIN'), ('FIN', 'CLS')]:
            conn.execute("insert into ticket_status_history (ticket_id, from_status, to_status, source) "
                         "values (%s, %s, %s, 'ITSSUE')", (once, frm, to))
        conn.commit()
        plain = draft(conn, once, files_root=tmp_path)                       # 다른 티켓(twice)의 되돌림은 안 센다
        again = draft(conn, twice, files_root=tmp_path)
    assert not any('다시 처리' in w for w in plain.warnings)
    want = (f'다시 처리된 접수입니다 (재처리 2회). 앞선 처리 결과·남은 증상은 TK-RO-2의 TK-08 이력(티켓 {twice})에서 '
            '확인하세요. 본문에는 마지막 처리 결과만 넣었습니다')
    assert [w for w in again.warnings if '다시 처리' in w] == [want]
    assert '스위치 포트를 바꿨습니다' in again.md                                # 본문은 마지막 처리 결과 그대로
    saved = tmp_path / 'again.json'
    again.save(saved)
    assert Draft.load(saved).warnings == again.warnings                       # 저장했다 불러도 경고가 남는다
    for text in ['\n'.join(again.warnings), again.md, saved.read_text(encoding='utf-8')]:
        assert not any(m in text for m in old)                                # 앞선 처리 결과·남은 증상 원문 없음
    out = tmp_path / 'again.md'
    assert main(['--database-url', url, '--files-root', str(tmp_path), 'draft', '--ticket', str(twice),
                 '--out', str(out)]) == 0
    printed = capsys.readouterr().out
    assert f'[경고] {want}' in printed and not any(m in printed for m in old)
    assert not any(m in Path(f'{out}.json').read_text(encoding='utf-8') for m in old)


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
    text = capsys.readouterr().out
    assert '새 항목' in text and '현행 정책: 열람 범위 ALL · 전송 정책 ALLOWED' in text   # 관리자가 고를 때 참고
    assert Path(f'{out}.json').exists()
    with pytest.raises(SystemExit):                                              # 정책은 반드시 고른다 (docs/10 1.3)
        main([*base, 'register', '--file', str(out), '--embedder', 'fake'])
    capsys.readouterr()
    assert main([*base, 'register', '--file', str(out), '--embedder', 'fake', *POLICY_ARGS]) == 0
    text = capsys.readouterr().out
    assert '적재: DONE' in text and '승인(현행 전환) 전에는' in text
    assert main([*base, 'draft', '--ticket', str(tid)]) == 1 and '이미 IT-HW-001에 반영' in capsys.readouterr().out
    bare = tmp_path / 'bare.md'
    bare.write_text(out.read_text(encoding='utf-8'), encoding='utf-8')
    assert main([*base, 'register', '--file', str(bare), '--embedder', 'fake', *POLICY_ARGS]) == 2   # 초안 정보 없이는 등록 안 됨


# ── 검수 반영 회귀 시험 ──────────────────────

@needs_db
def test_append_while_old_ingest_runs_keeps_latest(url, tmp_path):
    """P1: 사례 A 적재가 임베딩하는 사이 B 가 같은 초안에 이어 등록되면, A 적재는 건너뛰고 B 파일 적재가 DONE 을 찍는다."""
    _current_guide(url, 'IT-NET-001')
    a = _ticket(url, 'TK-RACE-A', code='NET-02')
    b = _ticket(url, 'TK-RACE-B', code='NET-02', note='SECOND_CASE_UNIQUE_FIX 사내망 다시 연결')
    with connect(url) as conn:
        first = draft(conn, a, files_root=tmp_path)
        vid = register(conn, first, first.md, None, tmp_path, **POLICY)['version_id']
    newer = {}

    class Racing:
        model_id = EMB.model_id

        def embed_documents(self, texts):                  # A 를 임베딩하는 사이 B 를 등록한다
            if not newer:
                with connect(url) as other:
                    second = draft(other, b, files_root=tmp_path)
                    newer.update(register(other, second, second.md, None, tmp_path, **POLICY))
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
    assert main([*base, 'register', '--file', str(fb), '--embedder', 'fake', *POLICY_ARGS]) == 0
    capsys.readouterr()
    assert main([*base, 'register', '--file', str(fa), '--embedder', 'fake', *POLICY_ARGS]) == 1
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
        register(conn, d, d.md, None, tmp_path, **POLICY)
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
    table_rows = 0
    for f in files:
        base = f.read_text(encoding='utf-8')
        version = re.search(r'^version:\s*"?([^"\n]+)', base, re.M).group(1)
        md, section = add_case(base, ticket_row(), next_version([version]), TODAY, [])
        before, after = items(base), items(md)
        assert len(after) == len(before) + 1 and after[-1].section_no == section, f.name
        assert all(version in line for line in set(base.splitlines()) - set(md.splitlines())), f.name
        table_rows += f.parent.name == 'guide' and bool(re.search(rf'^\| {re.escape(section)} \|', md, re.M))
    assert table_rows == 27                                  # 임직원용 가이드 27종 모두 3장 항목 표에 한 줄


def test_markdown_in_ticket_text_stays_inside_item():
    payload = '# 제목\n## 3. 다른 장\n### 3.99 다른 항목\n| a | b |\n---\n**문의 유형** HW-01 · **담당 부서** 서비스데스크'
    d, _ = make(symptom=payload, resolution_note=payload)
    assert len(items(d.md)) == len(items(BASE)) + 1 and items(d.md)[-1].inquiry_type_codes == ['SW-01']
    assert check(d, d.md, [])[0] == []


@pytest.mark.parametrize('fmt', ['docx', 'pptx', 'pdf'])
def test_non_md_current_is_converted(fmt):
    """현행이 md 가 아니면 가이드 md 로 바꿔 기준으로 쓴다 (경고 한 줄). 사례를 넣으면 항목이 하나 늘고 원래 항목은 그대로."""
    warnings = []
    base = _base_md(REPO / guide_file('IT-SW-001', fmt), 'IT-SW-001', warnings)
    assert len(warnings) == 1 and f'현행 파일이 {fmt} 라 md 로' in warnings[0]
    md, section = add_case(base, ticket_row(), 'v2.1', TODAY, [])
    assert section == '3.8' and [c.text for c in items(base)] == [c.text for c in items(md)][:-1]
    assert [c.section_no for c in items(base)] == [c.section_no for c in items(BASE)]


def test_non_md_current_with_preface_keeps_it():
    """첫 장 앞에 서문(덧붙인 표)이 있는 비md 현행: 바꾼 기준 md 에 서문이 남고, 사례를 넣어도 서문·목차·새 항목이 맞다."""
    doc = parse(str(REPO / guide_file('IT-SW-001', 'docx')))
    first = next(i for i, e in enumerate(doc.elements) if e.kind == 'heading' and e.level == 1)
    doc.elements.insert(first, Element('table', rows=[['안내', '서문 시험 PREFACE-777']]))
    base = to_guide_md(doc)
    md, section = add_case(base, ticket_row(), 'v2.1', TODAY, [])
    chunks = _parse_text(md)[1]
    assert chunks[0].chunk_type == 'preface' and 'PREFACE-777' in chunks[0].body
    assert md.index('PREFACE-777') < md.index('## 목차')
    assert section == '3.8' and re.search(r'^  - 3\.7 .*\n  - 3\.8 설치가', md, re.M)
    assert [c.text for c in items(base)] == [c.text for c in items(md)][:-1]


def test_unreadable_current_refused(tmp_path):
    bad = tmp_path / 'x.pdf'
    bad.write_bytes(b'not a pdf')
    with pytest.raises(CaseGuideError, match='읽지 못했습니다'):
        _base_md(bad, 'IT-SW-001', [])


@needs_db
@pytest.mark.parametrize('code, fmt', [('IT-NET-002', 'docx'), ('IT-SEC-001', 'pptx'), ('IT-SYS-001', 'pdf')])
def test_non_md_current_end_to_end(url, tmp_path, code, fmt):
    """현행이 docx·pptx·pdf 인 가이드: 초안(md) → 등록(md 파일) → 적재 DONE, 새 항목이 청크에 있다.
    가이드는 이 파일의 다른 시험이 초안을 만들지 않는 것 (같은 DB 에 승인 전 초안이 있으면 그 초안에 이어 쓴다)."""
    _current_guide(url, code, fmt)
    tid = _ticket(url, f'TK-FMT-{fmt}')
    with connect(url) as conn:
        d = draft(conn, tid, doc_code=code, files_root=tmp_path)
        assert any(f'현행 파일이 {fmt} 라' in w for w in d.warnings)
        out = register(conn, d, d.md, None, tmp_path, **POLICY)
        assert out['file_path'].endswith('.md')
        assert ingest_version(conn, out['version_id'], EMB, tmp_path)['status'] == 'DONE'
        keys = [k for (k,) in conn.execute("select unit_key from document_chunks where version_id = %s "
                                           "and chunk_type = 'ITEM'", (out['version_id'],))]
    assert f'{code}@{d.version}/item:{d.section_no}' in keys


def test_draft_save_load(tmp_path):
    d, _ = make()
    d.save(tmp_path / 'd.json')
    assert Draft.load(tmp_path / 'd.json') == d


# ── 조사 (받침에 맞게) ─────────────────────────────────────────

@pytest.mark.parametrize('word, pair, want', [
    ('네트워크팀', '이/가', '네트워크팀이'), ('서비스데스크', '이/가', '서비스데스크가'),
    ('3.4', '이/가', '3.4가'), ('3.1', '이/가', '3.1이'), ('v2.0', '은/는', 'v2.0은'), ('v2.3', '은/는', 'v2.3은'),
    ('TK-0042', '은/는', 'TK-0042는'), ('IT-ACC-001-M', '을/를', 'IT-ACC-001-M을'), ('SW-01', '을/를', 'SW-01을'),
    ('NET-02', '을/를', 'NET-02를'), ('ALLOWED', '으로/로', 'ALLOWED로'), ('분류 이름', '은/는', '분류 이름은'),
    ('서울', '으로/로', '서울로'), ('3.6', '으로/로', '3.6으로'), ('"해결 사례 반영 (TK-1)"', '을/를', '"해결 사례 반영 (TK-1)"을'),
    ('Team', '이/가', 'Team이'), ('ABC', '이/가', 'ABC가'), ('…', '이/가', '…이(가)'),
])
def test_josa(word, pair, want):
    """받침 따라 조사. 숫자·영문은 읽는 소리 (1 일·4 사·M 엠), 끝의 괄호·따옴표는 건너뜀, 모르면 둘 다."""
    from app.rag.case_guide import josa
    assert josa(word, pair) == want


@pytest.mark.parametrize('group, want', [('서비스데스크', '서비스데스크가 확인합니다'),
                                         ('네트워크팀', '네트워크팀이 확인합니다'), ('', '담당자가 확인합니다')])
def test_item_who_checks_josa(group, want):
    """가이드 본문 '해결되지 않으면' 줄: 담당 부서 이름 받침에 맞는 조사 (서비스데스크이 X)."""
    from app.rag.case_guide import _item
    assert want in _item('3.N', '제목', ticket_row(group=group))
