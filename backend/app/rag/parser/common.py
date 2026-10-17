"""형식 공통 도구와 후처리.

형식별 파서는 읽는 순서대로 요소(제목·문단·목록·표·그림)만 만들고, `finalize()`가 모든 형식을 같은 모양으로 맞춘다.

1. normalize_headings  장 제목 표기 통일('01  개요' → '1. 개요'), '(계속)'·반복 제목 제거, 목차 건너뛰기
2. collapse_props      항목(3.x) 머리 정보(문의 유형·처리 구분·담당 부서 …) → 항목 제목의 meta['props']
3. qa_tables           '질문 | 답변' 표 → 'Q. …' / 'A. …' 문단
4. extract_meta        첫 장 앞의 문서 정보 표 → doc.info · doc.meta, 표지 문구 → doc.properties['cover']
5. assign_sections     요소마다 제목 경로(section)
"""
from __future__ import annotations

import re

from .models import Element, ParsedDocument

# 항목(3.x) 머리 정보의 이름
PROPS_KEYS = ('문의 유형', '처리 구분', '담당 부서', '기본 긴급도', '1차 처리', '이관 대상', '관련 FAQ', '처리 방식', '처리 기간')

# 문서 정보 표의 이름 → 메타데이터 키 (정리본 .md 머리말과 같은 이름)
INFO_MAP = {
    '문서 번호': 'doc_no', '버전': 'version', '분류': 'category', '시행일': 'effective_date', '문서 유형': 'doc_kind',
    '열람 등급': 'access_level', '보안 등급': 'access_level', '관리 부서': 'owner', '승인자': 'approver', '작성자': 'author',
    '대상': 'target', '열람 대상': 'readers', '담당자 매뉴얼': 'pair', '대상 사용자 가이드': 'pair',
    '포함 시나리오': 'scenarios', '관련 FAQ': 'faqs', '키워드': 'keywords',
}
LIST_META = ('scenarios', 'faqs', 'keywords')

TOC_TITLES = ('Contents', 'CONTENTS', '목차')
SKIP_TITLES = ('문서 정보',) + TOC_TITLES          # 본문 제목으로 남기지 않는 쪽 제목

CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
BULLET_RE = re.compile(r'^\s*([•·▪◦‣\-–]|[①-⑳]|\d{1,2}[.)](?=\s))\s*')
NUM_RE = re.compile(r'(?:^|·\s*)(\d{1,2}(?:\.\d{1,2})*)(\.)?\s+\S')
CHAPTER_RE = re.compile(r'^(?:0(\d)\s+|(\d{1,2})\.?\s+(?=\D))(.+)$')   # '04 7개 분류…'처럼 0 붙은 번호는 늘 장 번호
CAPTION_RE = re.compile(r'^그림\s*[\d.-]+')
_SPACE_RE = re.compile(r'[ \t 　]+')
_CTRL_RE = re.compile(r'[\x00-\x08\x0c\x0e-\x1f​﻿]')       # 글꼴에 없는 글자가 \x00 으로 나오는 PDF 등


# ---------------------------------------------------------------- 글자 도구

