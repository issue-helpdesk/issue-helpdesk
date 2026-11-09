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


@pytest.mark.parametrize('title', ['회사 "VPN" 가이드', r'C:\경로\가이드', "작은 '따옴표' 가이드", '[긴급] 접속 가이드'])
def test_skeleton_title_round_trips(title):
    """PR #361 검수 1: 머리말 제목을 다시 읽으면 원래 제목 그대로 (따옴표·역슬래시·대괄호)."""
    meta, _ = _parse_text(skeleton(title, 'NET', 'VPN·네트워크', [frag('a')], CONTACT))
    assert meta.get('title') == title


@pytest.mark.parametrize('title', ['첫 줄\n## 9. 추가 장\n주입 본문', '줄\r바꿈', '탭\t문자',
                                   '제목\u0085## 9. 추가 장', '제목 ## 9. 추가 장', '제목 ## 9. 추가 장',
                                   '제목\x1c구분', '제목\x85C1'])
def test_multiline_title_refused(title):
    """PR #361 검수 2: 제목은 한 줄 — 줄바꿈 뒤에 장이 끼어들지 않게 거부."""
    assert ob.title_problems(title) == ['새 가이드 제목은 한 줄이어야 합니다 (줄바꿈·제어 문자 없이)']
    assert ob.title_problems('  ') == ['새 가이드 제목이 없습니다'] and ob.title_problems('정상 제목') == []


def test_contact_body_ignores_code_block_heading():
    """PR #361 검수 4: 6장 안 코드 예시의 '## ' 는 다음 장이 아니다. 문서 끝의 6장도 읽는다."""
    body = '```text\n## 예시\n내용\n```\n\n' + CONTACT
    md = f'## 5. 주의사항\n\n- a\n\n## 6. 문의처\n\n{body}\n\n## 부록 · 관련 문서\n\n- b\n'
    assert ob.contact_body(md) == body
    assert ob.contact_body(f'## 6. 문의처\n\n{CONTACT}\n') == CONTACT and ob.contact_body('## 5. 주의\n') == ''


def test_contact_skips_empty_chapter(monkeypatch):
    """PR #361 검수 3: 첫 후보의 6장이 비었거나 자리 표시뿐이면 다음 후보에서 복사한다. 모두 없으면 경고."""
    texts = {'A': '## 6. 문의처\n\n   \n\t\n## 부록\n', 'B': f'## 6. 문의처\n\n  {TODO}  \n', 'C': f'## 6. 문의처\n\n{CONTACT}\n'}

    class Conn:
        def __init__(self, docs):
            self.docs = docs

        def execute(self, *a):
            return type('R', (), {'fetchall': lambda _: [(d, d) for d in self.docs]})()

    monkeypatch.setattr(ob, 'resolve_file', lambda path, root: path)
    monkeypatch.setattr(ob, '_base_md', lambda path, code, w: texts[path])
    w = []
    assert ob._contact(Conn(['A', 'B', 'C']), 'NET', None, w) == CONTACT and w == []
    assert ob._contact(Conn(['A', 'B']), 'NET', None, w) == '' and len(w) == 1


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
    ({'judgment': 'CHANGE', 'target_section': '3.99'}, '항목 3.99가 없습니다'),
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


@needs_db
def test_ticket_fragment_warns_when_it_breaks_fragment_rules(url):
    """#363 재검수 3: 티켓 글이 조각 약속에 걸리면 (처리 글에 반영 표식 문구) 내용은 그대로 두고 '등록 전에 고쳐' 경고."""
    tid = _ticket(url, 'OB-SEC-3', code='SW-01', note='기존 문서의 해결 사례 반영 (ABC-1) 표식을 확인했습니다')
    with _conn(url) as conn:
        fragment, warnings = ticket_fragment(conn, tid)
        conn.rollback()
    assert '해결 사례 반영 (ABC-1)' in fragment
    assert any(w.startswith('OB-SEC-3: 등록 전에 고쳐 주세요') and '반영 표식' in w for w in warnings)


