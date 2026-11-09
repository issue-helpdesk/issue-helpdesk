"""파싱 결과 → 가이드 md (app.rag.parser.to_md) 를 검사한다. DB 없이 돈다.

완료 기준: dataset/guides 57종 × 4형식(md·docx·pptx·pdf) 모두, 바꾼 md 를 다시 파싱·청킹하면 원래 파일의 청크와 같다.
md 에 자리가 없는 쪽 번호·그림 내용 해시와, md 파서가 원래 지우는 이모지는 빼고 비교한다.
"""
import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from app.rag.chunker import chunk_document
from app.rag.ingest import GUIDES
from app.rag.ingest.upload import check_images, to_checked_md
from app.rag.parser import parse
from app.rag.parser.common import clean
from app.rag.parser.md_parser import EMOJI_RE
from app.rag.parser.models import Element, ParsedDocument
from app.rag.parser.to_md import to_guide_md

FIELDS = ('chunk_key', 'chunk_type', 'section_no', 'heading_path', 'text', 'body', 'props', 'subheadings', 'part',
          'parts', 'faq_ids', 'inquiry_type_codes', 'handling', 'team', 'escalation_teams', 'urgency', 'images')
DOCS = sorted(p.with_suffix('') for p in GUIDES.rglob('IT-*.md'))


def _norm(v):
    """md 파서가 하는 정리(이모지 빼기·빈칸 줄이기)와 머리말의 줄바꿈 → 빈칸."""
    if isinstance(v, str):
        return '\n'.join(clean(EMOJI_RE.sub('', line)) for line in v.split('\n'))
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {_norm(k): _norm(x) for k, x in v.items() if k != 'sha256'}
    return v


def _sig(chunks):
    return [_norm({f: getattr(c, f) for f in FIELDS}) for c in chunks]


def _reparse(md: str, tmp_path: Path, name='doc.md'):
    p = tmp_path / name
    p.write_text(md, encoding='utf-8')
    return parse(str(p))


def test_all_guides_all_formats_same_chunks(tmp_path):
    assert len(DOCS) == 57
    for base in DOCS:
        for fmt in ('md', 'docx', 'pptx', 'pdf'):
            f = base.with_name(base.name + '.' + fmt)
            a = parse(str(f))
            b = _reparse(to_guide_md(a), tmp_path)
            assert _sig(chunk_document(b)) == _sig(chunk_document(a)), f.name
            assert _norm({k: ' '.join(v.split('\n')) if isinstance(v, str) else
                          [' '.join(x.split('\n')) for x in v] if isinstance(v, list) else v
                          for k, v in a.meta.items()}) == _norm(b.meta), f.name


def test_md_source_round_trip_is_exact(tmp_path):
    """정리본 md 는 이모지까지 그대로 (md 파서가 이미 지웠다)."""
    for base in DOCS[:10]:
        a = parse(str(base.with_name(base.name + '.md')))
        b = _reparse(to_guide_md(a), tmp_path)
        assert [c.text for c in chunk_document(b)] == [c.text for c in chunk_document(a)]


def test_lost_only_pages_and_image_hash(tmp_path):
    """빠지는 것: pptx·pdf 쪽 번호, docx·pptx 그림 sha256. 그림 이름표(key)·설명은 남는다."""
    f = GUIDES / 'SW' / 'guide'
    pptx = next(f.glob('IT-SW-001_*.pptx'))
    a = parse(str(pptx))
    ca, cb = chunk_document(a), chunk_document(_reparse(to_guide_md(a), tmp_path))
    assert any(c.page_start for c in ca) and not any(c.page_start for c in cb)
    ia = [{k: v for k, v in i.items() if k != 'sha256'} for c in ca for i in c.images]
    assert ia and ia == [i for c in cb for i in c.images] and any('sha256' in i for c in ca for i in c.images)


def _doc(*els, meta=None):
    return ParsedDocument(path='x.docx', format='docx', meta=meta or {'doc_no': 'IT-SW-009', 'title': '시험',
                                                                     'category': 'SW', 'version': 'v1.0'},
                          elements=[Element('heading', '시험', level=0), Element('heading', '3. 항목별 안내', level=1),
                                    *els])


