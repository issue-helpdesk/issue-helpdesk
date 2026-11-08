"""매뉴얼 항목별 내용 전송 허용 목록 (app.rag.ingest.allowlist): 지문·뼈대. DB 없이."""
import json

import pytest

from app.rag.ingest import GUIDES, load_manifest
from app.rag.ingest.allowlist import FINGERPRINT_VERSION, fingerprint, item_text, items, main, skeleton
from app.rag.parser import parse
from app.rag.parser.models import Element

MANUALS = [e for e in load_manifest() if e.get('doc_type') == 'manual']
FILE = GUIDES / 'transfer_allowlist.json'


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