@needs_db
def test_ticket_warnings_for_cluster(url):
    """M4 Q8: 묶음 티켓별 짧은 처리·재처리 경고를 모은다. 티켓 순서대로·같은 id 한 번, 앞선 처리 원문은 넣지 않는다.
    문제없는 티켓은 경고 없음, 없는 id 는 거부."""
    from app.rag.ingest import connect
    ok = _ticket(url, 'OB-W-1', code='SW-01')
    short = _ticket(url, 'OB-W-2', code='SW-01', note='재부팅함')
    again = _ticket(url, 'OB-W-3', code='SW-01')
    with connect(url) as conn:
        for frm, to, reason in [('WIP', 'FIN', None), ('FIN', 'WIP', 'OLD_LEFT_MARK'), ('WIP', 'FIN', None),
                                ('FIN', 'CLS', None)]:
            conn.execute('insert into ticket_status_history (ticket_id, from_status, to_status, source, reason) '
                         "values (%s, %s, %s, 'ITSSUE', %s)", (again, frm, to, reason))
        conn.commit()
        warnings = ob.ticket_warnings(conn, [again, ok, short, again])
        assert ob.ticket_warnings(conn, [ok]) == []
        with pytest.raises(CaseGuideError, match='없는 티켓 id: 999999999'):
            ob.ticket_warnings(conn, [ok, 999999999])
        conn.rollback()
    assert warnings == ['OB-W-3: 다시 처리된 접수입니다 (재처리 1회). 앞선 처리는 TK-08 이력에서 확인하세요',
                        'OB-W-2: 해결 내용이 짧습니다 (4자). 초안의 조치 방법이 충분한지 확인하세요']
    assert not any('OLD_LEFT_MARK' in w for w in warnings)


def test_ticket_warnings_reads_only():
    """DB 에 쓰지 않고 commit 하지 않는다 (워커 트랜잭션 안에서 부른다)."""
    src = re.sub(r'""".*?"""', '', inspect.getsource(ob.ticket_warnings), flags=re.S) + inspect.getsource(ob._ticket_warnings)
    assert 'commit' not in src and not re.search(r'\b(insert|update|delete)\b', src, re.I)


def test_category_name_must_be_one_line():
    assert ob.title_problems('분류\n이름', '분류 이름') == ['분류 이름은 한 줄이어야 합니다 (줄바꿈·제어 문자 없이)']


# ── 1·2장 AI 초안 (11.09 M4 요청) ───────────────────────────────

OVERVIEW = '**목적**\n\n- 재택 프린터 연결 문제를 스스로 해결하도록 돕습니다.\n\n**적용 대상**\n\n- 재택 근무 임직원'
PRECHECK = '#### 공통 확인\n\n- 프린터 전원과 와이파이를 확인합니다.\n- 프린터 주소: 담당자 확인'


def test_skeleton_fills_chapter1_2_and_keeps_jump_table():
    """overview·precheck 가 있으면 1·2장 본문으로, 2장 본문 아래에 증상별 바로가기 표는 그대로 붙는다. 파서·청커가 읽는다."""
    md = skeleton('제목', 'NET', 'VPN·네트워크', [frag('a')], CONTACT, overview=OVERVIEW, precheck=PRECHECK)
    assert f'## 1. 개요\n\n{OVERVIEW}\n\n## 2. 먼저 확인할 사항\n\n{PRECHECK}\n\n#### 증상별 바로가기\n\n| 겪고 있는 증상 |' in md
    assert TODO not in md
    meta, chunks = _parse_text(md)
    assert [c.section_no for c in chunks if c.chunk_type == 'chapter'][:2] == ['1', '2']


def test_skeleton_without_bodies_is_unchanged():
    """값이 없으면 지금처럼 자리 표시 (예전 호출과 같은 결과)."""
    old = skeleton('제목', 'NET', 'VPN·네트워크', [frag('a')], CONTACT)
    assert old == skeleton('제목', 'NET', 'VPN·네트워크', [frag('a')], CONTACT, overview=None, precheck=None)
    assert old.count(f'\n{TODO}\n') == 2


