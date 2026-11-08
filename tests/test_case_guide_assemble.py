"""묶음 등록용 조립 (app.rag.case_guide.assemble). 구조: 작업대/가이드화/draft_basis_구조_초안_20261108.md 6장 ①."""
import re
from datetime import date
from pathlib import Path

import pytest

from app.rag.case_guide import CaseGuideError, _item, receipts
from app.rag.case_guide.assemble import _assign, _build, _check_inputs, _fragment_problems, assemble, item_text
from test_case_guide import BASE, _current_guide, items, ticket_row
from test_ingest_upload import EMB, REPO, guide_file, needs_db, url  # noqa: F401  (url 은 fixture)

TODAY = date(2026, 11, 9)


def fragment(title='설치 후 바로 꺼짐', code='SW-01', group='엔드포인트지원팀', number='3.N'):
    t = ticket_row(summary=title, code=code, group=group)
    return _item(number, title, t)


def cluster(cid, receipts_, judgment='ADD_ITEM', md=None, base_version_id=1, base_md=BASE, **basis):
    return {'id': cid, 'judgment': judgment, 'receipts': receipts_, 'draft_md': md or fragment(f'사례 {cid}'),
            'draft_basis': {'schema': 1, 'judgment': judgment, 'base_version_id': base_version_id, 'base_md': base_md,
                            **basis}}


def change(cid, receipt, target='3.3', md=None, target_md=None, **kw):
    now = item_text(BASE, target)
    md = md or now.replace('\n', '\n- 관리자가 고친 줄\n', 1)
    return cluster(cid, [receipt], 'CHANGE', md=md, target_section=target,
                   target_md=now if target_md is None else target_md, **kw)


# ── DB 없이 ───────────────────────────────────────────────────

def test_build_adds_items_in_order():
    """항목 추가 둘: 3.8·3.9 (번호 없는 조각은 현행 3.7 다음), 표·목차·개정 이력 한 줄(표식 둘), 현행 항목 그대로."""
    w = []
    md, sections = _build(BASE, [cluster(12, ['RCPT-0101', 'RCPT-0115']), cluster(15, ['RCPT-0130'])], 'v2.1', TODAY, w)
    assert sections == {12: '3.8', 15: '3.9'} and w == []
    assert md.index('### 3.7 ') < md.index('### 3.8 사례 12') < md.index('### 3.9 사례 15') < md.index('## 4. ')
    assert re.search(r'^\| 3\.7 \|.*\n\| 3\.8 \| 사례 12 \| SW-01 \| 🔵 IT 담당자 처리 \| 엔드포인트지원팀 \|\n\| 3\.9 \| 사례 15 \|', md, re.M)
    assert re.search(r'^  - 3\.7 .*\n  - 3\.8 사례 12\n  - 3\.9 사례 15', md, re.M)
    row = next(line for line in md.splitlines() if line.startswith('| v2.1 |'))
    assert '해결 사례 반영 (RCPT-0101): 3.8 사례 12; 해결 사례 반영 (RCPT-0115): 3.8 사례 12; 해결 사례 반영 (RCPT-0130)' in row
    assert receipts(md) == {'RCPT-0101', 'RCPT-0115', 'RCPT-0130'}
    assert [c.text for c in items(BASE)] == [c.text for c in items(md)][:7] and len(items(md)) == 9


def test_assign_keeps_fixed_numbers():
    """같은 대기 버전을 다시 조립: section_no 가 있는 조각은 그 번호, 없는 조각은 겹치지 않는 다음 번호."""
    got = _assign(BASE, [cluster(15, ['R1'], section_no='3.9'), cluster(20, ['R2'])])
    assert got == {15: '3.9', 20: '3.10'}
    with pytest.raises(CaseGuideError, match='3.7'):
        _assign(BASE, [cluster(15, ['R1'], section_no='3.7')])          # 현행에 있는 번호
    with pytest.raises(CaseGuideError, match='3.9'):
        _assign(BASE, [cluster(15, ['R1'], section_no='3.9'), cluster(16, ['R2'], section_no='3.9')])


