"""다시 맞추기 (app.rag.case_guide.rebase). 규칙은 case_guide/README.md 의 "다시 맞추기" 절."""
import inspect

import pytest

import app.rag.case_guide.rebase as rb
from app.rag.case_guide import CaseGuideError, _item
from app.rag.case_guide.assemble import assemble, item_text
from app.rag.case_guide.rebase import rebase
from test_case_guide import _current_guide, ticket_row
from test_ingest_upload import REPO, guide_file, needs_db, url  # noqa: F401  (url 은 fixture)


def current_md():
    return (REPO / guide_file('IT-SW-001')).read_text(encoding='utf-8')


def old_basis(judgment='ADD_ITEM', **kw):
    """예전 현행(가짜 버전 id -1)을 보고 만든 기준. 예전 원문은 지금 현행에서 3.3 한 줄만 다르다."""
    now = current_md()
    old_md = now.replace(item_text(now, '3.3'), item_text(now, '3.3').replace('\n', '\n- 예전 현행에만 있던 줄\n', 1), 1)
    b = {'schema': 1, 'judgment': judgment, 'base_version_id': -1, 'base_md': old_md}
    if judgment == 'CHANGE':
        b |= {'target_section': '3.3', 'target_md': item_text(old_md, '3.3')}
    else:
        b['section_no'] = '3.8'
    return b | kw


def frag(title='설치 후 꺼짐'):
    return _item('3.N', title, ticket_row(summary=title))


def test_never_writes():
    src = inspect.getsource(rb)
    assert '.commit(' not in src and '.rollback(' not in src and 'insert ' not in src and 'update ' not in src


@pytest.mark.parametrize('judgment', ['NEW_GUIDE', 'MANUAL_CANDIDATE', None])
def test_unsupported_judgment(judgment):
    with pytest.raises(CaseGuideError, match='다시 맞추지 않습니다'):
        rebase(None, 1, {'judgment': judgment, 'draft_basis': {}})


def test_basis_mismatch_refused():
    with pytest.raises(CaseGuideError, match='맞지 않습니다'):
        rebase(None, 1, {'judgment': 'CHANGE', 'draft_basis': old_basis('ADD_ITEM')})


# ── DB ────────────────────────────────────────────────────────

def _run(url, cluster):
    from app.rag.ingest import connect
    with connect(url) as conn:
        doc = conn.execute("select id from knowledge_documents where doc_code = 'IT-SW-001'").fetchone()[0]
        try:
            return rebase(conn, doc, cluster), doc
        finally:
            conn.rollback()


@needs_db
def test_add_item_gets_new_base_and_number_cleared(url, tmp_path):
    """항목 추가: 새 현행의 버전 id·원문, section_no 는 비움. 충돌 없음. 이 기준으로 assemble 이 등록한다."""
    cur = _current_guide(url)
    out, doc = _run(url, {'judgment': 'ADD_ITEM', 'draft_md': frag(), 'draft_basis': old_basis(), 'receipts': ['RB-1']})
    assert out['conflicts'] == [] and out['warnings'] == []
    assert out['draft_basis'] == {'schema': 1, 'judgment': 'ADD_ITEM', 'base_version_id': cur, 'base_md': current_md(),
                                  'section_no': None}
    from app.rag.ingest import connect
    with connect(url) as conn:
        res = assemble(conn, doc, [{'id': 1, 'judgment': 'ADD_ITEM', 'draft_md': frag(), 'draft_basis': out['draft_basis'],
                                    'receipts': ['RB-1']}], None, view_scope='ALL', transfer_policy='ALLOWED',
                       actor_id=None, files_root=tmp_path, staff_names=[])
        conn.rollback()
    assert res['sections'] == {1: '3.8'}


