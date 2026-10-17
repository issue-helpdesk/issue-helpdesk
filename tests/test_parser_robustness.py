"""공통 파서 안전장치 테스트: 깨진 파일·미지원 형식은 원인 있는 ParseError, 낯선 배치의 문서는 내용을 빠뜨리지 않는다."""
import glob
import logging
import os
import shutil
from pathlib import Path

import pytest

from app.rag.parser import ParseError, parse
from check_guides import ROOT as FINAL

OLD = os.path.join(os.path.dirname(__file__), '..', 'dataset', 'guides')     # 정리 전 원본 (배치가 다른 문서)


def final(rel_glob):
    found = glob.glob(os.path.join(FINAL, rel_glob))
    if not found:
        pytest.skip('dataset/guides_final 없음')
    return found[0]


def chars(doc):
    return sum(len(e.text) + sum(len(c) for r in (e.rows or []) for c in r) for e in doc.elements)


# ---------------------------------------------------------------- 파일 점검 → ParseError

@pytest.mark.parametrize('name, data, reason', [
    ('a.hwp', b'hello', 'unsupported'),
    ('a.xlsx', b'PK', 'unsupported'),
    ('empty.docx', b'', 'empty'),
    ('empty.md', b'', 'empty'),
    ('notzip.docx', b'this is not a zip file', 'corrupt'),
    ('legacy.pptx', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 100, 'encrypted'),
    ('fake.pdf', b'not a pdf at all', 'corrupt'),
])
def test_bad_files_raise_parse_error(tmp_path, name, data, reason):
    p = tmp_path / name
    p.write_bytes(data)
    with pytest.raises(ParseError) as ei:
        parse(str(p))
    assert ei.value.reason == reason
    assert ei.value.message                       # 사용자에게 보여 줄 문구


def test_unsupported_has_convert_hint(tmp_path):
    p = tmp_path / 'x.hwp'
    p.write_bytes(b'x')
    with pytest.raises(ParseError) as ei:
        parse(str(p))
    assert 'DOCX' in ei.value.message


def test_not_found():
    with pytest.raises(ParseError) as ei:
        parse('없는_파일.docx')
    assert ei.value.reason == 'not_found'


def test_truncated_pptx(tmp_path):
    src = final('SW/guide/IT-SW-002_*.pptx')
    p = tmp_path / 'cut.pptx'
    p.write_bytes(Path(src).read_bytes()[:3000])
    with pytest.raises(ParseError) as ei:
        parse(str(p))
    assert ei.value.reason == 'corrupt'


def test_encrypted_pdf(tmp_path):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.append(PdfReader(final('SW/guide/IT-SW-002_*.pdf')))
    w.encrypt('pw')
    p = tmp_path / 'locked.pdf'
    with open(p, 'wb') as f:
        w.write(f)
    with pytest.raises(ParseError) as ei:
        parse(str(p))
    assert ei.value.reason == 'encrypted'


def test_scanned_pdf_has_no_text(tmp_path):
    from PIL import Image
    p = tmp_path / 'scan.pdf'
    Image.new('RGB', (600, 800), 'white').save(p)
    with pytest.raises(ParseError) as ei:
        parse(str(p))
    assert ei.value.reason == 'no_text'