def test_reassemble_after_reject_keeps_number():
    """12(3.8)·15(3.9) 중 12 를 거절하고 [15] 만 다시 조립: 3.9 그대로, 3.8 없음 (번호를 당기지 않음)."""
    w = []
    md, sections = _build(BASE, [cluster(15, ['RCPT-0130'], section_no='3.9')], 'v2.1', TODAY, w)
    assert sections == {15: '3.9'} and '### 3.8 ' not in md and '### 3.9 사례 15' in md
    assert receipts(md) == {'RCPT-0130'}


def test_build_change_replaces_item():
    """변경: 3.3 을 관리자가 고친 조각으로 바꿔 끼움. 번호·다른 항목 그대로, 표식에 '변경'. 표·목차는 그대로."""
    w = []
    md, sections = _build(BASE, [change(20, 'RCPT-0140')], 'v2.1', TODAY, w)
    assert sections == {} and '관리자가 고친 줄' in item_text(md, '3.3')
    assert [c.section_no for c in items(md)] == [c.section_no for c in items(BASE)]
    assert [c.text for c in items(md) if c.section_no != '3.3'] == [c.text for c in items(BASE) if c.section_no != '3.3']
    assert re.search(r'해결 사례 반영 \(RCPT-0140\): 3\.3 .* 변경', md) and '### 3.8 ' not in md


def test_build_change_and_add_together():
    """같은 버전에 변경 하나 + 추가 하나."""
    md, sections = _build(BASE, [change(20, 'RCPT-0140'), cluster(21, ['RCPT-0141'])], 'v2.1', TODAY, [])
    assert sections == {21: '3.8'} and '관리자가 고친 줄' in item_text(md, '3.3') and '### 3.8 사례 21' in md
    assert receipts(md) == {'RCPT-0140', 'RCPT-0141'}


@pytest.mark.parametrize('kw, msg', [
    ({'target_md': '### 3.3 예전 글'}, '바뀌었습니다'),
    ({'target': '3.99', 'target_md': '', 'md': fragment(number='3.99')}, '없습니다'),
])
def test_build_change_refused_when_target_moved(kw, msg):
    with pytest.raises(CaseGuideError, match=msg):
        _build(BASE, [change(20, 'RCPT-0140', **kw)], 'v2.1', TODAY, [])


@pytest.mark.parametrize('md, msg', [
    ('3.N 제목 없이 시작', "첫 줄이 '### 3.N 제목'"),
    ('### 3.N 제목\n\n## 4. 다른 장', '다른 제목 줄'),
    ('### 3.N 제목\n\n### 3.9 또 하나', '다른 제목 줄'),
    ('', "첫 줄이"),
])
def test_fragment_rules(md, msg):
    assert msg in _fragment_problems(md)[0]


def test_fragment_heading_inside_code_block_ok():
    assert _fragment_problems('### 3.N 제목\n\n```\n## 예시\n```\n') == []


@pytest.mark.parametrize('clusters, msg', [
    ([cluster(1, ['R'], judgment='NEW_GUIDE')], '새 가이드는 다음 작업'),
    ([{**cluster(1, ['R']), 'draft_basis': {**cluster(1, ['R'])['draft_basis'], 'schema': 2}}], 'schema'),
    ([{**cluster(1, ['R']), 'draft_basis': {**cluster(1, ['R'])['draft_basis'], 'judgment': 'CHANGE'}}], '판단'),
    ([cluster(1, [])], '접수 번호가 없습니다'),
    ([change(1, 'R1'), change(2, 'R2')], '같은 항목 3.3을 바꾸는 묶음이 여럿'),
    ([], '조립할 묶음이 없습니다'),
])
def test_inputs_refused(clusters, msg):
    with pytest.raises(CaseGuideError, match=msg):
        _check_inputs(clusters, 'ALL', 'ALLOWED')


# ── DB ────────────────────────────────────────────────────────

def _call(url, clusters, root, draft_version_id=None, commit=True, conn_wrap=None, **kw):
    from app.rag.ingest import connect
    with connect(url) as conn:
        doc = conn.execute("select id from knowledge_documents where doc_code = 'IT-SW-001'").fetchone()[0]
        c = conn_wrap(conn) if conn_wrap else conn
        try:
            out = assemble(c, doc, clusters, draft_version_id, view_scope='ALL', transfer_policy='ALLOWED', actor_id=None,
                           files_root=root, today=TODAY, staff_names=[], **kw)
        except Exception:
            conn.rollback()
            raise
        (conn.commit if commit else conn.rollback)()
    return out