@needs_db
def test_change_target_changed_is_conflict(url):
    """변경: 새 현행의 3.3 이 만들 때와 다르면 충돌 (예전·새 원문). target_md 는 새 현행 것으로 (base_md 와 같은 버전).
    conflicts.revision 은 비워 둔다 (API 가 올린 draft_revision 으로 채움)."""
    cur = _current_guide(url)
    old = old_basis('CHANGE')
    out, _ = _run(url, {'judgment': 'CHANGE', 'draft_md': old['target_md'], 'draft_basis': old, 'receipts': ['RB-2']})
    b = out['draft_basis']
    assert b['base_version_id'] == cur and b['target_md'] == item_text(current_md(), '3.3')
    assert out['conflicts'] == b['conflicts']['items'] and b['conflicts']['revision'] is None
    c = out['conflicts'][0]
    assert (c['section'], c['kind']) == ('3.3', 'TARGET_CHANGED')
    assert '예전 현행에만 있던 줄' in c['old_md'] and c['new_md'] == b['target_md']


@needs_db
def test_change_target_same_no_conflict(url):
    """새 현행에서 그 항목이 그대로면 충돌 없음 (다른 곳만 바뀐 경우)."""
    _current_guide(url)
    now = current_md()
    old = old_basis('CHANGE', target_md=item_text(now, '3.3'))
    out, _ = _run(url, {'judgment': 'CHANGE', 'draft_md': old['target_md'], 'draft_basis': old, 'receipts': ['RB-3']})
    assert out['conflicts'] == [] and 'conflicts' not in out['draft_basis']


@needs_db
def test_change_target_missing_refused(url):
    """바꿀 항목이 새 현행에 없으면 충돌이 아니라 거부 (조각 저장으로 풀 수 없으므로)."""
    _current_guide(url)
    old = old_basis('CHANGE', target_section='3.99')
    with pytest.raises(CaseGuideError, match='3.99가 새 현행에 없습니다'):
        _run(url, {'judgment': 'CHANGE', 'draft_md': '', 'draft_basis': old, 'receipts': ['RB-4']})


@needs_db
def test_same_base_refused_and_receipt_warning(url, monkeypatch):
    """기준 버전이 이미 현행이면 다시 맞출 것이 없다. 새 현행에 같은 접수 번호 표식이 있으면 경고."""
    cur = _current_guide(url)
    with pytest.raises(CaseGuideError, match='같아 다시 맞출 것이 없습니다'):
        _run(url, {'judgment': 'ADD_ITEM', 'draft_basis': old_basis(base_version_id=cur), 'receipts': ['RB-5']})
    monkeypatch.setattr(rb, 'receipts', lambda md: {'RB-6'})
    out, _ = _run(url, {'judgment': 'ADD_ITEM', 'draft_basis': old_basis(), 'receipts': ['RB-6', 'RB-7']})
    assert out['warnings'] == ['이미 IT-SW-001 새 현행에 반영된 접수 번호입니다: RB-6 (등록 때 거부됩니다)']


def _after_first_rebase(revision=4):
    """첫 다시 맞추기 뒤의 기준: 조각은 예전 3.3(A) 으로 만들었고, 첫 다시 맞추기에서 현행 3.3(B) 과 충돌해
    target_md 는 B, 충돌(old_md A·new_md B)은 API 가 revision 을 채워 저장. 그 뒤 현행이 또 바뀜 (3.3 은 B 그대로)."""
    now = current_md()
    b_md = item_text(now, '3.3')
    a_md = b_md.replace('\n', '\n- 예전 현행에만 있던 줄\n', 1)
    return {'schema': 1, 'judgment': 'CHANGE', 'base_version_id': -1, 'base_md': '…', 'target_section': '3.3',
            'target_md': b_md, 'conflicts': {'revision': revision, 'items': [
                {'section': '3.3', 'kind': 'TARGET_CHANGED', 'message': '…', 'old_md': a_md, 'new_md': b_md}]}}, a_md


@needs_db
def test_unresolved_conflict_survives_second_rebase(url):
    """rebase 검수 1: 충돌 뒤 관리자가 조각을 저장하지 않은 채 (draft_revision 그대로) 현행이 또 바뀌어 다시 맞추면,
    대상 항목이 그대로여도 충돌이 남는다 — 조각이 만들어진 원문(A)과 새 현행(B)을 비교."""
    _current_guide(url)
    old, a_md = _after_first_rebase()
    out, _ = _run(url, {'judgment': 'CHANGE', 'draft_md': a_md, 'draft_basis': old, 'receipts': ['RB-8'],
                        'draft_revision': 4})
    assert len(out['conflicts']) == 1 and out['conflicts'][0]['old_md'] == a_md
    assert out['draft_basis']['conflicts']['items'] == out['conflicts']
    assert out['draft_basis']['conflicts']['items'] is not out['conflicts']        # 따로 (한쪽을 고쳐도 안 번짐)


