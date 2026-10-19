"""청크 나누기(M2-1-2)·청크 메타데이터(M2-1-3) 테스트. 기준 문서는 dataset/guides_final."""
import json
import os
import re

import pytest

from app.rag.chunker import (CHUNKER_VERSION, ITEM_UNIT_MAX, MAX_CHARS, baseline, chunk_document, chunk_row, document_row,
                             duplicate_groups, unit_ref, validate, version_row)
from app.rag.parser import parse
from app.rag.parser.models import Element, ParsedDocument
from test_parser import FORMATS, SAMPLES, manifest

HEAD_ROOM = 300      # 머리말(문서 제목 > 장 > 항목 + 항목 머리) 몫


def chunks_of(doc_no, fmt='md'):
    m = manifest()[doc_no]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dataset', 'guides_final', m['files'][fmt])
    doc = parse(path)
    return doc, chunk_document(doc)


@pytest.mark.parametrize('fmt', FORMATS[1:])
@pytest.mark.parametrize('doc_no', SAMPLES)
def test_same_chunks_across_formats(doc_no, fmt):
    """같은 문서는 형식이 달라도 청크 경계(경로·조각)가 같다."""
    key = lambda cs: [(c.heading_path, c.part, c.chunk_type) for c in cs]
    assert key(chunks_of(doc_no, fmt)[1]) == key(chunks_of(doc_no, 'md')[1])


@pytest.mark.parametrize('doc_no', SAMPLES)
def test_no_text_lost(doc_no):
    """개정 이력 말고는 본문 요소가 모두 어떤 청크에 들어 있다."""
    doc, cs = chunks_of(doc_no)
    allt = '\n'.join(c.text for c in cs)
    for e in doc.elements:
        if e.kind == 'heading' or e.section[:1] == ['개정 이력']:
            continue
        probe = e.text or ' | '.join(e.rows[-1]).strip()
        assert probe[:40] in allt, (e.kind, probe[:60])


def test_item_chunk():
    """3.x 항목 하나 = 청크 하나. 소제목과 항목 머리가 같이 들어 있다."""
    _, cs = chunks_of('IT-SW-002')
    c = next(c for c in cs if c.section_no == '3.1')
    assert c.chunk_type == 'item' and c.parts == 1
    assert c.heading_path == ['3. 항목별 안내', '3.1 유료 프로그램 라이선스 신청']
    assert c.text.startswith('SW 라이선스 신청·인증 가이드 > 3. 항목별 안내 > 3.1 유료 프로그램 라이선스 신청\n문의 유형: SW-02')
    assert {'신청 방법', '작성 예시', '문의 시 알려 주실 정보'} <= set(c.subheadings)
    assert c.inquiry_type_codes == ['SW-02'] and c.faq_ids == ['FAQ-023']
    assert c.handling == '신청·승인 후 처리' and c.team == '엔드포인트지원팀'
    assert c.images == ['sw002_license_form.png']
    assert (c.doc_no, c.version, c.access_level, c.category, c.doc_type) == ('IT-SW-002', 'v2.0', '사내 일반', 'SW', 'guide')


def test_chunk_kinds_and_skips():
    _, cs = chunks_of('IT-SW-002')
    faqs = [c for c in cs if c.chunk_type == 'faq']
    assert len(faqs) == 3 and all(c.text.count('\nQ. ') == 1 for c in faqs)
    assert faqs[0].faq_ids == ['FAQ-023']
    paths = [c.heading_path[0] for c in cs]
    assert '개정 이력' not in paths and '목차' not in paths
    assert [c.seq for c in cs] == list(range(1, len(cs) + 1))
    assert len({c.chunk_key for c in cs}) == len(cs) and cs[0].chunk_key == 'IT-SW-002@v2.0#001'
    assert all(c.char_count == len(c.text) for c in cs)


def test_pdf_chunk_pages():
    _, cs = chunks_of('IT-SW-002', 'pdf')
    c = next(c for c in cs if c.section_no == '3.1')
    assert c.page_start and c.page_start <= c.page_end
    _, md = chunks_of('IT-SW-002')
    assert all(c.page_start is None and c.page_end is None for c in md)