def clean(text: str) -> str:
    """공백을 하나로 줄이고 빈 줄·제어 문자를 지운다. 줄바꿈은 남긴다."""
    if not text:
        return ''
    text = _CTRL_RE.sub('', text.replace('\r', '\n').replace('\x0b', '\n'))
    lines = [_SPACE_RE.sub(' ', ln).strip() for ln in text.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def split_bullet(text: str) -> tuple[bool, str]:
    """글머리 기호를 떼어 낸다. 순서 번호(①, 1.)는 '1. '로 바꿔 남긴다(절차 순서가 의미가 있음)."""
    m = BULLET_RE.match(text)
    if not m:
        return False, text
    mark = m.group(1)
    body = text[m.end():].strip()
    if mark in CIRCLED:
        return True, f'{CIRCLED.index(mark) + 1}. {body}'
    if re.fullmatch(r'\d{1,2}[.)]', mark):
        return True, f'{mark[:-1]}. {body}'
    return True, body


def infer_level(text: str) -> int | None:
    """번호로 제목 수준을 정한다. '3. 증상별 …' → 1, '3.1 …' → 2, '3.1.2 …' → 3."""
    t = text.strip()
    if t in ('부록', '개정 이력') or t.startswith('부록 ·'):
        return 1
    found = NUM_RE.findall(t)
    if not found:
        return None
    num, dot = found[-1]
    depth = num.count('.') + 1
    if depth == 1 and not dot:
        return None          # '3 개월' 같은 일반 문장
    return min(depth, 3)


def chapter_label(text: str) -> str:
    """장 제목 표기 통일: '01  개요' · '01. 개요' → '1. 개요', '부록  관련 문서' → '부록 · 관련 문서'."""
    t = text.strip()
    m = CHAPTER_RE.match(t)
    if m:
        return f'{int(m.group(1) or m.group(2))}. {m.group(3).strip()}'
    m = re.match(r'^부록\s*[·:]?\s*(.+)$', t)
    if m:
        return f'부록 · {m.group(1).strip()}'
    return t


# ---------------------------------------------------------------- 후처리 단계

def _drop(doc: ParsedDocument, why: str, e: Element) -> None:
    doc.dropped.append([why, e.text or ' '.join(c for r in (e.rows or []) for c in r), e.page])


def normalize_headings(doc: ParsedDocument) -> None:
    """제목 정리: 표기 통일 → 목차 빼기 → 반복 제목 빼기. 뺀 것은 이유와 함께 doc.dropped 에 남긴다."""
    for e in doc.elements:
        if e.kind == 'heading':
            e.text = re.sub(r'\s*\(계속\)\s*$', '', e.text).strip()
            if e.text == '개정 이력' or e.text.startswith('부록'):
                e.level = 1
            if e.level == 1:
                e.text = chapter_label(e.text)
    _drop_toc(doc)
    _drop_repeated_titles(doc)


def _drop_toc(doc: ParsedDocument) -> None:
    """'문서 정보'·'Contents' 쪽 제목을 빼고, 'Contents'·'목차' 뒤는 다음 장 제목까지 뺀다."""
    out, in_toc = [], False
    for e in doc.elements:
        if e.kind == 'heading' and e.text in SKIP_TITLES:
            in_toc = e.text in TOC_TITLES
            _drop(doc, 'skip_title', e)
        elif in_toc and not (e.kind == 'heading' and e.level is not None and e.level <= 1):
            _drop(doc, 'toc', e)
        else:
            in_toc = False if e.kind == 'heading' else in_toc
            out.append(e)
    doc.elements = out


def _drop_repeated_titles(doc: ParsedDocument) -> None:
    """여러 쪽에 이어지는 같은 제목, 장 첫 쪽에서 장 이름만 다시 쓴 제목을 뺀다."""
    out: list[Element] = []
    last: dict[int, str] = {}
    chapter_title = ''
    for e in doc.elements:
        if e.kind != 'heading':
            out.append(e)
            continue
        if e.level == 1:
            m = re.match(r'^(?:\d+\.|부록 ·)\s*(.+)$', e.text)
            chapter_title = m.group(1) if m else e.text
        elif e.level is not None and e.level >= 2 and e.text == chapter_title:
            _drop(doc, 'repeat_title', e)
            continue
        if last.get(e.level) == e.text:
            _drop(doc, 'repeat_title', e)
            continue
        last[e.level] = e.text
        for lv in [k for k in last if e.level is not None and k > e.level]:
            del last[lv]
        out.append(e)
    doc.elements = out


def collapse_props(doc: ParsedDocument) -> None:
    """항목 제목(level 2) 바로 뒤의 머리 정보를 제목의 meta['props'] 로 옮긴다.
    모양은 형식마다 다르다: 1줄 표(docx·pdf), 이름·값이 번갈아 나오는 짧은 문단들(pptx)."""
    out: list[Element] = []
    els = doc.elements
    i = 0
    while i < len(els):
        e = els[i]
        out.append(e)
        i += 1
        if not (e.kind == 'heading' and e.level == 2):
            continue
        props = []
        while i < len(els):
            f = els[i]
            if f.kind == 'table' and f.rows and len(f.rows) == 1 and (kv := _kv_props(f.rows[0])):
                props += kv
                i += 1
            elif f.kind == 'paragraph' and f.text in PROPS_KEYS and i + 1 < len(els) and els[i + 1].kind == 'paragraph':
                props.append([f.text, els[i + 1].text])
                i += 2
            else:
                break
        if props:
            e.meta['props'] = props
    doc.elements = out


def _kv_props(cells: list[str]):
    cells = [c.strip() for c in cells]
    if len(cells) >= 2 and len(cells) % 2 == 0 and all(cells[k] in PROPS_KEYS for k in range(0, len(cells), 2)):
        return [[cells[k], cells[k + 1]] for k in range(0, len(cells), 2)]
    return None


def qa_tables(doc: ParsedDocument) -> None:
    """'질문 | 답변' 표를 'Q. …' · 'A. …' 문단으로 바꾼다 (.md 와 같은 모양)."""
    out = []
    for e in doc.elements:
        if e.kind == 'table' and e.rows and [c.strip() for c in e.rows[0]] == ['질문', '답변']:
            for r in e.rows[1:]:
                if len(r) >= 2:
                    q = r[0][2:].strip() if r[0].startswith('Q.') else r[0]
                    out.append(Element('paragraph', f'Q. {q}', page=e.page))
                    out.append(Element('paragraph', f'A. {r[1]}', page=e.page))
            continue
        out.append(e)
    doc.elements = out


def extract_meta(doc: ParsedDocument, safe: bool = False) -> None:
    """첫 장 앞의 문서 정보 표를 doc.info(원래 이름)·doc.meta(정규화 키)로 옮기고 본문에서 뺀다.

    표지 문구(시리즈명·문서 번호 줄·열람 안내)는 doc.properties['cover'] 로 옮기되, 정리본 같은 템플릿 문서일 때만이다:
    - 첫 장 앞에 문서 정보 표가 있으면 그 앞의 문단 (docx·pptx·pdf 정리본)
    - 파서가 표지 줄로 표시한 문단(meta['cover_line'], md 정리본의 제목 바로 뒤 인용 줄)
    그 밖의 문서에서 첫 장 앞의 문단은 서문이므로 본문에 남긴다. 보수 모드에서는 늘 본문에 남긴다."""
    els = doc.elements
    first_chapter = next((i for i, e in enumerate(els) if e.kind == 'heading' and e.level == 1), None)
    front_end = first_chapter if first_chapter is not None else min(len(els), 30)   # 장 제목이 없으면 앞부분
    templated = not safe and first_chapter is not None and any(
        e.kind == 'table' and _is_info_table(e.rows or []) for e in els[:front_end])
    info: dict[str, str] = {}
    cover: list[str] = []
    out = []
    for i, e in enumerate(els):
        front = i < front_end
        if front and e.kind == 'table' and _is_info_table(e.rows or []):
            _read_info(e.rows, info)
            continue
        if front and e.kind in ('paragraph', 'list_item') and (templated or (not safe and e.meta.get('cover_line'))):
            cover.append(e.text)
            continue
        out.append(e)
    doc.elements = out
    doc.info = info
    if cover:
        doc.properties['cover'] = cover
    doc.meta = _normalize_meta(doc.meta, info, doc.title)


def _is_info_table(rows: list[list[str]]) -> bool:
    """문서 정보 표: '항목 | 값' 쌍의 항목 이름이 문서 정보 이름인 것이 하나라도 있으면 (키워드 표처럼 한 줄짜리 포함)."""
    return any(r[k].strip() in INFO_MAP and r[k + 1].strip() for r in rows for k in range(0, len(r) - 1, 2))


def _read_info(rows: list[list[str]], info: dict) -> bool:
    used = False
    for r in rows:
        cells = [c.strip() for c in r]
        for k in range(0, len(cells) - 1, 2):
            if cells[k] in INFO_MAP and cells[k + 1]:
                info.setdefault(cells[k], cells[k + 1])
                used = True
    return used


def _normalize_meta(meta: dict, info: dict, title: str) -> dict:
    meta = dict(meta)
    for name, value in info.items():
        key = INFO_MAP[name]
        if meta.get(key):
            continue          # .md 머리말 값이 우선
        if key in LIST_META:
            meta[key] = [] if value in ('-', '없음') else [x.strip() for x in value.split(',') if x.strip()]
        elif key == 'pair':
            meta[key] = '' if value in ('-', '없음') else value
        elif key == 'category':
            code, _, name_ = value.partition(' ')
            meta['category'] = code
            if name_:
                meta.setdefault('category_name', name_)
        elif key == 'access_level':
            m = re.match(r'^(.+?)\s*\((.+)\)$', value)
            meta['access_level'] = m.group(1) if m else value
            if m:
                meta.setdefault('audience', m.group(2))
        else:
            meta[key] = value
    if not meta.get('title') and title:
        meta['title'] = title
    no = meta.get('doc_no', '')
    if no and 'doc_type' not in meta:
        meta['doc_type'] = ('manual' if no.endswith('-M') else 'standard' if '-STD-' in no
                            else 'policy' if '-AI-' in no else 'guide')
    return meta


def assign_sections(doc: ParsedDocument) -> None:
    stack: list[tuple[int, str]] = []
    for i, e in enumerate(doc.elements):
        e.order = i
        if e.kind == 'heading' and e.level is not None:
            if e.level == 0:
                stack = []
                e.section = []
                continue
            while stack and stack[-1][0] >= e.level:
                stack.pop()
            e.section = [t for _, t in stack]
            stack.append((e.level, e.text))
        else:
            e.section = [t for _, t in stack]


def collect_dropped(doc: ParsedDocument) -> None:
    """형식 파서가 'dropped' 로 표시한 글자(장 번호·쪽 번호·꼬리말·목차)를 본문에서 꺼내 doc.dropped 로 옮긴다."""
    out = []
    for e in doc.elements:
        if e.kind == 'dropped':
            doc.dropped.append([e.meta.get('why', ''), e.text, e.page])
        else:
            out.append(e)
    doc.elements = out


def finalize(doc: ParsedDocument, safe: bool = False) -> ParsedDocument:
    collect_dropped(doc)
    normalize_headings(doc)
    collapse_props(doc)
    qa_tables(doc)
    if not doc.title:
        doc.title = next((e.text for e in doc.elements if e.kind == 'heading' and e.level == 0), '') \
            or doc.meta.get('title', '') or doc.properties.get('title', '')
    extract_meta(doc, safe)
    assign_sections(doc)
    if not doc.headings():
        doc.warnings.append('제목을 하나도 찾지 못함 — 청크를 제목 단위로 나눌 수 없음')
    return doc
