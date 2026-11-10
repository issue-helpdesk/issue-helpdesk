"""파싱 결과(ParsedDocument) → 가이드 md (정리본과 같은 모양).

시스템 안의 가이드는 md 로 통일한다 (11.06 결정). 현행이 docx·pptx·pdf 인 가이드를 가이드화할 때 기준 md 로 쓰고,
나중에 업로드 때도 같은 함수로 md 를 만든다. 만든 md 를 다시 파싱·청킹하면 원래 파일의 청크와 같다
(tests/test_to_md.py, dataset/guides 57종 × 4형식). 다만 md 에 자리가 없는 것은 빠진다:
- 쪽 번호 (pptx·pdf 의 page_start·page_end)
- 문서 안 그림의 내용 해시 (docx·pptx 의 그림 sha256). 그래서 배포 그림과 다른 그림은 변환 **전에** 골라
  drop_images 로 넘긴다 (ingest/upload.py to_checked_md. 그 그림은 형식 없는 링크 → 이름표 없이 본문 설명만.
  링크는 이름표로만 그림을 가리키므로, 같은 그림 번호를 쓰는 그림 중 하나라도 빠지면 그 번호 그림은 모두 뺀다 —
  이 경우만 원래 파일을 직접 적재한 것보다 그림이 적다)
- 이모지 (★·🟢 …. md 파서가 원래 지운다. 정리본 md 청크와 같아진다)
- 머리말 목록 값 하나에 큰따옴표·작은따옴표가 둘 다 있으면 그대로 못 쓴다 (md_parser 머리말 문법에 이스케이프가 없다)

    from app.rag.parser import parse
    from app.rag.parser.to_md import to_guide_md
    md = to_guide_md(parse('IT-SW-001_….pdf'))      # md 글자열. 파일은 쓰지 않는다 (저장은 부른 쪽)

모양 (md_parser 가 읽는 문법만 쓴다)
- 머리말: doc.meta 를 front matter 로 (목록은 ["a", "b"]). 줄바꿈은 빈칸으로
- '# 제목', 표지 줄은 '> …', 첫 장 앞 서문, '## 목차' (장·3.x 항목. 파서는 읽지 않고 가이드화가 한 줄 더한다)
- 제목 수준 1·2·3 → '##'·'###'·'####', 카드 제목('목적' 등) → '**목적**'
- 항목 머리 정보: '**문의 유형** SW-01 · **처리 구분** …' (하나뿐이면 한 줄 표 — 파서가 둘 이상일 때만 머리 정보로 읽는다)
- 문단·목록·표 칸 안 줄바꿈은 '<br>' (파서가 줄바꿈으로 되돌린다. 요소 경계가 바뀌면 청크 경계가 바뀐다)
- 그림: '![설명](../images/{문서 번호}_{그림 번호}.{형식})' (그림 이름 규칙. 형식을 모르면(pdf) 확장자 없이)
- 코드(md 코드 블록, pptx·pdf 고정폭 글): '```' 울타리. 글 안에 '```' 줄이 있으면 더 긴 울타리
- md 문법으로 시작하는 문단('# …'·'| …'·'- …' 등)은 앞에 폭 없는 빈칸(U+200B)을 둬 문단으로 남긴다 (파서가 지운다)
- 글 안의 '**'·'<br>'·역슬래시+세로줄도 사이에 U+200B 를 넣어 글자 그대로 남긴다 (파서가 굵게·줄바꿈·칸 구분으로 읽지 않게)
"""
from __future__ import annotations

import re

from .common import FIGURE_NO_RE
from .models import Element, ParsedDocument

# 머리말 순서 (정리본 md 와 같게. 나머지 키는 뒤에)
FRONT_ORDER = ('doc_no', 'title', 'category', 'category_name', 'doc_type', 'doc_kind', 'access_level', 'audience',
               'version', 'effective_date', 'owner', 'approver', 'author', 'target', 'readers', 'pair',
               'scenarios', 'faqs', 'keywords')
MD_START_RE = re.compile(r'^(#{1,6}\s|\||>|```|!\[|[-*+]\s|\d{1,2}\.\s|\*)')   # md_parser 가 문단이 아닌 것으로 읽는 시작
NUMBERED_RE = re.compile(r'^\d{1,2}\.\s')
ZERO_WIDTH = '​'
BACKSLASH_BAR = '\\|'


def to_guide_md(doc: ParsedDocument, drop_images: frozenset[str] | set[str] = frozenset()) -> str:
    """drop_images: 링크에 형식을 넣지 않을 그림 이름표 ('SW/IT-SW-002_3.1-1.png'). 청커가 그 이름표를 만들지 않는다."""
    meta = dict(doc.meta)
    img = (meta.get('category', ''), meta.get('doc_no', ''), frozenset(drop_images))
    out = _front(meta)
    els = doc.elements
    start = 0
    if els and els[0].kind == 'heading' and els[0].level == 0:
        title, start = els[0].text, 1
    else:
        title = meta.get('title') or doc.title
    if title:
        out += [f'# {_inline(title)}', '']
        if cover := doc.properties.get('cover'):
            out += [f'> {_inline(c)}  ' for c in cover] + ['']
    # 첫 장 앞 서문(표지로 빠지지 않은 글·표·그림. 템플릿이 아닌 문서, 장 앞에 덧붙인 표)은 목차 **앞**에 쓴다.
    # md_parser 는 '## 목차' 부터 다음 제목까지 건너뛰므로, 목차 뒤에 쓰면 서문이 사라진다 (청커는 서문을 preface 청크로 남긴다)
    first = next((i for i, e in enumerate(els) if i >= start and e.kind == 'heading' and e.level == 1), len(els))
    for e in els[start:first]:
        out += _element(e, img, out)
    out += _toc(els)
    for e in els[first:]:
        out += _element(e, img, out)
    return '\n'.join(out).rstrip('\n') + '\n'