@needs_db
def test_resolved_conflict_compares_with_last_base(url):
    """관리자가 조각을 저장해 draft_revision 이 올라간 뒤라면 풀린 것 — 직전 기준(B)과 비교해 그대로면 충돌 없음."""
    _current_guide(url)
    old, a_md = _after_first_rebase()
    out, _ = _run(url, {'judgment': 'CHANGE', 'draft_md': a_md, 'draft_basis': old, 'receipts': ['RB-9'],
                        'draft_revision': 5})
    assert out['conflicts'] == [] and 'conflicts' not in out['draft_basis']


@needs_db
def test_old_conflict_needs_draft_revision(url):
    _current_guide(url)
    old, a_md = _after_first_rebase()
    with pytest.raises(CaseGuideError, match='draft_revision 이 필요합니다'):
        _run(url, {'judgment': 'CHANGE', 'draft_md': a_md, 'draft_basis': old, 'receipts': ['RB-10']})


@needs_db
def test_reads_only(url):
    """DB 에는 SELECT 만 보낸다 (쓰기·commit·rollback 없음)."""
    from app.rag.ingest import connect
    _current_guide(url)

    class SelectOnly:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *a):
            assert sql.lstrip().lower().startswith('select'), sql
            return self.conn.execute(sql, *a)

        def commit(self):
            raise AssertionError('commit')

        def rollback(self):
            raise AssertionError('rollback')

    with connect(url) as conn:
        doc = conn.execute("select id from knowledge_documents where doc_code = 'IT-SW-001'").fetchone()[0]
        old, a_md = _after_first_rebase()
        rebase(SelectOnly(conn), doc, {'judgment': 'CHANGE', 'draft_md': a_md, 'draft_basis': old, 'receipts': ['RB-11'],
                                       'draft_revision': 4})
        conn.rollback()


@pytest.mark.parametrize('conflicts, rev, msg', [
    ('bad', 4, 'conflicts·items'),
    ({'revision': 4, 'items': [None]}, 4, 'old_md 가 없음'),
    ({'revision': 4, 'items': {'section': '3.3'}}, 4, 'conflicts·items'),
    ({'revision': 4, 'items': []}, 4, 'conflicts·items'),
    ({'revision': 4, 'items': [{'section': '3.3', 'kind': 'TARGET_CHANGED'}]}, 4, 'old_md 가 없음'),
    ({'revision': 4, 'items': [{'section': '3.9', 'old_md': 'x'}]}, 4, '항목 3.3 의 old_md 가 없음'),
    ({'revision': '4', 'items': [{'section': '3.3', 'old_md': 'x'}]}, 4, '정수가 아님'),
])
def test_bad_conflict_data_refused(conflicts, rev, msg):
    """#368 재검수 1: 예전 충돌 기록의 모양이 틀리면 일반 예외가 아니라 CaseGuideError, 안 풀린 충돌에 old_md 가 없으면
    풀렸다고 추정하지 않고 거부."""
    with pytest.raises(CaseGuideError, match=msg):
        rb._unresolved({'conflicts': conflicts}, rev, '3.3')


def test_unresolved_returns_original_or_none():
    item = {'section': '3.3', 'old_md': 'A'}
    assert rb._unresolved({'conflicts': {'revision': 4, 'items': [item]}}, 4, '3.3') == 'A'
    assert rb._unresolved({'conflicts': {'revision': 4, 'items': [item]}}, 5, '3.3') is None      # 저장해 풀림
    assert rb._unresolved({'conflicts': {'revision': None, 'items': [item]}}, 4, '3.3') is None   # 번호 안 채움
    assert rb._unresolved({}, None, '3.3') is None
