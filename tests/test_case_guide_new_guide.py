"""새 가이드 조립·등록 (assemble 의 NEW_GUIDE, 김현나 Q9). 뼈대는 open_basis.skeleton."""
import re
from datetime import date
from pathlib import Path

import pytest

from app.rag.case_guide import CaseGuideError, _item, _parse_text, receipts
from app.rag.case_guide.assemble import TODO, _build_new_guide, assemble
from app.rag.case_guide.open_basis import skeleton
from test_case_guide import ticket_row
from test_ingest_upload import needs_db, url  # noqa: F401  (url 은 fixture)

TODAY = date(2026, 11, 9)
CONTACT = '| 창구 | 연락처 | 이용 기준 |\n| --- | --- | --- |\n| ITssue 챗봇 | 포털 | 24시간 |'
INTRO = '재택 프린터 연결 문제를 안내합니다.'
CHECK = '- 프린터 전원을 확인합니다.'


def frag(title, group='네트워크팀'):
    return _item('3.N', title, ticket_row(summary=title, code='NET-02', group=group))


def filled(edits=()):
    """관리자가 1·2장을 채운 뼈대 (4·5장·부록은 비워 둠). edits: [(old, new)]."""
    md = skeleton('재택 프린터 연결 가이드', 'NET', 'VPN·네트워크', [frag('프린터가 안 잡힘'), frag('출력이 느림')], CONTACT)
    md = md.replace(f'## 1. 개요\n\n{TODO}', f'## 1. 개요\n\n{INTRO}', 1)
    md = md.replace(f'## 2. 먼저 확인할 사항\n\n{TODO}', f'## 2. 먼저 확인할 사항\n\n{CHECK}', 1)
    for old, new in edits:
        assert old in md, old
        md = md.replace(old, new, 1)
    return md


def new_cluster(md=None, receipts_=('NG-1', 'NG-2'), cid=1):
    return {'id': cid, 'judgment': 'NEW_GUIDE', 'receipts': list(receipts_), 'draft_md': md or filled(),
            'draft_basis': {'schema': 1, 'judgment': 'NEW_GUIDE', 'base_version_id': None, 'base_md': None,
                            'category_code': 'NET', 'required': ['1', '2', '3']}}


# ── DB 없이 ───────────────────────────────────────────────────

def test_build_fills_number_version_and_drops_empty_chapters():
    """문서 번호·v1.0 채움, 빈 4·5장·부록은 장째 빼고 목차 줄도 뺌, 6장·개정 이력은 남김, 표식은 접수 번호마다."""
    md = _build_new_guide(new_cluster(), 'IT-NET-010', 'v1.0', TODAY, [])
    meta, chunks = _parse_text(md)
    assert (meta['doc_no'], meta['version']) == ('IT-NET-010', 'v1.0')
    for gone in ('## 4. 자주 묻는 질문', '## 5. 주의사항', '## 부록 · 관련 문서 · 용어',
                 '- 4. 자주 묻는 질문', '- 5. 주의사항', '- 부록 · 관련 문서 · 용어'):
        assert gone not in md, gone
    assert '## 6. 문의처' in md and '- 6. 문의처' in md and '## 개정 이력' in md
    assert receipts(md) == {'NG-1', 'NG-2'} and '해결 사례 반영 (NG-1): 새 가이드' in md
    assert re.search(r'^\| v1\.0 \| 2026-11-09 \| 네트워크팀 \|', md, re.M)
    assert [c.section_no for c in chunks if c.chunk_type == 'item'] == ['3.1', '3.2'] and TODO not in md


def test_build_keeps_written_optional_chapter():
    """관리자가 4장을 채웠으면 남긴다 (비었을 때만 뺀다)."""
    md = filled([('## 4. 자주 묻는 질문\n', '## 4. 자주 묻는 질문\n\nQ. 무선도 되나요?\n')])
    out = _build_new_guide(new_cluster(md), 'IT-NET-010', 'v1.0', TODAY, [])
    assert '## 4. 자주 묻는 질문' in out and '- 4. 자주 묻는 질문' in out


@pytest.mark.parametrize('edits, msg', [
    ([(INTRO, TODO)], "'(작성 필요)' 자리가 남아 있습니다: 1장"),
    ([(CHECK, TODO)], "'(작성 필요)' 자리가 남아 있습니다: 2장"),
    ([(f'## 1. 개요\n\n{INTRO}', '## 1. 개요\n')], '1장에 내용이 없습니다'),
    ([('| ITssue 챗봇 | 포털 | 24시간 |', TODO)], '자리가 남아 있습니다: 6장'),
])
def test_build_refuses_unfinished(edits, msg):
    """1·2·3장 필수, 어디든 '(작성 필요)' 줄이 남으면 거부 (김현나 Q9)."""
    with pytest.raises(CaseGuideError, match=re.escape(msg)):
        _build_new_guide(new_cluster(filled(edits)), 'IT-NET-010', 'v1.0', TODAY, [])


