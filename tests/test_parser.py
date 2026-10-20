"""공통 파서(M2-1-1) 테스트. 기준 문서는 dataset/guides_final (원천 JSON 하나에서 pdf·pptx·docx·md를 만든 정리본)."""
import json
import os
import re

import pytest

from app.rag.parser import parse
from check_guides import ROOT, expected, score

FORMATS = ('md', 'docx', 'pptx', 'pdf')
# 형식별 특징이 다른 문서: A 장애 대응(카드·그림), B 신청(표), M 매뉴얼(항목 머리 7개), D 사용 안내, 공통 기준
SAMPLES = ['IT-ACC-001', 'IT-SW-002', 'IT-SYS-007', 'IT-NET-003-M', 'IT-STD-001']


def manifest():
    p = os.path.join(ROOT, 'manifest.json')
    if not os.path.exists(p):
        pytest.skip('dataset/guides_final 없음')
    with open(p, encoding='utf-8') as f:
        return {d['doc_no']: d for d in json.load(f)}


def load(doc_no, fmt):
    m = manifest()[doc_no]
    with open(os.path.join(ROOT, 'tools', 'source', m['category'], doc_no + '.json'), encoding='utf-8') as f:
        src = json.load(f)
    return parse(os.path.join(ROOT, m['files'][fmt])), src


@pytest.mark.parametrize('fmt', FORMATS)
@pytest.mark.parametrize('doc_no', SAMPLES)
def test_matches_source(doc_no, fmt):
    """원천 JSON과 비교: 제목 순서가 같고, 원천 내용이 모두 들어 있고, 항목 머리·메타데이터가 같다."""
    doc, src = load(doc_no, fmt)
    eo, et, ep = expected(src)
    sc = score(doc, eo, et, ep, src['meta'])
    assert sc['outline_exact'], [x for x in sc['opcodes'] if x[0] != 'equal'][:5]
    assert sc['coverage'] >= 0.99, sc['missing'][:5]
    assert sc['props'] == 1.0
    assert sc['meta']


@pytest.mark.parametrize('fmt', FORMATS)
def test_same_result_across_formats(fmt):
    """같은 문서는 형식이 달라도 제목 경로와 항목 머리가 같다."""
    base, _ = load('IT-SW-002', 'md')
    doc, _ = load('IT-SW-002', fmt)
    assert doc.outline() == base.outline()
    props = lambda d: {e.text: e.meta.get('props') for e in d.headings() if e.level == 2}
    assert props(doc) == props(base)


def test_section_path_and_props():
    doc, _ = load('IT-ACC-001', 'docx')
    item = next(e for e in doc.elements if e.kind == 'list_item' and e.section[-1:] == ['조치 방법'])
    assert item.section[0] == '3. 증상별 조치 방법'
    assert item.section[1].startswith('3.')
    head = next(e for e in doc.headings() if e.text == item.section[1])
    assert dict(head.meta['props'])['문의 유형'].startswith('ACC-')


def test_meta_normalized():
    doc, _ = load('IT-NET-003-M', 'pdf')
    m = doc.meta
    assert m['doc_no'] == 'IT-NET-003-M' and m['doc_type'] == 'manual'
    assert m['access_level'] == '사내 제한'
    assert m['category'] == 'NET'
    assert isinstance(m['scenarios'], list) and m['scenarios']


def test_no_noise_lines():
    """꼬리말·쪽 번호·장 표시·목차가 본문에 섞이지 않는다."""
    for fmt in ('pptx', 'pdf'):
        doc, _ = load('IT-SW-002', fmt)
        texts = [e.text for e in doc.elements if e.kind in ('paragraph', 'list_item')]
        assert not any(t.startswith('©') or re.fullmatch(r'\d+ / \d+', t) for t in texts)
        assert not any(t in ('Contents', '문서 정보') for t in texts)
        assert not any(t.startswith('03. ') for t in texts)


def test_unsupported_format():
    from app.rag.parser import ParseError
    with pytest.raises(ParseError) as ei:
        parse('a.hwp')
    assert ei.value.reason == 'unsupported'