def _preface_doc():
    """템플릿이 아닌 문서: 장 제목 앞에 표지 쪽 글·덧붙인 표·그림이 있다 (사람이 만든 pdf·docx 에서 본 모양)."""
    return ParsedDocument(path='x.pdf', format='pdf', meta={'title': '업무용 SW 안내'}, elements=[
        Element('heading', '업무용 SW 안내', level=0),
        Element('image', '', meta={}),
        Element('paragraph', '서비스데스크 | 2026.10.06 | Ver 1.0'),
        Element('paragraph', '본 가이드는 교육용 가상 안내문입니다.'),
        Element('table', rows=[['검색 키워드', 'VPN, 원격 접속, VPN-1001']]),
        Element('heading', '1. 설치 전 확인', level=1),
        Element('paragraph', '설치 전에 저장 공간을 확인합니다.'),
        Element('heading', '2. 설치 방법', level=1),
        Element('paragraph', '소프트웨어 센터에서 설치합니다.')])


def test_preface_kept_before_toc(tmp_path):
    """첫 장 앞 서문은 '## 목차' 앞에 써야 남는다 (목차 뒤에 쓰면 md_parser 가 목차 절로 보고 건너뛴다)."""
    a = _preface_doc()
    md = to_guide_md(a)
    assert md.index('본 가이드는') < md.index('## 목차') < md.index('## 1. 설치 전 확인')
    assert re.search(r'^## 목차\n\n- 1\. 설치 전 확인\n- 2\. 설치 방법$', md, re.M)
    ca, cb = chunk_document(a), chunk_document(_reparse(md, tmp_path, 'x.md'))
    assert [c.chunk_type for c in cb] == ['preface', 'chapter', 'chapter']
    assert _sig(cb) == _sig(ca)                                    # 원래 파일을 직접 적재한 청크와 같다
    assert 'VPN-1001' in cb[0].body and cb[0].images == []         # 형식 모르는 그림(pdf)은 이름표 없음


def test_preface_only_image_no_empty_chunk(tmp_path):
    """서문이 그림 하나뿐이어도 원래 청크와 같다 (빈 청크·이름표가 새로 생기지 않는다)."""
    a = ParsedDocument(path='x.pdf', format='pdf', meta={'title': '안내'}, elements=[
        Element('heading', '안내', level=0), Element('image', '', meta={}),
        Element('heading', '1. 개요', level=1), Element('paragraph', '본문')])
    ca, cb = chunk_document(a), chunk_document(_reparse(to_guide_md(a), tmp_path, 'x.md'))
    assert _sig(cb) == _sig(ca)
    assert all(not c.images for c in cb)


def test_no_chapter_heading_keeps_everything(tmp_path):
    """장 제목이 하나도 없는 문서: 목차가 없고 글이 모두 남는다."""
    a = ParsedDocument(path='x.pdf', format='pdf', meta={'title': '메모'}, elements=[
        Element('heading', '메모', level=0), Element('paragraph', '첫 문단'), Element('paragraph', '둘째 문단')])
    md = to_guide_md(a)
    assert '## 목차' not in md
    assert _sig(chunk_document(_reparse(md, tmp_path, 'x.md'))) == _sig(chunk_document(a))


def test_markdown_like_paragraphs_stay_paragraphs(tmp_path):
    texts = ['# 제목 아님', '| 표 아님 |', '> 인용 아님', '- 목록 아님', '1. 번호 아님', '![그림](a.png)',
             '```', '*기울임*', '**굵게만**']
    a = _doc(Element('heading', '3.1 항목', level=2), *[Element('paragraph', t) for t in texts])
    b = _reparse(to_guide_md(a), tmp_path)
    paras = [e for e in b.elements if e.kind == 'paragraph']
    assert [e.text for e in paras] == texts


def test_props_newlines_tables_images(tmp_path):
    a = _doc(Element('heading', '3.1 항목', level=2, meta={'props': [['문의 유형', 'SW-01']]}),
             Element('paragraph', '첫 줄\n둘째 줄'),
             Element('table', rows=[['칸 | 하나', '줄\n바꿈'], ['a', 'b']]),
             Element('image', '그림 3.1-1. 화면', meta={'name': 'image7.png', 'ext': 'png'}),
             Element('image', '그림 3.1-2. pdf 그림', meta={}),
             Element('heading', '3.2 둘째', level=2, meta={'props': [['문의 유형', 'SW-02'], ['담당 부서', '서비스데스크']]}))
    md = to_guide_md(a)
    assert '![그림 3.1-1. 화면](../images/IT-SW-009_3.1-1.png)' in md
    assert '![그림 3.1-2. pdf 그림](../images/IT-SW-009_3.1-2)' in md
    assert '**문의 유형** SW-02 · **담당 부서** 서비스데스크' in md
    assert re.search(r'^- 3\. 항목별 안내\n  - 3\.1 항목\n  - 3\.2 둘째$', md, re.M)       # 목차
    b = _reparse(md, tmp_path)
    heads = [e for e in b.elements if e.kind == 'heading' and e.level == 2]
    assert [h.meta.get('props') for h in heads] == [[['문의 유형', 'SW-01']], [['문의 유형', 'SW-02'], ['담당 부서', '서비스데스크']]]
    assert next(e.text for e in b.elements if e.kind == 'paragraph') == '첫 줄\n둘째 줄'
    assert next(e.rows for e in b.elements if e.kind == 'table') == [['칸 | 하나', '줄\n바꿈'], ['a', 'b']]
    imgs = [i['key'] for c in chunk_document(b) for i in c.images]
    assert imgs == ['SW/IT-SW-009_3.1-1.png']                         # 형식을 모르는 그림은 이름표 없음 (pdf 와 같다)


