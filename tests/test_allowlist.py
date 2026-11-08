"""매뉴얼 항목별 내용 전송 허용 목록 (app.rag.ingest.allowlist): 지문·뼈대. DB 없이."""
import json

import pytest

from app.rag.ingest import GUIDES, load_manifest
from app.rag.ingest.allowlist import FINGERPRINT_VERSION, fingerprint, item_text, items, main, skeleton
from app.rag.parser import parse
from app.rag.parser.models import Element

MANUALS = [e for e in load_manifest() if e.get('doc_type') == 'manual']
from app.rag.ingest.allowlist import ALLOWLIST as FILE


@pytest.fixture(scope='module')
def built():
    return skeleton()


def test_skeleton_all_manual_items(built):
    """매뉴얼 27종의 3.x 143개 (기획 v4 "선행 작업"의 개수). 값은 비워 두고(M4 가 채움) 지문은 모두 다르다."""
    rows = built['items']
    assert built['fingerprint_version'] == FINGERPRINT_VERSION
    assert len(MANUALS) == 27 and len({r['doc_no'] for r in rows}) == 27 and len(rows) == 143
    assert all(r['content'] is None and r['section'].startswith('3.') and r['title'] for r in rows)
    assert len({r['fingerprint'] for r in rows}) == 143 and len({(r['doc_no'], r['section']) for r in rows}) == 143


def test_repo_file_matches_documents(built):
    """저장소의 허용 목록 파일: 항목·제목·지문이 지금 매뉴얼과 같다 (매뉴얼을 고치면 이 시험이 알린다 → 목록 다시 확인).
    content 는 M4 가 채우므로 비교하지 않는다. 값은 ALLOWED·BLOCKED·빈칸만."""
    data = json.loads(FILE.read_text(encoding='utf-8'))
    strip = lambda rows: [{k: v for k, v in r.items() if k != 'content'} for r in rows]   # noqa: E731
    assert data['fingerprint_version'] == FINGERPRINT_VERSION and strip(data['items']) == strip(built['items'])
    assert {r['content'] for r in data['items']} <= {None, 'ALLOWED', 'BLOCKED'}


def test_items_match_chunk_units():
    """목록의 항목 = 청커의 item 단위 (unit_key item:3.x). 여러 조각으로 나뉜 항목도 한 줄."""
    from app.rag.chunker import chunk_document
    for e in MANUALS:
        doc = parse(str(GUIDES / e['files']['md']))
        units = {c.unit_key.rsplit(':', 1)[-1] for c in chunk_document(doc) if c.chunk_type == 'item'}
        assert {i['section'] for i in items(doc)} == {u for u in units if u.startswith('3.')}, e['doc_no']


def test_docx_differs_only_by_symbols():
    """같은 매뉴얼의 docx: 대부분 md 와 지문이 같고, 다른 항목은 docx 에만 남는 기호(★·이모지, md 파서가 지움) 때문이다.
    그 기호는 docx 로 적재하면 청크 글에도 들어가므로 지문이 달라 차단되는 것이 맞다 (PR #355 검수 1)."""
    from app.rag.parser.md_parser import EMOJI_RE
    from app.rag.chunker import SECTION_NO_RE, _units

    def texts(path):
        return {SECTION_NO_RE.match(item.text).group(1): item_text(item.text, item.meta.get('props'), pieces)
                for kind, chapter, item, pieces in _units(parse(str(path)))
                if kind == 'item' and item and SECTION_NO_RE.match(chapter or '') and
                SECTION_NO_RE.match(chapter).group(1) == '3'}
    def plain(t):
        return '\n'.join(' '.join(line.split()) for line in EMOJI_RE.sub('', t).split('\n'))

    same = 0
    for e in MANUALS:
        md, docx = texts(GUIDES / e['files']['md']), texts(GUIDES / e['files']['docx'])
        assert md.keys() == docx.keys(), e['doc_no']
        for s in md:
            if md[s] == docx[s]:
                same += 1
            else:
                assert plain(docx[s]) == plain(md[s]), (e['doc_no'], s)           # 기호만 빼면 같다
    assert same == 130                                       # 2026-11-08 (README 와 같은 수)


