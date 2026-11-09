"""새 가이드 조립·등록 (assemble 의 NEW_GUIDE, 김현나 Q9). 뼈대는 open_basis.skeleton."""
import re
from datetime import date
from pathlib import Path

import pytest

from app.rag.case_guide import CaseGuideError, _item, _parse_text, receipts
from app.rag.case_guide.assemble import TODO, _build_new_guide, _check_result, assemble
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


def _with_fragments(fragments):
    md = skeleton('재택 프린터 연결 가이드', 'NET', 'VPN·네트워크', fragments, CONTACT)
    md = md.replace(f'## 1. 개요\n\n{TODO}', f'## 1. 개요\n\n{INTRO}', 1)
    return md.replace(f'## 2. 먼저 확인할 사항\n\n{TODO}', f'## 2. 먼저 확인할 사항\n\n{CHECK}', 1)


@pytest.mark.parametrize('fragments, msg', [
    (['### 3.N 제목만 있음', '### 3.N 이것도 제목만'], '본문이 없는 항목이 있습니다: 3.1, 3.2'),
    ([frag('프린터가 안 잡힘'), '### 3.N 제목만 있음'], '본문이 없는 항목이 있습니다: 3.2'),
])
def test_build_refuses_heading_only_items(fragments, msg):
    """항목 표·바로가기 표가 있어도 항목이 제목뿐이면 거부 — 검색될 항목이 없는 가이드가 되지 않게 (PR #370 검수 1)."""
    with pytest.raises(CaseGuideError, match=re.escape(msg)):
        _build_new_guide(new_cluster(_with_fragments(fragments)), 'IT-NET-010', 'v1.0', TODAY, [])


@pytest.mark.parametrize('fragments', [
    ['### 3.N 비어 있는 항목', frag('프린터가 안 잡힘')],          # 빈 것이 앞
    [frag('프린터가 안 잡힘'), '### 3.N 비어 있는 항목'],          # 빈 것이 뒤
    [frag('프린터가 안 잡힘'), frag('출력이 느림')],                # 둘 다 본문 있음
])
def test_build_refuses_duplicate_item_number(fragments):
    """같은 항목 번호가 둘이면 거부 — 본문 있는 쪽 때문에 빈 쪽이 통과하지 않게 (PR #370 재검수 1)."""
    md = _with_fragments(fragments)
    md = md.replace('\n### 3.2 ', '\n### 3.1 ', 1)
    with pytest.raises(CaseGuideError, match=re.escape('같은 항목 번호가 두 번 이상 있습니다: 3.1')):
        _build_new_guide(new_cluster(md), 'IT-NET-010', 'v1.0', TODAY, [])


@pytest.mark.parametrize('extra', [f'## 1. 미작성\n\n{TODO}\n\n## 1. 개요\n\n{INTRO}',      # 앞 장에 자리 표시
                                   f'## 1. 개요\n\n{INTRO}\n\n## 1. 개요 둘째\n\n{TODO}'])  # 뒤 장에 자리 표시
def test_build_refuses_duplicate_chapter(extra):
    """같은 장 번호가 두 번이면 거부하고, 앞·뒤 어느 장의 '(작성 필요)' 도 놓치지 않는다 (PR #370 검수 2)."""
    md = filled([(f'## 1. 개요\n\n{INTRO}', extra)])
    with pytest.raises(CaseGuideError) as e:
        _build_new_guide(new_cluster(md), 'IT-NET-010', 'v1.0', TODAY, [])
    assert '같은 장이 두 번 이상 있습니다: 1장' in str(e.value) and "'(작성 필요)' 자리가 남아 있습니다: 1장" in str(e.value)


def test_build_changes_only_front_matter():
    """문서 번호·버전은 머리말 안에서만 바꾼다. 본문 코드 예시의 같은 이름 줄은 그대로 (PR #370 검수 4)."""
    code = '\n```text\ndoc_no: "EX-1"\nversion: "v9.9"\n```'
    md = _build_new_guide(new_cluster(filled([(INTRO, INTRO + code)])), 'IT-NET-010', 'v1.0', TODAY, [])
    meta, _ = _parse_text(md)
    assert (meta['doc_no'], meta['version']) == ('IT-NET-010', 'v1.0') and code.strip('\n') in md


@pytest.mark.parametrize('edits, msg', [
    ([('version: "v1.0"\n', '')], '머리말에 version 줄이 없습니다'),
    ([('doc_no: ""\n', '')], '머리말에 doc_no 줄이 없습니다'),
    ([('---\ndoc_no', '--\ndoc_no')], '머리말(--- … ---)이 없습니다'),
])
def test_build_refuses_broken_front_matter(edits, msg):
    """머리말이 없거나 doc_no·version 줄이 없으면 거부 — 본문에서 찾아 바꾸지 않는다 (PR #370 검수 4)."""
    code = '\n```text\ndoc_no: "EX-1"\nversion: "v9.9"\n```'
    with pytest.raises(CaseGuideError, match=re.escape(msg)):
        _build_new_guide(new_cluster(filled([(INTRO, INTRO + code), *edits])), 'IT-NET-010', 'v1.0', TODAY, [])


def test_check_result_requires_version():
    """최종 검사: 버전이 없으면 (다르면만이 아니라) 거부 (PR #370 검수 4)."""
    md = _build_new_guide(new_cluster(), 'IT-NET-010', 'v1.0', TODAY, []).replace('version: "v1.0"\n', '', 1)
    with pytest.raises(CaseGuideError, match=re.escape('머리말에 버전(version)이 없습니다')):
        _check_result('', md, 'IT-NET-010', 'v1.0', [new_cluster()], {})


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
@pytest.mark.parametrize('existing', ['v2.0', 'v1.0'])
def test_assemble_new_guide_refuses_other_versions(url, tmp_path, existing):
    """현행은 없어도 다른 버전(업로드 초안·실패한 버전)이 있으면 v2.1 등으로 넘어가지 않고 거부 (PR #370 검수 3)."""
    from app.rag.ingest import connect
    doc = _new_document(url, f'IT-NET-01{2 if existing == "v2.0" else 3}')
    with connect(url) as conn:
        conn.execute("insert into document_versions (document_id, version, file_path, file_format, view_scope, "
                     "transfer_policy, is_current, ingest_status) values (%s, %s, 'storage/uploads/x.md', 'MD', 'ALL', "
                     "'ALLOWED', false, 'FAILED')", (doc, existing))
        conn.commit()
    with pytest.raises(CaseGuideError, match=re.escape(f'이미 다른 버전이 있습니다 ({existing})')):
        _call(url, doc, [new_cluster()], tmp_path)
    assert not list(Path(tmp_path).rglob('*.md'))


@needs_db
def test_assemble_new_guide_refused_writes_nothing(url, tmp_path):
    """새 가이드가 덜 채워졌으면 거부하고 파일을 남기지 않는다."""
    doc = _new_document(url, 'IT-NET-011')
    with pytest.raises(CaseGuideError, match='자리가 남아 있습니다'):
        _call(url, doc, [new_cluster(filled([(INTRO, TODO)]))], tmp_path)
    assert not list(Path(tmp_path).rglob('*.md'))
