"""PPTX 파서. 슬라이드마다 글 상자·표·그림·배경 상자를 읽어 공통 장표 해석(slides.py)에 넘긴다.

- 글 상자 하나(줄바꿈된 여러 줄)는 문단 하나로 합친다. 코드 글꼴(Consolas)이면 줄을 살린다.
- 글자 크기·굵기·색은 첫 글자 묶음(run) 기준으로 본다.
"""
from __future__ import annotations

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .common import clean, finalize
from .models import Element, ParsedDocument
from .slides import Item, attach_captions, page_elements

PT = 12700          # EMU per point


def _items(shapes, W, H):
    for sh in shapes:
        try:
            x, y = (sh.left or 0) / PT, (sh.top or 0) / PT
            w, h = (sh.width or 0) / PT, (sh.height or 0) / PT
        except (AttributeError, ValueError):
            continue
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _items(sh.shapes, W, H)
            continue
        if getattr(sh, 'has_table', False) and sh.has_table:
            rows = []
            for r in sh.table.rows:
                cells = [clean(c.text) for c in r.cells if not c.is_spanned]
                if any(cells):
                    rows.append(cells)
            yield Item('table', x, y, w, h, rows=rows)
        elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            yield Item('image', x, y, w, h, name=getattr(sh, 'name', ''))
        elif sh.has_text_frame and sh.text_frame.text.strip():
            yield _text_item(sh, x, y, w, h)
        elif w > 60 and h > 30 and not (w > W * 0.95 and h > H * 0.95):
            yield Item('box', x, y, w, h)      # 카드·안내 상자·그림 틀 (배경 전체는 제외)


def _text_item(sh, x, y, w, h) -> Item:
    tf = sh.text_frame
    runs = [r for p in tf.paragraphs for r in p.runs if r.text.strip()]
    lines = [clean(p.text) for p in tf.paragraphs]
    mono = any((r.font.name or '').lower().startswith('consolas') for r in runs)
    sizes = [r.font.size.pt for r in runs if r.font.size]
    try:
        color = str(runs[0].font.color.rgb) if runs and runs[0].font.color and runs[0].font.color.type else ''
    except AttributeError:
        color = ''
    return Item('text', x, y, w, h,
                text=('\n' if mono else ' ').join(ln for ln in lines if ln),
                size=max(sizes) if sizes else 0.0,
                bold=bool(runs) and all(r.font.bold for r in runs),
                color=color, mono=mono)


def parse_pptx(path: str, safe: bool = False) -> ParsedDocument:
    prs = Presentation(path)
    cp = prs.core_properties
    doc = ParsedDocument(path=path, format='pptx',
                         properties={'title': cp.title or '', 'author': cp.author or '',
                                     'modified': str(cp.modified or ''), 'keywords': cp.keywords or '',
                                     'pages': len(prs.slides)})
    W = (prs.slide_width or 960 * PT) / PT
    H = (prs.slide_height or 540 * PT) / PT
    out = []
    for si, slide in enumerate(prs.slides, start=1):
        try:
            out += page_elements(si, list(_items(slide.shapes, W, H)), W, H, safe)
        except Exception as ex:          # 한 장이 깨져도 나머지는 읽고, 그 장은 글자만이라도 남긴다
            doc.warnings.append(f'{si}번 슬라이드 해석 실패 → 글자만 추출 ({type(ex).__name__}: {ex})')
            out += _plain_slide(slide, si)
    attach_captions(out)
    doc.elements = out
    return finalize(doc, safe)


def _plain_slide(slide, page_no: int) -> list[Element]:
    out = []
    for sh in slide.shapes:
        try:
            if getattr(sh, 'has_text_frame', False) and sh.has_text_frame and (t := clean(sh.text_frame.text)):
                out.append(Element('paragraph', t.replace('\n', ' '), page=page_no))
        except Exception:
            continue
    return out