@pytest.mark.parametrize('fmt', ['docx', 'pptx', 'pdf'])
def test_front_matter_from_document_info(fmt, tmp_path):
    f = next((GUIDES / 'ACC' / 'guide').glob(f'IT-ACC-001_*.{fmt}'))
    md = to_guide_md(parse(str(f)))
    assert md.startswith('---\ndoc_no: "IT-ACC-001"\n') and '\nversion: "v2.0"\n' in md
    assert re.search(r'^## 3\. ', md, re.M) and re.search(r'^## 개정 이력$', md, re.M)


def test_literal_markup_kept(tmp_path):
    """글 안의 md 표기도 글자 그대로 (검수 4): '<br>'·'**'·역슬래시+세로줄. 문단·목록·표 칸·그림 설명·제목 모두."""
    lit = 'HTML 태그 <br>를 입력 · **굵게** · a\\|b · 별 ***'
    a = _doc(Element('heading', '3.1 ' + lit, level=2), Element('paragraph', lit), Element('list_item', lit),
             Element('table', rows=[['머리', lit], ['칸', lit]]), Element('image', '그림 3.1-1. ' + lit, meta={}))
    b = _reparse(to_guide_md(a), tmp_path)
    got = {e.kind: e.text or e.rows for e in b.elements if e.kind != 'heading' or e.level == 2}
    assert got == {'heading': '3.1 ' + lit, 'paragraph': lit, 'list_item': lit, 'table': [['머리', lit], ['칸', lit]],
                   'image': '그림 3.1-1. ' + lit}


def test_separator_like_table_rows_kept(tmp_path):
    """'---' 만 든 데이터 행도 남는다 (검수 3. md 파서는 둘째 줄만 구분 줄로 본다)."""
    rows = [['항목', '값'], ['---', '---'], ['a', 'b'], [':---:', '']]
    b = _reparse(to_guide_md(_doc(Element('table', rows=rows))), tmp_path)
    assert next(e.rows for e in b.elements if e.kind == 'table') == rows


def test_front_matter_quotes(tmp_path):
    """하나짜리 값은 따옴표가 둘 다 있어도, 바깥이 따옴표여도 그대로 (검수 5)."""
    meta = {'doc_no': 'IT-SW-009', 'title': '"O\'Reilly"', 'category': 'SW', 'version': 'v1.0',
            'keywords': ['큰"따옴표', "작은'따옴표", '쉼표, 있음']}
    b = _reparse(to_guide_md(_doc(meta=meta)), tmp_path)
    assert b.meta['title'] == meta['title'] and b.meta['keywords'] == meta['keywords']