def test_failure_is_logged(tmp_path, caplog):
    p = tmp_path / 'a.hwp'
    p.write_bytes(b'x')
    with caplog.at_level(logging.WARNING, logger='app.rag.parser'):
        with pytest.raises(ParseError):
            parse(str(p))
    assert any('a.hwp' in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- 읽을 수 있는 변형

def test_cp949_text(tmp_path):
    p = tmp_path / 'memo.txt'
    p.write_bytes('사내 공지\n프린터 점검 안내'.encode('cp949'))
    doc = parse(str(p))
    assert doc.properties['encoding'] == 'cp949'
    assert '프린터 점검 안내' in [e.text for e in doc.elements]


def test_uppercase_extension(tmp_path):
    p = tmp_path / 'UPPER.DOCX'
    shutil.copy(final('SW/guide/IT-SW-002_*.docx'), p)
    assert parse(str(p)).meta['doc_no'] == 'IT-SW-002'


def test_broken_page_is_isolated(monkeypatch):
    """한 쪽 해석이 실패해도 나머지는 읽고, 그 쪽은 글자만 남긴 뒤 경고를 남긴다."""
    from app.rag.parser import pdf_parser
    real = pdf_parser.page_elements

    def flaky(page_no, *a, **k):
        if page_no == 5:
            raise RuntimeError('테스트용 고장')
        return real(page_no, *a, **k)
    monkeypatch.setattr(pdf_parser, 'page_elements', flaky)
    doc = parse(final('SW/guide/IT-SW-002_*.pdf'), safe=False)
    assert any('5쪽 해석 실패' in w for w in doc.warnings)
    assert any(e.page == 5 for e in doc.elements)


# ---------------------------------------------------------------- 누락 감지

@pytest.mark.parametrize('rel', ['SW/guide/IT-SW-002_*.pdf', 'SYS/guide/IT-SYS-005_*.pptx', 'HW/manual/IT-HW-001-M_*.docx'])
def test_final_guides_keep_layout_mode(rel):
    doc = parse(final(rel))
    assert doc.quality['mode'] == 'layout'
    assert doc.quality['coverage'] >= 0.98


def test_foreign_layout_switches_to_safe_mode():
    """정리본과 배치가 다른 문서(정리 전 HW PDF): 배치 규칙으로는 글자 대부분이 빠지므로 보수 모드로 읽는다."""
    pdf = glob.glob(os.path.join(OLD, 'HW', 'guide', 'IT-HW-001_*.pdf'))
    docx = glob.glob(os.path.join(OLD, 'HW', 'guide', 'IT-HW-001_*.docx'))
    if not pdf or not docx:
        pytest.skip('dataset/guides 없음')
    doc = parse(pdf[0])
    assert doc.quality['mode'] == 'safe'
    assert doc.quality['coverage'] >= 0.98
    assert chars(doc) >= 0.8 * chars(parse(docx[0]))
    assert any('보수 모드' in w for w in doc.warnings)


def _assess_after(path, fmt, pick):
    """정상 파싱 결과에서 pick(요소 목록)이 고른 요소를 지운 뒤 누락 감지를 다시 돌린다."""
    from app.rag.parser.quality import assess, raw_pieces
    doc = parse(path)
    assert doc.quality['ok']
    victims = pick(doc.elements)
    assert victims
    doc.elements = [e for e in doc.elements if e not in victims]
    return assess(doc, raw_pieces(path, fmt)), victims


def _has(e, text):
    return text in e.text or any(text in c for r in (e.rows or []) for c in r)


def test_coverage_detects_deliberate_loss():
    """누락 감지 자체 검증: 결과에서 문단 하나를 지우면 포함률이 떨어지고, 지운 문장이 missing 에 나온다."""
    q, victims = _assess_after(final('SW/guide/IT-SW-002_*.docx'), 'docx',
                               lambda els: [e for e in els if e.kind == 'list_item' and len(e.text) > 30][:1])
    assert q['coverage'] < 1.0
    assert any(victims[0].text[:20] in m for m in q['missing'])


def test_long_paragraph_loss_is_flagged_even_if_ratio_is_high():
    """긴 문서에서 40자 넘는 문단 하나를 지우면 포함률은 98%를 넘어도 long_missing 으로 잡힌다."""
    q, _ = _assess_after(final('SYS/guide/IT-SYS-005_*.docx'), 'docx',
                         lambda els: [e for e in els if e.kind == 'list_item' and len(e.text) > 45][:1])
    assert q['coverage'] >= 0.98
    assert q['long_missing'] and not q['ok']


def test_repeated_sentence_loss_is_counted():
    """원문에 여러 번 나오는 같은 문장은 하나만 지워도 잡힌다 (예전에는 하나만 남아도 '있음'으로 통과)."""
    q, _ = _assess_after(final('SYS/guide/IT-SYS-003_*.docx'), 'docx',
                         lambda els: [e for e in els if e.text.startswith('단계 2. 그룹웨어 공지사항과')][1:2])
    assert q['coverage'] < 1.0
    assert any(m.startswith('단계 2. 그룹웨어 공지사항과') for m in q['missing'])


def test_missing_code_value_is_flagged():
    """숫자·코드가 결과에서 통째로 사라지면 missing_values 로 잡힌다."""
    q, _ = _assess_after(final('ACC/guide/IT-ACC-001_*.md'), 'md',
                         lambda els: [e for e in els if _has(e, 'AUTH-105')])
    assert 'AUTH-105' in q['missing_values'] and not q['ok']


def test_too_many_accepted_drops_is_suspicious():
    """정상 제외(목차 등)로 뺀 글자가 15%를 넘으면 배치 규칙이 본문을 뺀 것으로 의심한다."""
    from app.rag.parser.models import Element, ParsedDocument
    from app.rag.parser.quality import assess
    doc = ParsedDocument(path='mem', format='pptx')
    doc.elements = [Element('paragraph', '남은 본문 한 줄')]
    doc.dropped = [['toc', f'목차로 뺀 긴 문장 번호 {i} 입니다', 2] for i in range(10)]
    q = assess(doc, ['남은 본문 한 줄'] + [t for _, t, _ in doc.dropped])
    assert q['coverage'] == 1.0
    assert q['dropped_ratio'] > 0.15 and not q['ok']


# ---------------------------------------------------------------- 점검 보고서(2026-10-17) 재현 사례

def _slide_doc(items, safe=False):
    from app.rag.parser.common import finalize
    from app.rag.parser.models import ParsedDocument
    from app.rag.parser.slides import page_elements
    doc = ParsedDocument(path='mem', format='pptx')
    doc.elements = page_elements(2, items, 960, 540, safe)
    return finalize(doc, safe)


def test_divider_page_keeps_body_text():
    """1) 장 구분 쪽 모양이어도 다른 본문 글자는 본문으로 남는다. 정당한 제외는 장 번호뿐이다."""
    from app.rag.parser.slides import Item
    doc = _slide_doc([Item('text', 50, 200, 60, 60, text='01', size=40, bold=True),
                      Item('text', 50, 280, 300, 40, text='Overview', size=28, bold=True),
                      Item('text', 50, 350, 300, 20, text='Critical unique instruction', size=12)])
    assert doc.outline() == [(1, '1. Overview')]
    assert 'Critical unique instruction' in [e.text for e in doc.elements]
    assert [d[:2] for d in doc.dropped] == [['divider', '01']]


def test_md_italic_after_image_is_kept(tmp_path):
    """2) 그림 뒤 기울임 줄은 그림 설명과 다르면 본문이다. md 도 원문 대비 포함률을 잰다."""
    p = tmp_path / 'a.md'
    p.write_text('# Title\n![image](a.png)\n*Critical instruction*\n', encoding='utf-8')
    doc = parse(str(p))
    assert 'Critical instruction' in [e.text for e in doc.elements if e.kind == 'paragraph']
    assert doc.quality['coverage'] == 1.0


def test_md_loss_is_detected(monkeypatch, tmp_path):
    """2) md 파서가 문단을 잃으면 포함률이 떨어진다 (예전에는 md 원문 비교가 없어 늘 1.0)."""
    from app.rag.parser import md_parser
    p = tmp_path / 'b.md'
    p.write_text('# Title\n## 1. Body\nKeep this\nLose this sentence\n', encoding='utf-8')
    real = md_parser.finalize

    def lossy(doc, safe=False):
        doc.elements = [e for e in doc.elements if e.text != 'Lose this sentence']
        return real(doc, safe)
    monkeypatch.setattr(md_parser, 'finalize', lossy)
    doc = parse(str(p))
    assert doc.quality['coverage'] < 0.98
    assert any('원문 글자 포함률' in w for w in doc.warnings)


def test_preface_stays_in_body(tmp_path):
    """3) 문서 정보 표가 없는 일반 문서의 서문은 표지로 옮기지 않고 본문에 남긴다."""
    p = tmp_path / 'c.md'
    p.write_text('# Title\nCritical preface\n## Body\nBody text\n', encoding='utf-8')
    doc = parse(str(p))
    assert 'Critical preface' in [e.text for e in doc.elements]
    assert 'cover' not in doc.properties


def test_template_cover_still_moves():
    """3) 정리본(템플릿 문서)의 표지 문구는 계속 properties['cover'] 로 간다."""
    for rel in ('SW/guide/IT-SW-002_*.md', 'SW/guide/IT-SW-002_*.docx', 'SW/guide/IT-SW-002_*.pptx'):
        doc = parse(final(rel))
        assert any('IT-SW-002' in c for c in doc.properties.get('cover', [])), rel
        assert not any(e.kind == 'paragraph' and e.text.startswith('IT-SW-002 |') for e in doc.elements), rel


@pytest.mark.parametrize('safe', [False, True])
def test_number_only_body_text_is_kept(safe):
    """4) 숫자만 있는 본문(포트 443 등)은 남기고, 쪽 번호는 머리·바닥 띠의 숫자만 뺀다."""
    from app.rag.parser.slides import Item
    doc = _slide_doc([Item('text', 50, 40, 400, 30, text='Title', size=22, bold=True),
                      Item('text', 50, 200, 100, 20, text='443', size=12),
                      Item('text', 50, 230, 300, 20, text='Retained body', size=12),
                      Item('text', 880, 512, 60, 10, text='3 / 9', size=8)], safe)
    assert '443' in [e.text for e in doc.elements]
    assert ['page_no', '3 / 9', 2] in doc.dropped


def test_yaml_lists_without_quotes(tmp_path):
    """5) 따옴표 없는 목록·작은따옴표 목록도 읽는다."""
    p = tmp_path / 'd.md'
    p.write_text("---\nscenarios: [ACC-01, SEC-01]\nfaqs: ['FAQ-1', \"FAQ-2\"]\ntitle: T\n---\n# T\n## 1. 개요\ntext\n",
                 encoding='utf-8')
    doc = parse(str(p))
    assert doc.meta['scenarios'] == ['ACC-01', 'SEC-01']
    assert doc.meta['faqs'] == ['FAQ-1', 'FAQ-2']


def test_nested_table_text_is_kept():
    """칸 안의 표(그림 + 설명)도 읽는다."""
    p = glob.glob(os.path.join(OLD, 'SEC', 'guide', 'IT-SEC-001_*.docx'))
    if not p:
        pytest.skip('dataset/guides 없음')
    doc = parse(p[0])
    body = ' '.join([e.text for e in doc.elements] + [c for e in doc.tables() for r in e.rows for c in r])
    assert '그림 3.1.' in body
    assert doc.quality['coverage'] >= 0.98
