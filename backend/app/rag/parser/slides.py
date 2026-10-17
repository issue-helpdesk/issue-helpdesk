"""장표형 문서(PPTX·PDF) 공통 해석.

형식별 파서는 쪽마다 Item 목록(글 상자 · 표 · 그림 · 배경 상자)만 만들고, 제목 판단과 읽는 순서는 여기서 같은 규칙으로 정한다.

쪽 종류
- 첫 쪽(표지): 가장 큰 글자 → 문서 제목(level 0), 나머지는 본문 (표지 문구로 옮길지는 공통 후처리가 정함)
- 장 구분 쪽: 큰 장 번호('01', '부록') + 장 이름 → '1. 개요'(level 1), 그 밖의 글자는 본문
- 본문 쪽: 위쪽 띠의 가장 큰 굵은 글자 → 쪽 제목('3.1 …' level 2, '개정 이력' level 1).
  제목 띠의 장 표시와 바닥 띠의 꼬리말·쪽 번호는 뺀다.

본문 쪽 안에서
- 굵고 색 있는 13pt 이상 글자 → 소제목(level 3), 배경 상자 맨 위의 굵은 짧은 글자 → 카드 제목(level 3)
- 따로 떨어진 글머리 기호('·', '①')는 다음 글 상자와 합쳐 목록 항목으로
- 읽는 순서: 위아래로 겹치는 것끼리 행으로 묶고, 행 안에서는 칸(80pt 단위) → 위 → 왼쪽.
  카드가 나란히 있거나 왼쪽 단계 목록 + 오른쪽 그림이어도 '카드1 → 카드2', '목록 → 그림' 순서가 된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import CAPTION_RE, CIRCLED, TOC_TITLES, infer_level, split_bullet
from .models import Element

LEVEL1_PAGE_TITLES = ('개정 이력', '문서 정보') + TOC_TITLES
PAGE_NO_RE = re.compile(r'(?:p\.?\s*)?\d{1,3}(?:\s*/\s*\d{1,3})?|-\s*\d{1,3}\s*-')
INK_COLORS = ('', '1D2433', '000000')          # 본문 글자색 (이 색의 굵은 글자는 소제목이 아니다)
COLUMN_WIDTH = 80                              # 읽는 순서의 칸 단위(pt)
FOOTER_BAND = 40                               # 바닥에서 이 높이(pt) 안은 꼬리말


@dataclass
class Item:
    kind: str                      # text / table / image / box
    x: float
    y: float
    w: float
    h: float
    text: str = ''
    size: float = 0.0
    bold: bool = False
    color: str = ''                # 'RRGGBB'
    mono: bool = False
    rows: list = field(default_factory=list)
    name: str = ''
    box: 'Item | None' = None      # 이 글자를 감싼 배경 상자


def page_elements(page_no: int, items: list[Item], W: float, H: float, safe: bool = False) -> list[Element]:
    """쪽 하나 → 요소. 글자는 버리지 않는다: 본문이 아닌 글자는 이유를 붙여 'dropped' 로 넘긴다.

    - 표지(첫 쪽): 가장 큰 글자가 문서 제목, 나머지는 본문으로 읽는다. 표지 문구로 옮길지는 공통 후처리가
      문서 정보 표가 있는 템플릿 문서인지 보고 정한다.
    - 장 구분 쪽: 장 번호만 빼고 장 이름은 제목으로, 그 밖의 글자는 본문으로 읽는다.
    - 목차 쪽: 글자를 'toc' 로 뺀다 (보수 모드에서는 본문으로 남긴다).
    - safe=True(보수 모드): 제목 띠·꼬리말 띠의 글자도 본문으로 남긴다.
    """
    texts = [t for t in items if t.kind == 'text']
    if not texts and not any(t.kind in ('table', 'image') for t in items):
        return []
    out: list[Element] = []
    skip: list[Item] = []
    title = None
    if page_no == 1:
        title = max(texts, key=lambda t: t.size) if texts else None
        if title is not None:
            out.append(Element('heading', title.text, level=0, page=1))
    elif (div := _divider(texts)) is not None:
        num, name = div
        head = f'{int(num.text)}. {name.text}' if num.text.isdigit() else f'부록 · {name.text}'
        out += [Element('heading', head, level=1, page=page_no), _dropped(num, 'divider', page_no)]
        skip = [num, name]
    else:
        title = _page_title(texts, H)
        if title is not None:
            level = 1 if title.text in LEVEL1_PAGE_TITLES else (infer_level(title.text) or 2)
            out.append(Element('heading', title.text, level=level, page=page_no))
            if title.text in TOC_TITLES and not safe:
                return out + [_dropped(t, 'toc', page_no) for t in texts if t is not title]
    out += _body(page_no, [it for it in items if it not in skip], title, H, safe)
    return out


def _dropped(it: Item, why: str, page_no: int) -> Element:
    """본문에서 빼는 글자. 공통 후처리가 doc.dropped 로 옮기고, 누락 감지가 이유를 보고 판단한다."""
    return Element('dropped', it.text, page=page_no, meta={'why': why})


def _divider(texts: list[Item]) -> tuple[Item, Item] | None:
    """장 구분 쪽이면 (장 번호, 장 이름). 큰 장 번호와 그 아래 큰 장 이름이 있어야 한다."""
    num = next((t for t in texts if divider_like(t)), None)
    if num is None:
        return None
    name = next((t for t in texts if t is not num and t.size >= 24), None)
    return (num, name) if name is not None else None


def divider_like(it: Item) -> bool:
    """장 구분 쪽의 큰 장 번호('01', '부록')."""
    return it.size >= 36 and (bool(re.fullmatch(r'\d{2}', it.text)) or it.text == '부록')


def _page_title(texts: list[Item], H: float) -> Item | None:
    top = [t for t in texts if t.y < H * 0.16 and t.bold and t.size >= 15]
    return max(top, key=lambda t: t.size) if top else None


def _inside(box: Item, it: Item) -> bool:
    cx, cy = it.x + min(it.w, 30) / 2, it.y + min(it.h, 20) / 2
    return box.x - 1 <= cx <= box.x + box.w + 1 and box.y - 1 <= cy <= box.y + box.h + 1


def reading_order(items: list[Item]) -> list[Item]:
    def span(it):
        b = it.box or it
        return b.y, b.y + max(b.h, 1)

    rows: list[list[Item]] = []
    bottom = 0.0
    for it in sorted(items, key=lambda t: (span(t)[0], t.x)):
        top, bot = span(it)
        if rows and top < bottom - 2:
            rows[-1].append(it)
            bottom = max(bottom, bot)
        else:
            rows.append([it])
            bottom = bot
    return [it for row in rows for it in sorted(row, key=lambda t: (int((t.box or t).x // COLUMN_WIDTH), t.y, t.x))]


def _body(page_no: int, items: list[Item], title: Item | None, H: float, safe: bool = False) -> list[Element]:
    title_bottom = (title.y + title.h) if (title and page_no != 1) else H * 0.12
    boxes = [t for t in items if t.kind == 'box']
    body = []
    dropped = []
    for it in items:
        if it is title or it.kind == 'box':
            continue
        if it.kind == 'text':
            footer = it.y > H - FOOTER_BAND
            header = it.y < H * 0.16 and it.y + it.h <= title_bottom + 4
            if (footer or header) and PAGE_NO_RE.fullmatch(it.text):
                dropped.append(_dropped(it, 'page_no', page_no))     # 쪽 번호는 머리·바닥 띠의 숫자만
                continue
            if not safe and (footer or header):
                dropped.append(_dropped(it, 'band', page_no))        # 꼬리말·제목 띠의 장 표시
                continue
        elif not safe and it.kind == 'image' and it.y > H - FOOTER_BAND:
            dropped.append(Element('dropped', it.name, page=page_no, meta={'why': 'band_image'}))   # 바닥 띠 그림(로고 등). 표는 본문에 남긴다
            continue
        inside = [b for b in boxes if _inside(b, it)]
        it.box = min(inside, key=lambda b: b.w * b.h) if inside else None
        body.append(it)

    first_in_box = {}
    for it in sorted(body, key=lambda t: (t.y, t.x)):
        if it.box is not None and it.kind == 'text':
            first_in_box.setdefault(id(it.box), it)

    out: list[Element] = []
    pending = None             # 따로 떨어진 글머리 기호
    for it in reading_order(body):
        if it.kind == 'table':
            if it.rows:
                out.append(Element('table', rows=it.rows, page=page_no))
            pending = None
            continue
        if it.kind == 'image':
            out.append(Element('image', page=page_no, meta={'name': it.name}))
            pending = None
            continue
        t = it.text
        if t in ('·', '•', '▶') or t in CIRCLED or re.fullmatch(r'\d{1,2}\.', t):
            pending = None if t == '▶' else t
            continue
        if CAPTION_RE.match(t) and out and out[-1].kind == 'image' and not out[-1].text:
            out[-1].text = t
            continue
        # 표지 쪽의 굵은 문구(문서 번호 줄·열람 배지)는 소제목이 아니라 표지 문구다
        if page_no != 1 and pending is None and (level3 := _subheading(it, first_in_box.get(id(it.box)) is it)):
            out.append(Element('heading', t, level=3, page=page_no, meta={'card': True} if level3 == 'card' else {}))
            continue
        if pending is not None:
            t = f'{CIRCLED.index(pending) + 1}. {t}' if pending in CIRCLED else (f'{pending} {t}' if pending.endswith('.') else t)
            out.append(Element('list_item', t, page=page_no))
            pending = None
            continue
        bullet, b = split_bullet(t)
        out.append(Element('list_item' if bullet else 'paragraph', b if bullet else t, page=page_no,
                           meta={'code': True} if it.mono else {}))
    return out + dropped


def _subheading(it: Item, first_in_box: bool) -> str | None:
    """소제목이면 'heading', 카드 제목이면 'card'."""
    color = it.color.upper()
    if not it.bold or color == 'FFFFFF' or it.text.startswith(('★', '※')) or len(it.text) > 60:
        return None
    if it.size >= 13 and color not in INK_COLORS:
        return 'heading'
    if first_in_box and 10.5 <= it.size < 13 and len(it.text) <= 40:
        return 'card'
    return None


def attach_captions(out: list[Element]) -> None:
    """설명 없는 그림 뒤(같은 쪽, 다음 제목·그림 전)의 '그림 …' 문단을 그림 설명으로 붙인다.
    그림 오른쪽에 설명 점(①②…)이 있으면 그림 아래 설명이 그 뒤에 읽히므로 몇 줄 떨어질 수 있다."""
    for i, e in enumerate(out):
        if e.kind != 'image' or e.text:
            continue
        for f in out[i + 1:i + 16]:
            if f.page != e.page or f.kind in ('heading', 'image'):
                break
            if f.kind == 'paragraph' and CAPTION_RE.match(f.text):
                e.text = f.text
                f.kind = '_drop'
                break
    out[:] = [e for e in out if e.kind != '_drop']