def test_long_chapter_split():
    """긴 장은 소제목 단위로 나뉘고, 조각마다 경로와 (i/n)이 붙는다."""
    _, cs = chunks_of('IT-STD-002')
    parts = [c for c in cs if c.heading_path == ['2. 문서 체계와 번호']]
    assert len(parts) > 1
    assert [c.part for c in parts] == list(range(1, len(parts) + 1))
    for c in parts:
        assert f'({c.part}/{c.parts})' in c.text.split('\n')[0]
        assert c.char_count <= MAX_CHARS + HEAD_ROOM


def test_all_guides_within_limit():
    for doc_no in manifest():
        _, cs = chunks_of(doc_no)
        assert all(c.char_count <= MAX_CHARS + HEAD_ROOM for c in cs), doc_no


def _doc(*elements, meta=None):
    d = ParsedDocument(path='x.md', format='md', title='시험 문서', meta=meta or {'doc_no': 'IT-T-001', 'version': 'v1.0'})
    d.elements = list(elements)
    return d


def test_long_table_repeats_header():
    rows = [['항목', '내용']] + [[f'행{i}', '가' * 60] for i in range(60)]
    cs = chunk_document(_doc(Element('heading', '1. 표', level=1), Element('table', rows=rows)))
    assert len(cs) > 1
    assert all(c.text.split('\n\n', 1)[1].startswith('| 항목 | 내용 |') for c in cs)
    assert sum(c.text.count('| 행') for c in cs) == 60


def test_no_structure_long_text():
    """제목 없이 읽힌 문서(보수 모드)도 길이 기준으로 나뉘고 글자가 빠지지 않는다."""
    text = ' '.join(f'문장 {i}번은 이렇게 끝납니다.' for i in range(400))
    cs = chunk_document(_doc(Element('paragraph', text)))
    assert len(cs) > 1 and all(c.chunk_type == 'preface' for c in cs)
    assert all(c.char_count <= MAX_CHARS + HEAD_ROOM for c in cs)
    got = ' '.join(c.text.split('\n\n', 1)[1] for c in cs)
    assert re.findall(r'문장 (\d+)번', got) == [str(i) for i in range(400)]


def test_duplicate_groups_kept():
    """여러 문서에 똑같이 들어 있는 문의처는 지우지 않고 묶음으로만 알려 준다. 열람 등급이 다르면 다른 묶음이다."""
    all_chunks = []
    for doc_no in ('IT-SW-001', 'IT-SW-002', 'IT-SW-001-M', 'IT-SW-002-M'):
        all_chunks += chunks_of(doc_no)[1]
    groups = duplicate_groups(all_chunks)
    contact = [g for g in groups if g[0].heading_path == ['6. 문의처']]
    assert len(contact) == 1 and {c.doc_no for c in contact[0]} == {'IT-SW-001', 'IT-SW-002'}
    manual = [g for g in groups if g[0].heading_path == ['6. 연락처']]
    assert len(manual) == 1 and {c.access_level for c in manual[0]} == {'사내 제한'}
    assert all(len({c.content_hash for c in g}) == 1 for g in groups)


def test_document_and_version_rows():
    """knowledge_documents·document_versions 행 (칸 이름·값은 docs/06.테이블_설계서.md)."""
    doc, _ = chunks_of('IT-NET-003-M', 'pdf')
    d = document_row(doc)
    assert (d['doc_code'], d['doc_type'], d['category_code'], d['pair_doc_code']) == ('IT-NET-003-M', 'MANUAL', 'NET', 'IT-NET-003')
    v = version_row(doc, registration={'transfer_policy': 'MASKED'})
    assert (v['version'], v['file_format'], v['view_scope'], v['transfer_policy']) == ('v2.0', 'PDF', 'AGENT', 'MASKED')
    assert 'is_current' not in v and 'ingest_status' not in v            # 적재 스크립트·활성화 함수가 정한다
    assert v['chunker_version'] == CHUNKER_VERSION and v['parser_version'] and v['ingest_meta']['parse_mode'] == 'layout'
    std = chunks_of('IT-STD-002')[0]
    assert document_row(std)['category_code'] is None and document_row(std)['doc_type'] == 'STANDARD'
    assert version_row(std)['view_scope'] == 'ALL'


