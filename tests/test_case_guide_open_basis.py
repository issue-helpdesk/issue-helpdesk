"""초안 기준 (app.rag.case_guide.open_basis): 워커가 묶음 초안을 만들 때 부른다. 구조 초안 6장 ③."""
import inspect
import re

import pytest

import app.rag.case_guide.open_basis as ob
from app.rag.case_guide import CaseGuideError, _item, _parse_text
from app.rag.case_guide.assemble import HEAD_RE, assemble, item_text
from app.rag.case_guide.open_basis import TODO, open_basis, skeleton, ticket_fragment
from test_case_guide import _current_guide, _ticket, ticket_row
from test_ingest_upload import REPO, guide_file, needs_db, url  # noqa: F401  (url 은 fixture)

CONTACT = '| 창구 | 연락처 | 이용 기준 |\n| --- | --- | --- |\n| ITssue 챗봇 | 포털 | 24시간 |'


def frag(title, code='NET-02', group='네트워크팀'):
    return _item('3.N', title, ticket_row(summary=title, code=code, group=group))


# ── DB 없이 ───────────────────────────────────────────────────

def test_skeleton_shape():
    """새 가이드 뼈대: v1.0·문서 번호 빈칸, 1·2장 자리 표시, 2장 바로가기·3장 항목 표·목차에 항목, 3.1부터,
    4·5장·부록은 제목만(청크 없음), 6장 문의처, 개정 이력 표 머리. 파서·청커가 읽는다."""
    md = skeleton('재택 프린터 연결 가이드', 'NET', 'VPN·네트워크', [frag('프린터가 안 잡힘'), frag('출력이 느림 | 무선')], CONTACT)
    meta, chunks = _parse_text(md)
    assert (meta.get('doc_no'), meta.get('version'), meta.get('title')) == ('', 'v1.0', '재택 프린터 연결 가이드')
    assert [(c.chunk_type, c.section_no) for c in chunks] == [('chapter', '1'), ('chapter', '2'), ('chapter', '3'),
                                                              ('item', '3.1'), ('item', '3.2'), ('chapter', '6')]
    assert md.count(f'\n{TODO}\n') == 2                                     # 1장·2장
    assert re.search(r'^\| 3\.2 \| 출력이 느림 \\\| 무선 \| NET-02 \| 🔵 IT 담당자 처리 \| 네트워크팀 \|$', md, re.M)
    assert re.search(r'^\| 프린터가 안 잡힘 \| 3\.1 \| 🔵 IT 담당자 처리 \|$', md, re.M)
    assert re.search(r'^  - 3\.1 프린터가 안 잡힘\n  - 3\.2 출력이 느림', md, re.M)
    assert '## 6. 문의처\n\n' + CONTACT in md and md.rstrip().endswith('| --- | --- | --- | --- |')
    assert item_text(md, '3.1').startswith('### 3.1 프린터가 안 잡힘')


def test_skeleton_without_contact_leaves_todo():
    md = skeleton('제목', 'NET', 'VPN·네트워크', [frag('a')], '')
    assert '## 6. 문의처\n\n' + TODO in md


def test_manual_candidate_has_no_draft():
    assert open_basis(None, 'MANUAL_CANDIDATE') == {'draft_basis': None, 'draft_md': None, 'warnings': []}


def test_never_commits():
    """워커 트랜잭션 안에서 부르므로 commit·rollback 을 하지 않는다 (구조 초안 6장)."""
    src = inspect.getsource(ob)
    assert '.commit(' not in src and '.rollback(' not in src


# ── DB ────────────────────────────────────────────────────────

def _conn(url):
    from app.rag.ingest import connect
    return connect(url)


def _doc_id(conn, code='IT-SW-001'):
    return conn.execute('select id from knowledge_documents where doc_code = %s', (code,)).fetchone()[0]


