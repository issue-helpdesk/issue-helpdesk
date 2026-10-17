"""Markdown 파서. 정리본(.md)의 머리말·제목·목록·표·인용·코드·그림을 읽는다.

- 머리말(front matter) → doc.meta 그대로
- '#'~'####' → level 0~3, '## 목차' 절은 건너뛴다
- 혼자 있는 굵은 줄('**목적**') → 카드 제목(level 3). '**Q. …**'은 질문 문단
- 항목 제목 바로 뒤의 '**문의 유형** SW-02 · **처리 구분** …' → 항목 제목의 meta['props']
- '![설명](경로)' → image. 바로 뒤의 '*그림 …*' 줄은 같은 설명이라 건너뛴다
"""
from __future__ import annotations

import re

from .common import TOC_TITLES, clean, finalize
from .errors import ParseError
from .models import Element, ParsedDocument

FRONT_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)
EMOJI_RE = re.compile('[\U0001F300-\U0001FAFF☀-➿]️?')
BOLD_RE = re.compile(r'(?<![\w*-])\*\*([^*\s-][^*]*?)\*\*')     # 가림 값('010-****-5678', '홍*동')은 건드리지 않는다
IMAGE_RE = re.compile(r'^!\[(.*)\]\(([^()]+)\)\s*$')            # 설명 안의 '[정보]' 같은 대괄호도 허용
_ITALIC_RE = re.compile(r'\*([^*\s][^*]*?)\*')                   # 줄 전체가 기울임인 '*…*'


def _front(text: str) -> tuple[dict, str]:
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        meta[k.strip()] = _yaml_value(v.strip())
    return meta, text[m.end():]


def _yaml_value(v: str):
    """머리말 값 하나. 목록은 '["a", "b"]' · "['a', 'b']" · '[a, b]' 모두 읽는다."""
    if v.startswith('[') and v.endswith(']'):
        items = re.findall(r'"([^"]*)"|\'([^\']*)\'|([^,\s][^,]*)', v[1:-1])
        return [next(x for x in g if x).strip() for g in items if any(x.strip() for x in g)]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    return v


def _inline(s: str) -> str:
    s = BOLD_RE.sub(r'\1', s).replace('\\|', '|').replace('<br>', '\n')
    return clean(EMOJI_RE.sub('', s))


def _table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        cells = [_inline(c) for c in re.split(r'(?<!\\)\|', ln.strip().strip('|'))]
        if any(cells) and all(re.fullmatch(r':?-{3,}:?', c.replace(' ', '')) for c in cells if c):
            continue          # 구분 줄
        rows.append(cells)
    if rows and not any(rows[0]):
        rows = rows[1:]       # 머리 없는 표(빈 머리 줄)
    return rows


def _props(line: str):
    if not line.startswith('**'):
        return None
    pairs = []
    for part in re.split(r'\s+·\s+(?=\*\*)', line):
        m = re.match(r'^\*\*([^*]+)\*\*\s*(.*)$', part)
        if not m:
            return None
        pairs.append([m.group(1).strip(), _inline(m.group(2))])
    return pairs if len(pairs) >= 2 else None


def _take(lines: list[str], i: int, cond) -> tuple[list[str], int]:
    """i 부터 cond 를 만족하는 줄을 모은다."""
    j = i
    while j < len(lines) and cond(lines[j].strip()):
        j += 1
    return lines[i:j], j


def read_text(path: str) -> tuple[str, str]:
    """utf-8(BOM 포함) → cp949 순서로 읽는다. 둘 다 아니면 ParseError('encoding')."""
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ParseError('encoding', path, 'utf-8·cp949 모두 아님')


def parse_md(path: str, safe: bool = False) -> ParsedDocument:
    """.md 와 .txt 를 읽는다 (일반 글은 줄마다 문단이 된다)."""
    text, enc = read_text(path)
    meta, body = _front(text)
    fmt = 'txt' if path.lower().endswith('.txt') else 'md'
    doc = ParsedDocument(path=path, format=fmt, properties={'title': meta.get('title', ''), 'encoding': enc}, meta=dict(meta))
    out: list[Element] = []
    lines = body.splitlines()
    in_toc = False
    last_heading: Element | None = None
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if m := re.match(r'^(#{1,6})\s+(.*)$', s):
            title = _inline(m.group(2))
            in_toc = title in TOC_TITLES
            if not in_toc:
                last_heading = Element('heading', title, level=min(len(m.group(1)) - 1, 3))
                out.append(last_heading)
            i += 1
        elif in_toc or not s:
            i += 1
        elif s.startswith('```'):
            block, j = _take(lines, i + 1, lambda x: not x.startswith('```'))
            if any(x.strip() for x in block):
                out.append(Element('paragraph', '\n'.join(block).strip(), meta={'code': True}))
            i = j + 1
        elif s.startswith('|'):
            block, i = _take(lines, i, lambda x: x.startswith('|'))
            if rows := _table_rows(block):
                out.append(Element('table', rows=rows))
        elif s.startswith('>'):
            # 문서 제목 바로 뒤의 인용 줄은 표지 줄(정리본 형식). 표지로 옮길지는 공통 후처리가 정한다
            cover = bool(out) and out[-1].kind == 'heading' and out[-1].level == 0
            block, i = _take(lines, i, lambda x: x.startswith('>'))
            for x in block:
                if t := x.strip().lstrip('>').strip():
                    out.append(Element('paragraph', _inline(t), meta={'cover_line': True} if cover else {}))
        elif img := IMAGE_RE.match(s):
            alt = _inline(img.group(1))
            out.append(Element('image', alt, meta={'name': img.group(2).rsplit('/', 1)[-1]}))
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            # 바로 뒤 '*…*' 줄은 그림 설명과 글자가 같을 때만 건너뛴다 (다르면 본문)
            same = j < len(lines) and (m := _ITALIC_RE.fullmatch(lines[j].strip())) and _inline(m.group(1)) == alt
            i = j + 1 if same else i + 1
        elif out and out[-1] is last_heading and last_heading.level == 2 and (pr := _props(s)):
            last_heading.meta['props'] = pr
            i += 1
        elif m := re.match(r'^[-*+]\s+(.*)$', s):
            out.append(Element('list_item', _inline(m.group(1))))
            i += 1
        elif m := re.match(r'^(\d{1,2})\.\s+(.*)$', s):
            out.append(Element('list_item', f'{m.group(1)}. {_inline(m.group(2))}'))
            i += 1
        elif (m := re.fullmatch(r'\*\*(.+?)\*\*', s)) and not m.group(1).startswith('Q.'):
            out.append(Element('heading', _inline(m.group(1)), level=3, meta={'card': True}))
            i += 1
        else:
            m = _ITALIC_RE.fullmatch(s)
            out.append(Element('paragraph', _inline(m.group(1) if m else s)))
            i += 1
    doc.elements = out
    return finalize(doc, safe)
