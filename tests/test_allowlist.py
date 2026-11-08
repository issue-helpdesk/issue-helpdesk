"""매뉴얼 항목별 내용 전송 허용 목록 (app.rag.ingest.allowlist): 지문·뼈대. DB 없이."""
import json

import pytest

from app.rag.ingest import GUIDES, load_manifest
from app.rag.ingest.allowlist import FINGERPRINT_VERSION, fingerprint, items, main, skeleton
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


def test_docx_same_fingerprint_as_md():
    """같은 매뉴얼의 docx 도 정리본 md 와 지문이 같다 (★·이모지는 md 파서만 지워서 지문 계산 때 지운다)."""
    for e in MANUALS:
        md = {i['section']: i['fingerprint'] for i in items(parse(str(GUIDES / e['files']['md'])))}
        docx = {i['section']: i['fingerprint'] for i in items(parse(str(GUIDES / e['files']['docx'])))}
        assert md == docx, e['doc_no']


def test_fingerprint_sees_content_not_layout():
    """내용(글·표 칸·머리 정보·제목)이 바뀌면 지문이 바뀌고, 쪽 번호·줄 끝·줄 앞뒤 공백·꾸밈 기호는 상관없다."""
    body = [Element('heading', '접수 시 확인 질문', level=3), Element('paragraph', '사번과 증상을 묻는다'),
            Element('table', rows=[['상황', '조치'], ['잠김', '해제']])]
    base = fingerprint('3.1 계정 잠김', [('1차 처리', '서비스데스크')], body)
    same = [Element('heading', ' 접수 시 확인 질문 ', level=3, page=3), Element('paragraph', '★ 사번과 증상을 묻는다\r\n', page=4),
            Element('table', rows=[['상황', '조치'], ['', ''], ['잠김 ', '해제']], page=4)]
    assert fingerprint('3.1 계정 잠김', [('1차 처리', '서비스데스크')], same) == base
    changed = [
        ('3.1 계정 잠김', [('1차 처리', '서비스데스크')], body[:1] + [Element('paragraph', '사번만 묻는다')] + body[2:]),
        ('3.1 계정 잠김', [('1차 처리', '서비스데스크')], body[:2] + [Element('table', rows=[['상황', '조치'], ['잠김', '초기화']])]),
        ('3.1 계정 잠김', [('1차 처리', '보안팀')], body),
        ('3.1 계정 잠김 해제', [('1차 처리', '서비스데스크')], body),
        ('3.1 계정 잠김', [('1차 처리', '서비스데스크')], body + [Element('list_item', '해제 후 알린다')]),
    ]
    assert all(fingerprint(*c) != base for c in changed)


def test_cli_refuses_overwrite(tmp_path, capsys):
    """채운 값을 지우지 않게, 있는 파일은 --force 없이 덮어쓰지 않는다."""
    out = tmp_path / 'list.json'
    out.write_text('{"items": []}', encoding='utf-8')
    assert main(['skeleton', '--out', str(out)]) == 2 and out.read_text(encoding='utf-8') == '{"items": []}'
    assert main(['skeleton', '--out', str(out), '--force']) == 0
    assert len(json.loads(out.read_text(encoding='utf-8'))['items']) == 143