@pytest.mark.parametrize('text, why', [
    ('## 9. 끼어든 장\n본문', '1번째 줄에 쓸 수 없는 제목(##)'), ('본문\n### 3.9 끼어든 항목', '2번째 줄에 쓸 수 없는 제목(###)'),
    ('# 문서 제목', '쓸 수 없는 제목(#)'),
    ('```text\n열린 코드', '닫히지 않은 코드 블록'), ('- 해결 사례 반영 (TK-1): 넣지 마세요', '반영 표식'),
])
def test_chapter_body_refuses_shape_breakers(text, why):
    """장 경계를 깨는 글은 넣지 않고 자리 표시 + 경고 (묶음 전체를 실패시키지 않는다)."""
    warnings = []
    assert ob.chapter_body(text, '1장 개요', warnings) is None
    assert len(warnings) == 1 and why in warnings[0] and '1장 개요' in warnings[0]


def test_chapter_body_allows_subheadings_code_and_tables():
    """#### 소제목·굵은 글씨·목록·표·코드 블록 안의 '##' 는 됨. 빈 글은 경고 없이 자리 표시. 줄바꿈은 \n 으로."""
    text = '#### 소제목\r\n\r\n| a | b |\r\n| --- | --- |\r\n| 1 | 2 |\r\n\r\n```text\r\n## 코드 안\r\n```\r\n'
    warnings = []
    assert ob.chapter_body(text, '2장', warnings) == text.replace('\r\n', '\n').strip('\n') and warnings == []
    assert ob.chapter_body('  \n ', '2장', warnings) is None and ob.chapter_body(None, '2장', warnings) is None
    assert warnings == []
    assert ob.chapter_body('#### 증상별 바로가기\n- x', '2장', warnings, reserved=(ob.JUMP_TITLE,)) is None
    assert '1번째 줄에 뼈대가 붙이는 소제목' in warnings[0]


@pytest.mark.parametrize('head', ['####\t증상별 바로가기', '#### **증상별 바로가기**', '####   증상별   바로가기',
                                  '##### 증상별 바로가기', '#### `증상별 바로가기` ####'])
def test_chapter_body_reserved_title_variants(head):
    """PR #384 검수 2: 탭·여러 공백·굵게·코드 표시·다른 수준으로 써도 예약 소제목은 막는다 (파서가 같은 제목으로 읽음)."""
    warnings = []
    assert ob.chapter_body(f'- 앞\n\n{head}\n\n- 내용', '2장', warnings, reserved=(ob.JUMP_TITLE,)) is None
    assert '3번째 줄에 뼈대가 붙이는 소제목' in warnings[0]
    assert ob.chapter_body('#### 증상별 확인 순서\n- 내용', '2장', [], reserved=(ob.JUMP_TITLE,))  # 비슷한 다른 제목은 됨


def test_chapter_body_warning_has_no_rejected_text():
    """PR #384 검수 1: 거부한 글의 값(연락처·비밀값 등)은 경고에 넣지 않는다 — 장 이름·줄 번호·문제 종류만."""
    secret = '010-9999-0000 비번 Zx9!q'                       # 합성 값
    warnings = []
    for text in (f'## {secret}', f'본문\n#### 증상별 바로가기 {secret}\n```', f'해결 사례 반영 ({secret})'):
        assert ob.chapter_body(text, '2장', warnings, reserved=(ob.JUMP_TITLE,)) is None
    assert len(warnings) == 3 and not any(part in w for w in warnings for part in ('010', '9999', 'Zx9', '비번'))


@needs_db
def test_open_basis_new_guide_with_ai_chapters(url):
    """open_basis(NEW_GUIDE, overview=, precheck=) → 1·2장 채움, 틀린 장만 자리 표시 + 경고."""
    _current_guide(url)
    with _conn(url) as conn:
        ok = open_basis(conn, 'NEW_GUIDE', category_code='SW', title='새 가이드', fragments=[frag('a', code='SW-01')],
                        overview=OVERVIEW, precheck=PRECHECK, files_root=REPO)
        half = open_basis(conn, 'NEW_GUIDE', category_code='SW', title='새 가이드', fragments=[frag('a', code='SW-01')],
                          overview=OVERVIEW, precheck='## 2. 덮어쓰기', files_root=REPO)
        conn.rollback()
    assert OVERVIEW in ok['draft_md'] and PRECHECK in ok['draft_md'] and not any('초안을 넣지' in w for w in ok['warnings'])
    assert OVERVIEW in half['draft_md'] and f'## 2. 먼저 확인할 사항\n\n{TODO}' in half['draft_md']
    assert any(w.startswith('2장 먼저 확인할 사항 초안을 넣지 않고') for w in half['warnings'])