def test_transfer_policy_not_inferred():
    """외부 전송은 열람 등급으로 정하지 않는다. 등록 값이 없거나 모르는 값이면 BLOCKED."""
    doc, _ = chunks_of('IT-SW-002')
    assert doc.meta['access_level'] == '사내 일반'
    assert version_row(doc)['transfer_policy'] == 'BLOCKED'
    assert version_row(doc, registration={'transfer_policy': 'allow'})['transfer_policy'] == 'BLOCKED'
    assert version_row(doc, registration={'transfer_policy': 'ALLOWED'})['transfer_policy'] == 'ALLOWED'


def test_unknown_access_level_is_narrowest():
    assert version_row(_doc(meta={'doc_no': 'IT-T-001', 'version': 'v1.0', 'access_level': '대외비'}))['view_scope'] == 'ADMIN'


def test_chunk_row():
    _, cs = chunks_of('IT-SW-002', 'pdf')
    c = next(c for c in cs if c.section_no == '3.1')
    r = chunk_row(c)
    assert r['content'] == c.body and r['heading_path'] == '3. 항목별 안내 > 3.1 유료 프로그램 라이선스 신청'
    assert r['location'].startswith('3.1 · p.') and r['unit_key'] == 'IT-SW-002@v2.0/item:3.1' and r['chunk_type'] == 'ITEM'
    assert set(r) == {'heading_path', 'location', 'content', 'seq', 'unit_key', 'chunk_type', 'part', 'meta'}
    m = r['meta']
    assert (m['inquiry_type_codes'], m['section_no'], m['team']) == (['SW-02'], '3.1', '엔드포인트지원팀')
    assert m['page_start'] and m['page_start'] <= m['page_end']
    faq = chunk_row(next(c for c in chunks_of('IT-SW-002')[1] if c.unit_key.endswith('FAQ-035')))
    assert faq['location'] == '4 · FAQ-035'


def test_meta_keys_fixed():
    """meta 키는 계약대로 항상 같다 (청크_메타데이터.md 5장)."""
    keys = {'section_no', 'inquiry_type_codes', 'page_start', 'page_end', 'props', 'subheadings', 'faq_ids',
            'images', 'handling', 'team', 'escalation_teams', 'urgency'}
    for doc_no in ('IT-SW-002', 'IT-NET-003-M', 'IT-STD-002'):
        assert all(set(chunk_row(c)['meta']) == keys for c in chunks_of(doc_no)[1])


def test_part_unique_within_unit():
    """UNIQUE(version_id, unit_key, part) 를 걸 수 있다: 한 문서 안에서 (unit_key, part)가 겹치지 않는다."""
    for doc_no in manifest():
        cs = chunks_of(doc_no)[1]
        assert len({(c.unit_key, c.part) for c in cs}) == len(cs), doc_no


def test_unit_keys():
    """unit_key = 문서@버전/종류:키. 항목·장은 절 번호, FAQ는 질문의 FAQ 번호, 없으면 순번."""
    _, cs = chunks_of('IT-SW-002')
    by = {c.chunk_key: c.unit_key for c in cs}
    assert by['IT-SW-002@v2.0#004'] == 'IT-SW-002@v2.0/item:3.1'
    assert 'IT-SW-002@v2.0/chapter:부록' in by.values()
    faqs = [c.unit_key for c in cs if c.chunk_type == 'faq']
    assert faqs == ['IT-SW-002@v2.0/faq:FAQ-023', 'IT-SW-002@v2.0/faq:FAQ-035', 'IT-SW-002@v2.0/faq:q03']
    assert unit_ref(faqs[0]) == 'IT-SW-002/faq:FAQ-023'