def _element(e: Element, img: tuple, out: list[str]) -> list[str]:
    if e.kind == 'heading':
        t = _inline(e.text)
        head = f'**{t}**' if e.meta.get('card') and e.level == 3 else '#' * ((e.level or 0) + 1) + ' ' + t
        lines = [head, '']
        if props := e.meta.get('props'):
            if len(props) >= 2:
                lines += [' · '.join(f'**{k}** {_inline(v)}' for k, v in props), '']
            else:
                lines += _table([list(p) for p in props]) + ['']
        return lines
    if e.kind == 'paragraph':
        if e.meta.get('code'):     # md 코드 블록, pptx·pdf 의 고정폭(Consolas 등) 글
            return [_fence(e.text), e.text, _fence(e.text), '']
        return [_paragraph(e.text), '']
    if e.kind == 'list_item':
        t = _inline(e.text)
        if len(out) >= 2 and out[-1] == '' and (out[-2].startswith('- ') or NUMBERED_RE.match(out[-2])):
            out.pop()                                       # 이어지는 목록은 빈 줄 없이
        return [t if NUMBERED_RE.match(t) else f'- {t}', '']
    if e.kind == 'table':
        return _table(e.rows) + [''] if e.rows else []
    if e.kind == 'image':
        return [_image(e, *img), '']
    return [_paragraph(e.text), ''] if e.text else []


def _front(meta: dict) -> list[str]:
    keys = [k for k in FRONT_ORDER if k in meta] + [k for k in meta if k not in FRONT_ORDER]
    out = ['---']
    for k in keys:
        v = meta[k]
        if isinstance(v, list):
            out.append(f'{k}: [' + ', '.join(_quote_item(x) for x in v) + ']')
        else:
            out.append(f'{k}: "{_one_line(v)}"')     # md_parser 는 바깥 따옴표 한 쌍만 벗긴다 → 안의 따옴표는 그대로 남는다
    return out + ['---', '']


def _quote_item(v) -> str:
    """목록 값. 따옴표 안에 같은 따옴표를 못 쓰므로 없는 쪽으로 감싼다 (둘 다 있으면 그대로, 모듈 설명의 한계)."""
    v = _one_line(v)
    return f'"{v}"' if '"' not in v else f"'{v}'" if "'" not in v else v


def _one_line(v) -> str:
    return ' '.join(str(v).split('\n'))


def _inline(text: str) -> str:
    """글자 그대로 남길 md 표기('**'·'<br>'·역슬래시+세로줄)를 U+200B 로 끊고, 줄바꿈은 '<br>' 로."""
    t = re.sub(r'\*(?=\*)', '*' + ZERO_WIDTH, text or '')
    t = t.replace('<br>', '<br' + ZERO_WIDTH + '>').replace(BACKSLASH_BAR, '\\' + ZERO_WIDTH + '|')
    return t.replace('\n', '<br>')


def _fence(code: str) -> str:
    """코드 울타리. 글 안 줄이 '```' 로 시작하면 그보다 하나 긴 백틱으로 연다 (md_parser 는 여는 줄 이상 길이의 백틱 줄에서 닫는다)."""
    runs = [len(s) - len(s.lstrip('`')) for s in (line.strip() for line in code.split('\n'))]
    return '`' * max([3] + [n + 1 for n in runs if n >= 3])


def _paragraph(text: str) -> str:
    t = _inline(text)
    return ZERO_WIDTH + t if MD_START_RE.match(t) else t


def _cell(c: str) -> str:
    return _inline((c or '').strip()).replace('|', BACKSLASH_BAR)


def _table(rows: list[list[str]]) -> list[str]:
    n = max(len(r) for r in rows)
    rows = [[_cell(c) for c in r] + [''] * (n - len(r)) for r in rows]
    return ['| ' + ' | '.join(rows[0]) + ' |', '|' + ' --- |' * n] + ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]


def _image(e: Element, category: str, doc_no: str, drop: frozenset[str]) -> str:
    """그림 이름 규칙 {문서 번호}_{그림 번호}.{형식}. 청커는 링크에서 형식(확장자)만 읽고 이름표는 설명의 그림 번호로 만든다
    (chunker._images 와 같은 이름표). drop 에 든 이름표는 형식을 빼서 이름표가 생기지 않게 한다."""
    no = FIGURE_NO_RE.match(e.text or '')
    ext = e.meta.get('ext', '')
    if no and f'{category}/{doc_no}_{no.group(1)}.{ext}' in drop:
        ext = ''
    if doc_no and no:
        name = f'{doc_no}_{no.group(1)}' + (f'.{ext}' if ext else '')
    else:
        name = re.sub(r'[\s()]+', '_', e.meta.get('name') or '그림')
    return f'![{_inline(e.text)}](../images/{name})'


def _toc(els: list[Element]) -> list[str]:
    """목차: 장과 3.x 항목. md_parser 는 '## 목차' 절을 건너뛴다. 가이드화가 3.x 줄 뒤에 한 줄 더한다."""
    lines = []
    for e in els:
        if e.kind == 'heading' and e.level == 1:
            lines.append(f'- {e.text}')
        elif e.kind == 'heading' and e.level == 2 and re.match(r'^\d+\.\d+\s', e.text):
            lines.append(f'  - {e.text}')
    return ['## 목차', '', *lines, ''] if lines else []