def _fp(*elements, title='3.1 확인', props=()):
    return fingerprint(title, list(props), list(elements))


@pytest.mark.parametrize('a, b', [
    (Element('paragraph', '결과: ✓'), Element('paragraph', '결과: ✗')),                       # 뜻 있는 기호
    (Element('table', rows=[['a | b', 'c']]), Element('table', rows=[['a', 'b | c']])),       # 표 칸 경계
    (Element('paragraph', 'if ok:\n    allow()\ndeny()', meta={'code': True}),
     Element('paragraph', 'if ok:\n    allow()\n    deny()', meta={'code': True})),          # 코드 들여쓰기
    (Element('paragraph', '조치'), Element('list_item', '조치')),                              # 요소 종류
    (Element('heading', '확인', level=3), Element('heading', '확인', level=4)),                 # 제목 수준
])
def test_fingerprint_keeps_meaningful_differences(a, b):
    """PR #355 검수 1~3: 기호·표 칸 경계·코드 들여쓰기·요소 종류가 다르면 지문이 다르다."""
    assert _fp(a) != _fp(b)


def test_fingerprint_ignores_layout():
    """쪽 번호·줄 끝(CRLF)·줄 끝 공백·빈 표 행은 지문에 들어가지 않는다 (청커가 나눈 경계도 입력이 아니다)."""
    a = [Element('heading', '접수 시 확인 질문', level=3), Element('paragraph', '사번과 증상을 묻는다'),
         Element('table', rows=[['상황', '조치'], ['잠김', '해제']])]
    b = [Element('heading', '접수 시 확인 질문  ', level=3, page=3), Element('paragraph', '사번과 증상을 묻는다\r\n', page=4),
         Element('table', rows=[['상황', '조치'], ['', ''], ['잠김 ', '해제']], page=4)]
    assert _fp(*a) == _fp(*b)


def test_only_items_in_chapter3():
    """PR #355 검수 4: 장 번호가 3 인 장 안의 '3.x' 항목만. 다른 장(FAQ 등)의 '3.x' 제목은 목록에 넣지 않는다."""
    from app.rag.parser.models import ParsedDocument
    def doc(chapter):
        return ParsedDocument(path='x.md', format='md', elements=[
            Element('heading', chapter, level=1), Element('heading', '3.1 확인', level=2), Element('paragraph', '내용')])
    assert [i['section'] for i in items(doc('3. 처리'))] == ['3.1']
    assert items(doc('5. 자주 묻는 질문')) == [] and items(doc('부록 · 관련 문서')) == []


def test_skeleton_refuses_duplicate_section(tmp_path, monkeypatch):
    """같은 문서에 3장 항목 번호가 겹치면 목록을 만들지 않는다 (어느 쪽을 허용할지 모호)."""
    import app.rag.ingest.allowlist as al
    monkeypatch.setattr(al, 'items', lambda doc: [{'section': '3.1', 'title': 'a', 'fingerprint': 'x'}] * 2)
    with pytest.raises(ValueError, match='3.1'):
        al.skeleton()


def test_cli_refuses_overwrite(tmp_path, capsys):
    """채운 값을 지우지 않게, 있는 파일은 --force 없이 덮어쓰지 않는다."""
    out = tmp_path / 'list.json'
    out.write_text('{"items": []}', encoding='utf-8')
    assert main(['skeleton', '--out', str(out)]) == 2 and out.read_text(encoding='utf-8') == '{"items": []}'
    assert main(['skeleton', '--out', str(out), '--force']) == 0
    assert len(json.loads(out.read_text(encoding='utf-8'))['items']) == 143


# ── 적재 판정 (load·policies) ─────────────────────────────────

def _write(tmp_path, data):
    f = tmp_path / 'allow.json'
    f.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return f