def test_split_parts_share_unit():
    """나뉜 조각은 같은 unit_key, 나뉘지 않은 단위끼리는 unit_key 가 겹치지 않는다."""
    for doc_no in ('IT-SW-003', 'IT-STD-002'):
        _, cs = chunks_of(doc_no)
        units = {}
        for c in cs:
            units.setdefault(c.unit_key, []).append(c)
        for parts in units.values():
            assert [c.part for c in parts] == list(range(1, parts[0].parts + 1))
            assert len({tuple(c.heading_path) for c in parts}) == 1
        assert validate(cs) == []
    item = [c for c in chunks_of('IT-SW-003')[1] if c.unit_key == 'IT-SW-003@v2.0/item:3.1']
    assert len(item) == 3 and '해결 확인' in item[-1].subheadings


def test_hashes():
    """content_hash 는 본문만 본다. 임베딩 입력(text = 머리말 + 본문)은 제목이 바뀌면 같이 바뀐다."""
    doc, cs = chunks_of('IT-SW-002')
    doc.meta['title'] = '바뀐 제목'
    cs2 = chunk_document(doc)
    for a, b in zip(cs, cs2):
        assert a.content_hash == b.content_hash and a.text != b.text
        assert a.text.endswith(a.body)


def test_validate_catches_problems():
    _, cs = chunks_of('IT-SW-003')
    assert validate([]) == ['청크가 없음']
    assert any('조각 번호' in p for p in validate([c for c in cs if c.chunk_key != 'IT-SW-003@v2.0#005']))
    big = chunk_document(_doc(Element('heading', '3. 항목별 안내', level=1), Element('heading', '3.1 긴 항목', level=2),
                              *[Element('paragraph', f'{i}번 문단입니다. ' + '가' * 300) for i in range(20)]))
    assert sum(len(c.body) for c in big) > ITEM_UNIT_MAX
    assert any('넘음' in p for p in validate(big))