@needs_db
def test_add_basis_round_trip_with_assemble(url, tmp_path):
    """항목 추가: 기준 = 현행 버전 id·현행 원문, 번호는 비움. 이 기준과 조각으로 assemble 이 등록한다 (워커 → API 주고받기)."""
    cur = _current_guide(url)
    with _conn(url) as conn:
        out = open_basis(conn, 'ADD_ITEM', document_id=_doc_id(conn), receipts_=['OB-0001'])
        b = out['draft_basis']
        assert b == {'schema': 1, 'judgment': 'ADD_ITEM', 'base_version_id': cur,
                     'base_md': (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8'), 'section_no': None}
        assert out['draft_md'] is None and out['warnings'] == []
        res = assemble(conn, _doc_id(conn), [{'id': 1, 'judgment': 'ADD_ITEM', 'draft_md': frag('설치 후 꺼짐', 'SW-01'),
                                              'draft_basis': b, 'receipts': ['OB-0001']}], None,
                       view_scope='ALL', transfer_policy='ALLOWED', actor_id=None, files_root=tmp_path, staff_names=[])
        conn.rollback()
    assert res['sections'] == {1: '3.8'}


@needs_db
def test_change_basis_round_trip_with_assemble(url, tmp_path):
    """변경: target_md 는 assemble 이 비교하는 것과 같은 모양 (item_text). 관리자가 고친 조각으로 등록된다."""
    _current_guide(url)
    with _conn(url) as conn:
        b = open_basis(conn, 'CHANGE', document_id=_doc_id(conn), target_section='3.3')['draft_basis']
        assert b['target_section'] == '3.3' and b['target_md'] == item_text(b['base_md'], '3.3')
        edited = b['target_md'].replace('\n', '\n- 관리자가 고친 줄\n', 1)
        res = assemble(conn, _doc_id(conn), [{'id': 2, 'judgment': 'CHANGE', 'draft_md': edited, 'draft_basis': b,
                                              'receipts': ['OB-0002']}], None,
                       view_scope='ALL', transfer_policy='ALLOWED', actor_id=None, files_root=tmp_path, staff_names=[])
        text = (tmp_path / res['file_path']).read_text(encoding='utf-8')
        conn.rollback()
    assert '관리자가 고친 줄' in item_text(text, '3.3')


@needs_db
def test_receipt_already_in_current_warns(url, monkeypatch):
    """이미 현행에 반영된 접수 번호면 경고 (워커가 판단). 등록 때는 assemble 이 거부한다."""
    _current_guide(url)
    monkeypatch.setattr(ob, 'receipts', lambda md: {'OB-9'})               # 현행에 'OB-9' 표식이 있다고 보고
    with _conn(url) as conn:
        out = open_basis(conn, 'ADD_ITEM', document_id=_doc_id(conn), receipts_=['OB-9', 'OB-10'])
        conn.rollback()
    assert out['warnings'] == ['이미 IT-SW-001 현행에 반영된 접수 번호입니다: OB-9']


@needs_db
@pytest.mark.parametrize('kw, msg', [
    ({'judgment': 'CHANGE', 'target_section': '3.99'}, '항목 3.99이 없습니다'),
    ({'judgment': 'CHANGE'}, 'target_section'),
    ({'judgment': 'ADD_ITEM', 'document_id': None}, 'document_id'),
    ({'judgment': 'ADD_ITEM', 'document_id': -1}, '임직원용 가이드가 아닌'),
    ({'judgment': 'WHAT'}, '모르는 판단'),
])
def test_open_basis_refused(url, kw, msg):
    _current_guide(url)
    with _conn(url) as conn:
        args = {'document_id': _doc_id(conn), **kw}
        judgment = args.pop('judgment')
        with pytest.raises(CaseGuideError, match=msg):
            open_basis(conn, judgment, **args)
        conn.rollback()


@needs_db
def test_new_guide_copies_contact_from_current_guide(url):
    """새 가이드: 6장은 같은 분류(없으면 다른 분류) 현행 가이드의 6장 그대로. 기준은 base 없음·required 1~3장."""
    _current_guide(url)                                                     # IT-SW-001 (SW)
    want = re.search(r'^## 6\. 문의처[ \t]*\n(.*?)(?=^## )', (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8'),
                     re.M | re.S).group(1).strip('\n')
    with _conn(url) as conn:
        for category in ('SW', 'NET'):                                      # NET 은 현행 가이드가 없어 다른 분류에서
            out = open_basis(conn, 'NEW_GUIDE', category_code=category, title='새 가이드', fragments=[frag('사례')])
            assert out['draft_basis'] == {'schema': 1, 'judgment': 'NEW_GUIDE', 'base_version_id': None, 'base_md': None,
                                          'category_code': category, 'required': ['1', '2', '3']}
            assert '## 6. 문의처\n\n' + want + '\n' in out['draft_md'] and out['warnings'] == []
        conn.rollback()


@needs_db
@pytest.mark.parametrize('kw, msg', [
    ({'category_code': 'XX'}, '없는 분류'),
    ({'title': ' '}, '제목이 없습니다'),
    ({'fragments': []}, '조각이 없습니다'),
    ({'fragments': ['3.N 제목만']}, "조각 1: 조각 첫 줄"),
])
def test_new_guide_refused(url, kw, msg):
    with _conn(url) as conn:
        args = {'category_code': 'SW', 'title': '새 가이드', 'fragments': [frag('사례')], **kw}
        with pytest.raises(CaseGuideError, match=msg):
            open_basis(conn, 'NEW_GUIDE', **args)
        conn.rollback()


@needs_db
def test_ticket_fragment_for_sec(url):
    """SEC 직접 검토: 티켓 글 → '### 3.N 제목' 조각 (assemble 의 조각 약속을 지킨다). CLS 가 아니면 거부."""
    tid = _ticket(url, 'OB-SEC-1', code='SW-01', note='짧음')
    with _conn(url) as conn:
        fragment, warnings = ticket_fragment(conn, tid)
        conn.rollback()
    assert HEAD_RE.match(fragment.splitlines()[0]) and '#### 조치 방법' in fragment and '- 짧음' in fragment
    assert any('짧습니다' in w for w in warnings) and any('그대로 옮겼습니다' in w for w in warnings)
    fin = _ticket(url, 'OB-SEC-2', code='SW-01', status='FIN')
    with _conn(url) as conn, pytest.raises(CaseGuideError, match='CLS'):
        ticket_fragment(conn, fin)