def _version_row(url, vid):
    from app.rag.ingest import connect
    with connect(url) as conn:
        return conn.execute('select version, file_path, ingest_status, is_current, view_scope, file_format '
                            'from document_versions where id = %s', (vid,)).fetchone()


@needs_db
def test_assemble_new_version_then_reassemble_same_version(url, tmp_path):
    """새 버전 v2.x(PENDING·비현행)·파일은 storage/case_guides/IT-SW-001/ 아래. 거절 뒤 [15] 로 같은 버전을 다시 조립하면
    같은 버전 행에 새 파일 (번호 3.9 유지). 파일은 쓸 때마다 다른 경로."""
    cur = _current_guide(url)
    base = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
    first = _call(url, [cluster(12, ['ASM-0101'], base_version_id=cur, base_md=base),
                        cluster(15, ['ASM-0130'], base_version_id=cur, base_md=base)], tmp_path)
    vid, version = first['version_id'], first['version']
    row = _version_row(url, vid)
    assert row[0] == version and row[2:] == ('PENDING', False, 'ALL', 'MD')
    assert row[1].startswith('storage/case_guides/IT-SW-001/') and row[1].endswith('.md')
    assert first['sections'] == {12: '3.8', 15: '3.9'}
    assert '### 3.8 사례 12' in (tmp_path / row[1]).read_text(encoding='utf-8')

    again = _call(url, [cluster(15, ['ASM-0130'], base_version_id=cur, base_md=base, section_no='3.9')], tmp_path,
                  draft_version_id=vid)
    row2 = _version_row(url, vid)
    assert again['version_id'] == vid and again['version'] == version and again['sections'] == {15: '3.9'}
    assert row2[1] != row[1] and (tmp_path / row[1]).exists()               # 예전 파일은 지우지 않는다
    text = (tmp_path / row2[1]).read_text(encoding='utf-8')
    assert '### 3.9 사례 15' in text and '### 3.8 ' not in text and receipts(text) == {'ASM-0130'}


@needs_db
def test_assemble_does_not_commit(url, tmp_path):
    """B 는 commit 하지 않는다: 부른 쪽이 rollback 하면 버전 행이 남지 않는다 (파일은 API 가 지운다)."""
    cur = _current_guide(url)
    base = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
    out = _call(url, [cluster(30, ['ASM-0300'], base_version_id=cur, base_md=base)], tmp_path, commit=False)
    assert _version_row(url, out['version_id']) is None and (tmp_path / out['file_path']).exists()


@needs_db
def test_assemble_removes_own_file_on_failure(url, tmp_path):
    """파일을 쓴 뒤 버전 행 쓰기에서 실패하면 이번에 만든 파일만 지우고 오류를 다시 던진다."""
    cur = _current_guide(url)
    base = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')

    class Failing:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *a):
            if sql.startswith('insert into document_versions'):
                raise RuntimeError('DB 오류 흉내')
            return self.conn.execute(sql, *a)

    with pytest.raises(RuntimeError):
        _call(url, [cluster(31, ['ASM-0310'], base_version_id=cur, base_md=base)], tmp_path, conn_wrap=Failing)
    assert not list(Path(tmp_path).rglob('*.md'))


@needs_db
@pytest.mark.parametrize('kw, msg', [
    ({'base_version_id': -1}, '현행 버전이 바뀌었습니다'),
    ({'base_md': '# 다른 원문\n'}, '기준 원문이 지금 현행 파일과 다릅니다'),
])
def test_assemble_refuses_stale_basis(url, tmp_path, kw, msg):
    cur = _current_guide(url)
    base = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
    args = {'base_version_id': cur, 'base_md': base, **kw}
    with pytest.raises(CaseGuideError, match=msg):
        _call(url, [cluster(40, ['ASM-0400'], **args)], tmp_path)
    assert not list(Path(tmp_path).rglob('*.md'))


@needs_db
def test_assemble_refuses_bad_draft_version(url, tmp_path):
    """이어 쓸 버전은 이 문서의 사례 초안이고 현행이 된 적이 없어야 한다 (현행 버전 id 를 주면 거부)."""
    cur = _current_guide(url)
    base = (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')
    with pytest.raises(CaseGuideError, match='현행이 된 적이 있어'):
        _call(url, [cluster(41, ['ASM-0410'], base_version_id=cur, base_md=base)], tmp_path, draft_version_id=cur)