def test_baseline_matches_guides_final():
    """정리본 md 57종의 문서별 청크 수·항목 수·단위 수가 기준표와 같다 (파싱 누락·규칙 변경 감지)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend', 'app', 'rag', 'chunk_baseline.json')
    with open(path, encoding='utf-8') as f:
        want = json.load(f)
    assert want['chunker_version'] == CHUNKER_VERSION
    got = baseline([c for doc_no in manifest() for c in chunks_of(doc_no)[1]])
    assert got == want['docs']


def test_manual_item_props():
    """매뉴얼 항목: team 은 1차 처리 팀, 이관 대상은 escalation_teams (가이드의 담당 부서 자리)."""
    _, cs = chunks_of('IT-NET-003-M')
    c = next(c for c in cs if c.section_no == '3.1')
    assert (c.inquiry_type_codes, c.urgency, c.access_level) == (['NET-03'], 'P1', '사내 제한')
    assert (c.team, c.escalation_teams) == ('서비스데스크', ['네트워크팀'])


@pytest.mark.parametrize('raw, want', [
    ('정보보안팀 (도용 의심 시)', ['정보보안팀']),
    ('시스템인프라팀 / 네트워크팀', ['시스템인프라팀', '네트워크팀']),
    ('ITssue 챗봇·서비스데스크', ['서비스데스크']),
    ('없음 (구매는 팀장 협의)', []),
    ('—', []),
])
def test_team_names_only(raw, want):
    """팀 칸에는 DB teams 의 팀 이름만 들어간다. 조건 메모는 props 원문에 남는다."""
    item = Element('heading', '3.1 x', level=2, meta={'props': [['1차 처리', '서비스데스크'], ['이관 대상', raw]]})
    c = chunk_document(_doc(_h('3. 증상별 처리 절차', 1), item, _p('본문')))[0]
    assert c.escalation_teams == want and c.team == '서비스데스크' and c.props['이관 대상'] == raw


# ── 검토(PR #21)에서 나온 지적 ──────────────────────────────────

def _h(text, level):
    return Element('heading', text, level=level)


def _p(text):
    return Element('paragraph', text)


def test_long_run_keeps_sentence_order():
    """마침표 없이 긴 글 앞의 문장이 뒤로 밀리지 않는다."""
    text = '앞 문장입니다. 둘째 문장입니다. ' + '가' * 2000 + '. 끝 문장입니다.'
    got = ''.join(c.body for c in chunk_document(_doc(_p(text))))
    assert got.index('앞 문장') < got.index('가' * 50) < got.index('끝 문장')


def test_ids_found_before_korean_particle():
    cs = chunk_document(_doc(_h('4. 자주 묻는 질문', 1), _p('Q. 메일이 안 보여요 FAQ-012를 보세요'), _p('A. 답변입니다.')))
    assert cs[0].faq_ids == ['FAQ-012'] and cs[0].unit_key.endswith('/faq:FAQ-012')
    item = Element('heading', '3.1 항목', level=2, meta={'props': [['문의 유형', 'SW-02와 SW-03']]})
    cs = chunk_document(_doc(_h('3. 항목별 안내', 1), item, _p('본문')))
    assert cs[0].inquiry_type_codes == ['SW-02', 'SW-03']
    assert chunk_document(_doc(_h('1. 개요', 1), Element('heading', '1.1 x', level=2, meta={'props': [['문의 유형', 'IT-SW-002']]}),
                               _p('본문')))[0].inquiry_type_codes == []     # 문서 번호의 일부는 시나리오가 아니다


def test_faq_subheading_goes_with_next_question():
    cs = chunk_document(_doc(_h('4. 자주 묻는 질문', 1), _p('Q. 첫 질문 (FAQ-001)'), _p('A. 첫 답'),
                             _h('계정', 3), _p('Q. 둘째 질문 (FAQ-002)'), _p('A. 둘째 답')))
    assert [c.chunk_type for c in cs] == ['faq', 'faq']
    assert '### 계정' not in cs[0].body and cs[1].body.startswith('### 계정\nQ. 둘째')
    assert cs[1].subheadings == ['계정'] and cs[1].unit_key.endswith('/faq:FAQ-002')


def test_faq_subsections_split_per_question():
    """FAQ 장이 5.1·5.2 하위 절로 나뉘어도 질문 하나 = 청크 하나."""
    cs = chunk_document(_doc(_h('5. 자주 묻는 질문', 1), _h('5.1 계정', 2), _p('Q. 가?'), _p('A. 가.'), _p('Q. 나?'), _p('A. 나.'),
                             _h('5.2 메일', 2), _p('Q. 다?'), _p('A. 다.')))
    assert [c.chunk_type for c in cs] == ['faq'] * 3
    assert all(c.body.count('Q. ') == 1 for c in cs)
    assert cs[2].heading_path == ['5. 자주 묻는 질문', '5.2 메일']
    assert len({c.unit_key for c in cs}) == 3


def test_subheading_not_left_alone_at_part_end():
    """소제목 줄만 앞 조각 끝에 남지 않고 내용과 같은 조각으로 간다."""
    els = [_h('3. 항목별 안내', 1), _h('3.1 긴 항목', 2), _h('이런 경우', 3), _p('가' * 880),
           _h('조치 방법', 3), *[_p(f'{i}단계 ' + '나' * 300) for i in range(6)]]
    cs = chunk_document(_doc(*els))
    assert len(cs) > 1
    assert all(not c.body.rstrip().split('\n')[-1].startswith('### ') for c in cs)
    assert any(c.body.startswith('### 조치 방법\n') for c in cs[1:])


@pytest.mark.parametrize('title', ['개정 이력', '6. 개정 이력'])
def test_revision_history_skipped(title):
    cs = chunk_document(_doc(_h('1. 개요', 1), _p('개요 본문'), _h(title, 1), _p('v1.0 처음 작성'),
                             _h('6.1 세부', 2), _p('v1.1 고침')))
    assert [c.heading_path for c in cs] == [['1. 개요']]