def test_build_refuses_no_items_and_marker():
    no_items = re.sub(r'^### 3\.\d+ .*$', '설명', filled(), flags=re.M)
    with pytest.raises(CaseGuideError, match=r'3장에 항목\(### 3\.N\)이 없습니다'):
        _build_new_guide(new_cluster(no_items), 'IT-NET-010', 'v1.0', TODAY, [])
    with pytest.raises(CaseGuideError, match='반영 표식'):
        _build_new_guide(new_cluster(filled() + '\n해결 사례 반영 (X-1)\n'), 'IT-NET-010', 'v1.0', TODAY, [])


def test_heading_in_code_block_is_not_a_chapter():
    """코드 블록 안의 '## 4. …' 는 장이 아니다 (빈 장 빼기·필수 검사가 코드를 자르지 않는다)."""
    code = '\n```text\n## 4. 자주 묻는 질문\n```'
    out = _build_new_guide(new_cluster(filled([(CHECK, CHECK + code)])), 'IT-NET-010', 'v1.0', TODAY, [])
    assert code.strip('\n') in out and '\n## 4. 자주 묻는 질문\n\n## 5.' not in out


# ── DB ────────────────────────────────────────────────────────

def _new_document(url, code='IT-NET-010', category='NET'):
    from app.rag.ingest import connect
    with connect(url) as conn:
        doc = conn.execute("insert into knowledge_documents (doc_code, doc_type, title, category_code) values (%s, 'GUIDE', "
                           "'재택 프린터 연결 가이드', %s) on conflict (doc_code) do update set doc_code = excluded.doc_code "
                           'returning id', (code, category)).fetchone()[0]
        conn.commit()
    return doc


def _call(url, doc, clusters, root, draft_version_id=None, commit=True):
    from app.rag.ingest import connect
    with connect(url) as conn:
        try:
            out = assemble(conn, doc, clusters, draft_version_id, view_scope='ALL', transfer_policy='ALLOWED', actor_id=None,
                           files_root=root, today=TODAY, staff_names=[])
        except Exception:
            conn.rollback()
            raise
        (conn.commit if commit else conn.rollback)()
    return out


@needs_db
def test_assemble_new_guide_first_version_then_searchable(url, tmp_path):
    """현행이 없는 문서(DC-02 로 등록만 됨) → v1.0 PENDING, 파일은 storage/case_guides/<문서>/ 아래, sections 없음.
    적재하면 항목이 청크가 되고 빈 장은 없다. 같은 대기 버전을 다시 조립할 수 있고, 현행이 생긴 뒤에는 거부."""
    from app.rag.ingest import activate, connect
    from app.rag.ingest.upload import ingest_version
    from test_ingest_upload import EMB
    doc = _new_document(url)
    out = _call(url, doc, [new_cluster()], tmp_path)
    assert out['version'] == 'v1.0' and out['sections'] == {}
    assert out['file_path'].startswith('storage/case_guides/IT-NET-010/')
    again = _call(url, doc, [new_cluster(receipts_=('NG-1',))], tmp_path, draft_version_id=out['version_id'])
    assert again['version_id'] == out['version_id'] and again['version'] == 'v1.0'
    with connect(url) as conn:
        res = ingest_version(conn, out['version_id'], EMB, tmp_path)
        assert res['status'] == 'DONE', res
        units = [u for (u,) in conn.execute('select unit_key from document_chunks where version_id = %s order by seq',
                                            (out['version_id'],))]
        activate(conn, out['version_id'])
        conn.commit()
    assert 'IT-NET-010@v1.0/item:3.1' in units and not [u for u in units if '/chapter:4' in u or '/chapter:5' in u]
    with pytest.raises(CaseGuideError, match='이미 현행 버전이 있습니다'):
        _call(url, doc, [new_cluster(cid=2, receipts_=('NG-3',))], tmp_path)


@needs_db
def test_assemble_new_guide_refused_writes_nothing(url, tmp_path):
    """새 가이드가 덜 채워졌으면 거부하고 파일을 남기지 않는다."""
    doc = _new_document(url, 'IT-NET-011')
    with pytest.raises(CaseGuideError, match='자리가 남아 있습니다'):
        _call(url, doc, [new_cluster(filled([(INTRO, TODO)]))], tmp_path)
    assert not list(Path(tmp_path).rglob('*.md'))