def _with_changed_image(src: Path, dst: Path) -> None:
    """docx 안 첫 png 를 다른 그림으로 바꾼 사본 (배포 그림과 내용이 달라진 현행 가이드)."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w') as zout:
        first = next(n for n in zin.namelist() if n.startswith('word/media/') and n.endswith('.png'))
        for item in zin.infolist():
            data = zin.read(item.filename)
            zout.writestr(item, data + b'changed' if item.filename == first else data)


def test_checked_md_drops_changed_images(tmp_path):
    """검수 1: 문서 안 그림이 배포 그림과 다르면 변환 전에 골라, md 에서도 이름표가 생기지 않게 한다 (업로드 적재와 같은 결과)."""
    src = next((GUIDES / 'SW' / 'guide').glob('IT-SW-002_*.docx'))
    same_md, same_w = to_checked_md(parse(str(src)))
    keys = [i['key'] for c in chunk_document(_reparse(same_md, tmp_path, 'same.md')) for i in c.images]
    assert same_w == [] and keys
    changed = tmp_path / 'changed.docx'
    _with_changed_image(src, changed)
    doc = parse(str(changed))
    direct = chunk_document(doc)
    expect_warn = check_images(direct)                              # 원래 파일을 업로드 적재할 때의 결과
    md, warnings = to_checked_md(doc)
    got = [i['key'] for c in chunk_document(_reparse(md, tmp_path, 'changed.md')) for i in c.images]
    assert warnings == expect_warn and len(warnings) == 1 and '배포 그림과 달라' in warnings[0]
    assert got == [i['key'] for c in direct for i in c.images] and len(got) == len(keys) - 1


def test_duplicate_figure_number_drops_all(tmp_path):
    """재검수 2: 같은 그림 번호를 쓰는 그림 중 하나만 배포 그림과 달라도, md 에서는 구분할 수 없으니 그 번호 그림을 모두 뺀다."""
    (tmp_path / 'img' / 'SW').mkdir(parents=True)
    png = b'deployed'
    (tmp_path / 'img' / 'SW' / 'IT-SW-009_3.1-1.png').write_bytes(png)
    same = hashlib.sha256(png).hexdigest()
    doc = _doc(Element('heading', '3.1 항목', level=2),
               Element('image', '그림 3.1-1. 원래 화면', meta={'ext': 'png', 'sha256': same}),
               Element('image', '그림 3.1-1. 바뀐 화면', meta={'ext': 'png', 'sha256': 'other'}))
    md, warnings = to_checked_md(parse_again(doc), tmp_path / 'img')
    assert len(warnings) == 2 and '배포 그림과 달라' in warnings[0] and '같은 그림 번호' in warnings[1]
    assert [i for c in chunk_document(_reparse(md, tmp_path)) for i in c.images] == []
    assert md.count('](../images/IT-SW-009_3.1-1)') == 2                  # 두 그림 모두 형식 없는 링크 (본문 설명은 남음)
    one = _doc(Element('heading', '3.1 항목', level=2),
               Element('image', '그림 3.1-1. 원래 화면', meta={'ext': 'png', 'sha256': same}))
    md, warnings = to_checked_md(parse_again(one), tmp_path / 'img')
    assert warnings == [] and [i['key'] for c in chunk_document(_reparse(md, tmp_path)) for i in c.images] == ['SW/IT-SW-009_3.1-1.png']


def parse_again(doc):
    """손으로 만든 문서에 파서 후처리(제목 경로 등)를 입힌다."""
    from app.rag.parser.common import assign_sections
    assign_sections(doc)
    return doc


def test_code_with_fence_lines_kept(tmp_path):
    """재검수 1: 코드 글 안의 '```' 줄은 더 긴 울타리로 감싸, 다시 읽어도 코드가 끊기거나 제목이 생기지 않는다."""
    code = 'echo before\n```\n## 4. 실제로는 코드\n````\necho after'
    b = _reparse(to_guide_md(_doc(Element('paragraph', code, meta={'code': True}))), tmp_path)
    assert [(e.kind, e.text) for e in b.elements if e.kind != 'heading' or e.level != 0][1:] == [('paragraph', code)]


def test_pptx_monospace_code_round_trip(tmp_path):
    """pptx 의 고정폭(Consolas) 글은 코드 문단이 된다. 그 안의 '```' 줄도 md 로 바꿨다 다시 읽으면 그대로."""
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = '시험 문서'
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = '3. 항목별 안내'
    tf = s.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3)).text_frame
    lines = ['echo before', '```', '## 4. 실제로는 코드', 'echo after']
    for k, line in enumerate(lines):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text, run.font.name, run.font.size = line, 'Consolas', Pt(12)
    f = tmp_path / 'code.pptx'
    prs.save(f)
    a = parse(str(f))
    codes = [e.text for e in a.elements if e.meta.get('code')]
    assert codes and '```' in codes[0].split('\n')                       # 실제로 코드 문단이 된다 (검수 재현과 같은 조건)
    b = _reparse(to_guide_md(a), tmp_path)
    assert [e.text for e in b.elements if e.meta.get('code')] == codes
    assert [e.text for e in b.headings()] == [e.text for e in a.headings()]


def test_md_fence_close_rule(tmp_path):
    """md 코드 닫기: 여는 줄 백틱 수 이상으로 시작하는 줄 (뒤 글자 허용, 예전과 같음). 더 짧은 '```' 줄은 코드 내용."""
    md = ('---\ntitle: "t"\n---\n\n# t\n\n## 1. 개요\n\n```bash\necho a\n```end\n\n본문 하나\n\n'
          '````\necho b\n```\n## 2. 코드 안\n````\n\n본문 둘\n')
    b = _reparse(md, tmp_path)
    assert [(e.kind, e.text) for e in b.elements if e.kind != 'heading'] == [
        ('paragraph', 'echo a'), ('paragraph', '본문 하나'), ('paragraph', 'echo b\n```\n## 2. 코드 안'), ('paragraph', '본문 둘')]
    assert [e.text for e in b.headings()] == ['t', '1. 개요']