def test_load_distrusts_bad_lists(tmp_path):
    """믿을 수 없는 목록은 비운다 (= 차단): 파일 없음·계산법 버전 다름 → 전부, 같은 키 → 그 키, 모르는 값 → 그 항목."""
    from app.rag.ingest.allowlist import load
    allow, w = load(tmp_path / 'none.json')
    assert allow == {} and '읽지 못해' in w[0]
    allow, w = load(_write(tmp_path, {'fingerprint_version': 99, 'items': [{'doc_no': 'A', 'section': '3.1', 'content': 'ALLOWED'}]}))
    assert allow == {} and '계산법 버전(99)' in w[0]
    rows = [{'doc_no': 'A', 'section': '3.1', 'content': 'ALLOWED', 'fingerprint': 'x'},
            {'doc_no': 'A', 'section': '3.1', 'content': 'BLOCKED', 'fingerprint': 'x'},
            {'doc_no': 'A', 'section': '3.2', 'content': 'MASKED', 'fingerprint': 'y'},
            {'doc_no': 'A', 'section': '3.3', 'content': None, 'fingerprint': 'z'}]
    allow, w = load(_write(tmp_path, {'fingerprint_version': FINGERPRINT_VERSION, 'items': rows}))
    assert allow == {('A', '3.2'): (None, 'y'), ('A', '3.3'): (None, 'z')}
    assert any('같은 항목이 여럿' in x for x in w) and any("모르는 값 'MASKED'" in x for x in w)


def _manual(code='IT-SEC-003-M'):
    from app.rag.chunker import chunk_document
    doc = parse(str(GUIDES / next(e for e in MANUALS if e['doc_no'] == code)['files']['md']))
    return doc, chunk_document(doc)


def test_policies_allow_only_listed_same_fingerprint():
    """목록 ALLOWED·지문 같음 → 그 항목의 모든 조각 ALLOWED (여러 조각 항목 3.5 포함). 나머지(목록 BLOCKED·빈 값·
    목록 밖·3장 밖 장·서문)는 BLOCKED. 모든 청크에 값이 있다."""
    from app.rag.ingest.allowlist import policies
    doc, chunks = _manual()
    found = {i['section']: i['fingerprint'] for i in items(doc)}
    allow = {('IT-SEC-003-M', '3.5'): ('ALLOWED', found['3.5']), ('IT-SEC-003-M', '3.1'): ('BLOCKED', found['3.1']),
             ('IT-SEC-003-M', '3.2'): (None, found['3.2'])}
    pol, w = policies('IT-SEC-003-M', doc, chunks, allow)
    assert w == [] and set(pol) == {c.unit_key for c in chunks}
    pieces = [c for c in chunks if c.unit_key.endswith('/item:3.5')]
    assert len(pieces) > 1 and {pol[c.unit_key] for c in pieces} == {'ALLOWED'}
    assert {p for u, p in pol.items() if not u.endswith('/item:3.5')} == {'BLOCKED'}


def test_policies_block_changed_content_and_duplicates(monkeypatch):
    """지문이 다르면 차단 + 경고. 문서 안 3장 항목 번호가 겹치면 그 번호는 차단 + 경고."""
    import app.rag.ingest.allowlist as al
    doc, chunks = _manual()
    found = {i['section']: i['fingerprint'] for i in items(doc)}
    pol, w = al.policies('IT-SEC-003-M', doc, chunks, {('IT-SEC-003-M', '3.1'): ('ALLOWED', 'sha256:old')})
    assert set(pol.values()) == {'BLOCKED'} and w == ['IT-SEC-003-M 3.1: 허용 목록 이후 내용이 바뀌어 차단합니다 (M4 확인 뒤 목록을 고쳐 주세요)']
    real = al.items
    monkeypatch.setattr(al, 'items', lambda d: real(d) + [{'section': '3.1', 'title': 'x', 'fingerprint': found['3.1']}])
    pol, w = al.policies('IT-SEC-003-M', doc, chunks, {('IT-SEC-003-M', '3.1'): ('ALLOWED', found['3.1'])})
    assert set(pol.values()) == {'BLOCKED'} and w == ['IT-SEC-003-M: 3장 항목 번호가 겹쳐 차단합니다 (3.1)']


def test_allowlist_file_ships_with_backend():
    """목록은 백엔드 코드 옆 — 서버 이미지(backend/Dockerfile 은 backend 폴더만 복사, dataset/guides 는 안 함)에 들어가야
    업로드 적재가 읽는다 (없으면 매뉴얼 내용을 모두 차단)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert FILE.exists() and FILE.resolve().is_relative_to(root / 'backend')
    docker = (root / 'backend' / 'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY backend ./backend' in docker
