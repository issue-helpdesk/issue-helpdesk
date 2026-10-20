"""PDF 파서 (pdfplumber). 글자 위치·크기·굵기·색으로 글 상자를 다시 만들어 공통 장표 해석(slides.py)에 넘긴다.

1. 줄: 같은 높이의 글자를 묶고, 아무것도 없는 넓은 간격에서 다른 칸(카드 등)으로 나눈다.
2. 글 상자: 왼쪽 시작(또는 가운데)·글자 모양이 같고 줄 간격만큼 이어지는 줄들. 글머리('•', '①')로 시작하는 줄은 새 상자.
3. 표: 칸 테두리가 있는 표만 표로 꺼내고 그 안의 글자는 본문에서 뺀다. 칸이 하나뿐인 테두리(카드)는 표가 아니다.
4. 배경 상자: 큰 사각형(카드·안내 상자·그림 틀).

한계: 스캔 PDF(글자 없음)는 경고만 남긴다. 선 없는 표는 문단으로 나온다.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter

import pdfplumber

from .common import BULLET_RE, clean, finalize
from .models import Element, ParsedDocument
from .slides import Item, attach_captions, page_elements

logging.getLogger('pdfminer').setLevel(logging.ERROR)


def _hex(color) -> str:
    """pdfplumber 색(회색 1값 · RGB 3값 · CMYK 4값) → 'RRGGBB'."""
    try:
        vals = list(color or [])
    except TypeError:
        return ''
    if len(vals) == 1:
        vals *= 3
    elif len(vals) == 4:
        c, m, y, k = vals
        vals = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    if len(vals) != 3:
        return ''
    return ''.join(f'{max(0, min(255, round(v * 255))):02X}' for v in vals)


def _inside(c: dict, bbox) -> bool:
    x0, top, x1, bottom = bbox
    return x0 <= (c['x0'] + c['x1']) / 2 <= x1 and top <= (c['top'] + c['bottom']) / 2 <= bottom


class _Seg:
    """한 줄 안의 이어진 글자 묶음."""

    def __init__(self, chars: list[dict]):
        parts, prev = [], None
        for c in chars:
            if prev is not None and c['text'] != ' ' and prev['text'] != ' ' and c['x0'] - prev['x1'] > 0.25 * c['size']:
                parts.append(' ')
            parts.append(c['text'])
            prev = c
        ink = [c for c in chars if c['text'].strip()]
        self.text = clean(''.join(parts))
        self.x0 = min(c['x0'] for c in ink)
        self.x1 = max(c['x1'] for c in ink)
        self.top = min(c['top'] for c in ink)
        self.bottom = max(c['bottom'] for c in ink)
        self.size = statistics.median(c['size'] for c in ink)
        self.bold = sum('bold' in c['fontname'].lower() for c in ink) >= 0.6 * len(ink)
        self.mono = any(k in ink[0]['fontname'].lower() for k in ('mono', 'courier', 'consol'))
        self.color = Counter(_hex(c.get('non_stroking_color')) for c in ink).most_common(1)[0][0]
        m = BULLET_RE.match(self.text)
        self.marker = bool(m)
        self.text_x = self.x0          # 글머리 뒤 본문 시작 x (여러 줄 목록의 둘째 줄은 여기서 시작)
        if m:
            n = 0
            for c in ink:
                n += len(c['text'])
                if n > len(m.group(1)):
                    self.text_x = c['x0']
                    break


class _Block:
    """글 상자 하나 = 이어지는 줄들."""

    def __init__(self, seg: _Seg):
        self.segs = [seg]
        self.x0, self.text_x = seg.x0, seg.text_x

    @property
    def last(self) -> _Seg:
        return self.segs[-1]

    def accepts(self, s: _Seg) -> bool:
        last = self.last
        same_left = abs(s.x0 - self.text_x) <= 1.5 or abs(s.x0 - self.x0) <= 1.5
        centered = abs((s.x0 + s.x1) / 2 - (last.x0 + last.x1) / 2) <= 2       # 가운데 정렬 (그림 설명)
        return ((same_left or centered) and abs(s.size - last.size) < 0.3 and s.color == last.color
                and (s.bold == last.bold or same_left) and 0.5 * s.size <= s.top - last.top <= 1.9 * s.size)

    def item(self) -> Item:
        first = self.segs[0]
        x0 = min(s.x0 for s in self.segs)
        return Item('text', x0, first.top, max(s.x1 for s in self.segs) - x0, self.last.bottom - first.top,
                    text=('\n' if first.mono else ' ').join(s.text for s in self.segs),
                    size=first.size, bold=first.bold, color=first.color, mono=first.mono)


def _segments(chars: list[dict]) -> list[_Seg]:
    lines: list[list[dict]] = []
    for c in sorted(chars, key=lambda c: (round(c['top']), c['x0'])):
        if lines and abs(c['top'] - lines[-1][0]['top']) <= 0.5 * max(c['size'], 4):
            lines[-1].append(c)
        else:
            lines.append([c])
    segs = []
    for line in lines:
        cur, prev = [], None
        for c in sorted(line, key=lambda c: c['x0']):
            # 빈칸 글자로 이어진 곳(코드의 긴 공백 등)은 끊지 않고, 아무것도 없는 넓은 간격에서만 끊는다
            if c['text'].strip() and prev is not None and c['x0'] - prev['x1'] > max(1.2 * c['size'], 8):
                if any(x['text'].strip() for x in cur):
                    segs.append(_Seg(cur))
                cur = []
            cur.append(c)
            prev = c
        if any(x['text'].strip() for x in cur):
            segs.append(_Seg(cur))
    return segs


def _blocks(segs: list[_Seg]) -> list[Item]:
    open_, done = [], []
    for s in sorted(segs, key=lambda s: (s.top, s.x0)):
        target = None if s.marker else next((b for b in open_ if b.accepts(s)), None)
        if target is None:
            open_.append(_Block(s))
        else:
            target.segs.append(s)
        # 한참 지난 상자는 닫는다
        done += [b for b in open_ if s.top - b.last.top > 2.5 * max(b.last.size, 4)]
        open_ = [b for b in open_ if s.top - b.last.top <= 2.5 * max(b.last.size, 4)]
    return [b.item() for b in done + open_]


def _page_items(pg) -> list[Item]:
    W, H = float(pg.width), float(pg.height)
    items: list[Item] = []
    table_boxes = []
    for t in pg.find_tables():
        rows = []
        for r in t.extract():
            cells = [clean(c or '').replace('\n', ' ') for c in r]
            if any(cells):
                rows.append(cells)
        if sum(1 for r in rows for c in r if c) <= 1:
            continue          # 칸 하나짜리 테두리(카드·안내 상자) → 글자는 본문으로
        x0, top, x1, bottom = t.bbox
        table_boxes.append(t.bbox)
        items.append(Item('table', x0, top, x1 - x0, bottom - top, rows=rows))
    chars = [c for c in pg.chars if not any(_inside(c, b) for b in table_boxes)]
    items += _blocks(_segments(chars))
    for im in pg.images:
        w, h = im['x1'] - im['x0'], im['bottom'] - im['top']
        if w > 30 and h > 30:
            items.append(Item('image', im['x0'], im['top'], w, h, name=str(im.get('name', ''))))
    for r in pg.rects:
        w, h = r['x1'] - r['x0'], r['bottom'] - r['top']
        if w > 60 and h > 30 and not (w > W * 0.95 and h > H * 0.95) and not any(_inside(r, b) for b in table_boxes):
            items.append(Item('box', r['x0'], r['top'], w, h))
    return items


def parse_pdf(path: str, safe: bool = False) -> ParsedDocument:
    doc = ParsedDocument(path=path, format='pdf')
    out = []
    with pdfplumber.open(path) as pdf:
        md = pdf.metadata or {}
        doc.properties = {k.lower(): md.get(k, '') or '' for k in ('Title', 'Author', 'Producer', 'Creator')}
        doc.properties['pages'] = len(pdf.pages)
        n_chars = 0
        for pi, pg in enumerate(pdf.pages, start=1):
            n_chars += len(pg.chars)
            try:
                out += page_elements(pi, _page_items(pg), float(pg.width), float(pg.height), safe)
            except Exception as ex:          # 한 쪽이 깨져도 나머지는 읽고, 그 쪽은 글자만이라도 남긴다
                doc.warnings.append(f'{pi}쪽 해석 실패 → 글자만 추출 ({type(ex).__name__}: {ex})')
                out += _plain_page(pg, pi)
    if n_chars == 0:
        doc.warnings.append('글자가 없는 PDF (스캔 이미지일 수 있음) — OCR 필요')
    attach_captions(out)
    doc.elements = out
    return finalize(doc, safe)


def _plain_page(pg, page_no: int) -> list[Element]:
    try:
        text = pg.extract_text() or ''
    except Exception:
        return []
    return [Element('paragraph', ln, page=page_no) for ln in clean(text).split('\n') if ln]
