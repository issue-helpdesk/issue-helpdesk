"""청크 나누기 (WBS M2-1-2)와 청크 메타데이터 (M2-1-3).

파서 결과(ParsedDocument)를 검색 단위(Chunk)로 나눈다.

    from app.rag.parser import parse
    from app.rag.chunker import chunk_document, chunk_row, document_row, version_row

    doc = parse(path)
    chunks = chunk_document(doc)
    document_row(doc)                     # knowledge_documents 한 행
    version_row(doc, path, registration)  # document_versions 한 행 (registration = manifest.json 한 행)
    [chunk_row(c) for c in chunks]        # document_chunks 행들. 임베딩 입력은 c.text (document_chunk_embeddings.source_text)

표 이름·칸은 docs/06.테이블_설계서.md(A)를 따른다. 칸 설명은 청크_메타데이터.md.

규칙
- 3.x 항목 하나 = 청크 하나. 이런 경우·원인·조치 방법·해결 확인이 한 청크에 있어야 답이 끊기지 않는다.
- 항목이 없는 장(개요·사전 확인·주의사항·문의처·부록)은 장 하나 = 청크 하나.
- 자주 묻는 질문은 질문·답변 한 쌍 = 청크 하나.
- MAX_CHARS 를 넘으면 소제목 단위로 묶어 TARGET_CHARS 안팎으로 나눈다.
  소제목 하나도 길면 요소 단위로, 표는 행 단위로 나누고 머리 행을 반복한다.
- 청크 맨 앞에 '문서 제목 > 장 > 항목'과 항목 머리(문의 유형·처리 구분·담당 부서)를 붙인다.
- 개정 이력·문서 정보·목차·표지는 청크로 만들지 않는다 (document_row·version_row 로 간다).
- 나뉜 조각은 같은 unit_key 를 갖는다 (검색이 항목 조각을 다시 붙인다).
- 여러 문서에 똑같이 들어 있는 장(문의처 등)도 문서마다 적재한다. 검색이 content_hash 로 묶는다
  (duplicate_groups() 는 확인용).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field

from ..parser import PARSER_VERSION
from ..parser.common import CIRCLED, NUM_RE
from ..parser.models import Element, ParsedDocument

CHUNKER_VERSION = '1.0'  # 청크 경계·글이 바뀌는 수정을 하면 올린다 (chunk_key 는 같은 버전 안에서만 안정적)
TRANSFER_POLICIES = ('ALLOWED', 'MASKED', 'BLOCKED')    # document_versions.transfer_policy
VIEW_SCOPES = {'사내 일반': 'ALL', '사내 제한': 'AGENT'}   # 문서 열람 등급 → document_versions.view_scope
DOC_TYPES = {'guide': 'GUIDE', 'manual': 'MANUAL', 'standard': 'STANDARD', 'policy': 'POLICY'}   # → knowledge_documents.doc_type
FILE_FORMATS = {'md': 'MD', 'docx': 'DOCX', 'pptx': 'PPTX', 'pdf': 'PDF', 'txt': 'TEXT'}
ITEM_UNIT_MAX = 4500     # 3.x 항목 하나(조각 합)의 상한. 넘으면 적재 검증에서 걸린다
TARGET_CHARS = 1000      # 나눌 때 조각 하나의 목표 길이 (본문 글자 수)
MAX_CHARS = 1500         # 이보다 길면 나눈다
MIN_CHARS = 200          # 마지막 조각이 이보다 짧으면 앞 조각에 붙인다
SKIP_CHAPTERS = ('개정 이력',)
FAQ_CHAPTER = '자주 묻는 질문'

# \b 는 한글도 단어 글자로 봐서 'FAQ-012를'을 못 찾는다. 영문·숫자만 경계로 본다
SCENARIO_RE = re.compile(r'(?<![A-Za-z0-9])[A-Z]{2,3}-\d{2}(?!\d)')
FAQ_RE = re.compile(r'(?<![A-Za-z0-9])FAQ-\d{3}(?!\d)')
TEAM_RE = re.compile(r'[가-힣A-Za-z]+팀(?![가-힣])|서비스데스크')   # 'OO팀'(팀장은 아님)과 서비스데스크
SECTION_NO_RE = re.compile(r'^(\d{1,2}(?:\.\d{1,2})?)\.?\s')
SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')
SKIP_PREFIX_RE = re.compile(r'^(?:\d{1,2}\.\s*|부록\s*·\s*)')   # '6. 개정 이력'·'부록 · 개정 이력'


@dataclass
class Chunk:
    """검색 단위 하나. 표 칸과의 대응은 청크_메타데이터.md, 표에 넣을 행은 chunk_row()."""
    chunk_key: str                 # IT-SW-002@v2.0#004
    doc_no: str
    version: str
    seq: int                      # 문서 안 순번 (1부터)
    chunk_type: str               # item (3.x 항목) · chapter (장) · faq (질문·답변) · preface (첫 장 앞 서문)
    section_no: str               # '3.1' · '1' · '부록' · ''
    heading_path: list[str]       # ['3. 항목별 안내', '3.1 유료 프로그램 라이선스 신청']
    text: str                     # 머리말 + 본문 = 임베딩 입력 = 답변 근거
    body: str = ''                # 본문만
    unit_key: str = ''             # IT-SW-002@v2.0/item:3.1. 나뉜 조각끼리 같다
    part: int = 1                 # 긴 항목을 나눴을 때 몇 번째 조각인지
    parts: int = 1
    subheadings: list[str] = field(default_factory=list)   # 들어 있는 소제목 (이런 경우·조치 방법 …)
    props: dict = field(default_factory=dict)              # 항목 머리 {'문의 유형': 'SW-02', …}
    inquiry_type_codes: list[str] = field(default_factory=list)
    faq_ids: list[str] = field(default_factory=list)
    handling: str = ''            # 처리 구분 (사용자 직접 조치 · 신청·승인 후 처리 · 담당자 처리 …)
    team: str = ''                # 처리 팀 하나: 가이드 '담당 부서', 매뉴얼 '1차 처리' (팀 이름만, 조건 메모는 props)
    escalation_teams: list[str] = field(default_factory=list)   # 매뉴얼 '이관 대상'의 팀 이름들 ('없음'·'—' 이면 [])
    urgency: str = ''             # 매뉴얼 '기본 긴급도' (P1~P4)
    page_start: int | None = None  # 쪽 범위 (pdf·pptx). docx·md 는 None
    page_end: int | None = None
    images: list[str] = field(default_factory=list)         # 그림 파일 이름 (원본 문서 옆 images/ 기준)
    category: str = ''            # 문서 값 (표에는 넣지 않는다. 검색은 document_versions·knowledge_documents 와 조인)
    doc_type: str = ''
    access_level: str = ''
    char_count: int = 0           # text 글자 수
    content_hash: str = ''        # sha1(body). 문서 사이 같은 본문 묶기

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Atom:
    """청크에 들어가는 가장 작은 조각 (요소 하나, 또는 긴 표의 몇 행)."""
    text: str
    page: int | None
    sub: str = ''                 # 속한 소제목
    image: str = ''


def document_row(doc: ParsedDocument) -> dict:
    """knowledge_documents 한 행. owner·pair 는 이름·문서 번호로 주고, 적재 스크립트가 id 로 바꾼다."""
    m = doc.meta
    category = m.get('category', '')
    return {
        'doc_code': _doc_no(doc),
        'doc_type': DOC_TYPES.get(m.get('doc_type', ''), 'GUIDE'),
        'title': m.get('title') or doc.title,
        'category_code': category if category not in ('', 'STD', 'AI') else None,   # 공통 기준은 분류 없음
        'owner_group': m.get('owner', '') or None,          # → owner_group_id (support_groups.name)
        'pair_doc_code': m.get('pair', '') or None,         # → pair_document_id (추가 요청 칸)
    }


def version_row(doc: ParsedDocument, source_path: str = '', registration: dict | None = None) -> dict:
    """document_versions 한 행. is_current·ingest_status 는 적재 스크립트·활성화 함수가 정한다.

    registration: 등록 입력 (manifest.json 한 행 또는 POST /guides 본문). 외부 전송 정책은 문서 내용이
    아니라 등록 때 정하는 값이라 여기서만 받는다 (열람 등급에서 추론하지 않는다, IT-STD-002).
    """
    m = doc.meta
    reg = registration or {}
    return {
        'version': m.get('version', ''),
        'file_path': (source_path or doc.path).replace('\\', '/'),
        'file_format': FILE_FORMATS.get(doc.format, 'TEXT'),
        'view_scope': view_scope(m.get('access_level', '')),
        'transfer_policy': transfer_policy(reg.get('transfer_policy')),
        # 아래는 추가 요청 칸 (청크_메타데이터.md 6장)
        'effective_date': m.get('effective_date', '') or None,
        'keywords': _as_list(m.get('keywords')),
        'parser_version': PARSER_VERSION,
        'chunker_version': CHUNKER_VERSION,
        'ingest_meta': {'parse_mode': doc.quality.get('mode', ''), 'parse_coverage': doc.quality.get('coverage'),
                        'warnings': list(doc.warnings)},
    }


def chunk_row(c: Chunk) -> dict:
    """document_chunks 한 행. 임베딩 입력은 c.text (document_chunk_embeddings.source_text).

    전용 칸은 SQL 조회·정렬·제약에 쓰는 것만 둔다 (seq·unit_key·chunk_type·part). 나머지는 meta 에 넣는다.
    chunk_key(문서@버전#순번)·parts(같은 unit_key 행 수)·content_hash(sha1(content))는 저장하지 않고 계산한다.
    """
    pages = '' if not c.page_start else f'p.{c.page_start}' if c.page_start == c.page_end else f'p.{c.page_start}-{c.page_end}'
    faq = ''
    if c.chunk_type == 'faq':                           # FAQ 번호, 없으면 질문 앞부분으로 구분한다
        faq = c.unit_key.rsplit(':', 1)[-1] if ':FAQ-' in c.unit_key else _short(_question(c.body), 20)
    return {
        'heading_path': ' > '.join(c.heading_path),
        'location': ' · '.join(x for x in (c.section_no, faq, pages) if x),   # 출처 표시: 문서 번호 + 이 값
        'content': c.body,
        # 아래는 추가 요청 칸 (청크_메타데이터.md 6장)
        'seq': c.seq, 'unit_key': c.unit_key,
        'chunk_type': c.chunk_type.upper(),                                   # ITEM·CHAPTER·FAQ·PREFACE
        'part': c.part,
        'meta': {'section_no': c.section_no, 'inquiry_type_codes': c.inquiry_type_codes,
                 'page_start': c.page_start, 'page_end': c.page_end,
                 'props': c.props, 'subheadings': c.subheadings, 'faq_ids': c.faq_ids, 'images': c.images,
                 'handling': c.handling, 'team': c.team, 'escalation_teams': c.escalation_teams, 'urgency': c.urgency},
    }


def view_scope(access_level: str) -> str:
    """문서 열람 등급 → view_scope. 모르는 등급은 가장 좁은 ADMIN (A의 기본값과 같다)."""
    return VIEW_SCOPES.get(access_level, 'ADMIN')


def transfer_policy(value) -> str:
    """등록 입력의 외부 전송 정책. 없거나 모르는 값은 BLOCKED (설계서 7장 '불명확하면 전송하지 않는다')."""
    return value if value in TRANSFER_POLICIES else 'BLOCKED'


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    """문서 하나를 청크 목록으로 나눈다."""
    units: list[list[Chunk]] = []
    for kind, chapter, item, pieces in _units(doc):
        if SKIP_PREFIX_RE.sub('', chapter).startswith(SKIP_CHAPTERS):   # '6. 개정 이력'·'부록 · 개정 이력'과 그 아래 절까지
            continue
        if not any(e.kind != 'heading' for e in pieces):
            continue
        props = [tuple(p) for p in (item.meta.get('props') or [])] if item else []
        path = [t for t in (chapter, item.text if item else '') if t]
        if FAQ_CHAPTER in chapter and kind in ('chapter', 'item'):  # '5.1 계정' 같은 FAQ 하위 절도 질문 단위로
            for qa in _split_faq(pieces):                    # 긴 답변은 항목과 같은 길이 규칙으로 나눈다
                parts = _pack(_atoms(qa))
                units.append([_make(doc, 'faq', path, props, atoms, i, len(parts)) for i, atoms in enumerate(parts, 1)])
            continue
        parts = _pack(_atoms(pieces))
        units.append([_make(doc, kind, path, props, atoms, i, len(parts)) for i, atoms in enumerate(parts, 1)])
    _assign_unit_keys(units)
    out = [c for u in units for c in u]
    for i, c in enumerate(out, 1):
        c.seq = i
        c.chunk_key = f'{c.doc_no}@{c.version}#{i:03d}'
    return out


def _assign_unit_keys(units: list[list[Chunk]]) -> None:
    """unit_key = 문서@버전/종류:키. 항목·장은 절 번호, FAQ는 질문 줄의 FAQ 번호, 번호가 없으면 질문 글의 지문
    (q-1a2b3c4d. 순번이 아니라서 앞에 질문이 늘어도 바뀌지 않는다), 서문은 1.
    절 번호가 없거나 겹치면 문서 안 단위 순번(u07)으로 대신한다 (이때는 순서가 바뀌면 키도 바뀐다)."""
    used: set[str] = set()
    for n, unit in enumerate(units, 1):
        c = unit[0]
        if c.chunk_type == 'faq':
            q = _question(c.body)
            m = FAQ_RE.search(q)                                # 질문 줄의 번호만 (답변 속 참조 번호는 아님)
            key = m.group(0) if m else (f'q-{_sha1(q)[:8]}' if q else '')
        elif c.chunk_type == 'preface':
            key = '1'
        else:
            key = c.section_no
        uid = f'{c.doc_no}@{c.version}/{c.chunk_type}:{key}'
        if not key or uid in used:
            uid = f'{c.doc_no}@{c.version}/{c.chunk_type}:u{n:02d}'
        used.add(uid)
        for x in unit:
            x.unit_key = uid


def unit_ref(unit_key: str) -> str:
    """버전을 뺀 단위 참조 (평가 정답·피드백처럼 오래 가는 참조용). IT-SW-003@v2.0/item:3.1 → IT-SW-003/item:3.1"""
    head, _, tail = unit_key.partition('/')
    return f'{head.split("@", 1)[0]}/{tail}'


def duplicate_groups(chunks: list[Chunk]) -> list[list[Chunk]]:
    """여러 문서에 똑같이 들어 있는 청크(문의처·연락처 등) 묶음. 확인·보고용이고 지우지 않는다.

    본문(content_hash)과 열람 등급이 같으면 한 묶음이다. 검색 결과에서는 외부 전송 정책까지 같아야
    묶는다 (검색 API 몫, README '검색 결과 계약').
    """
    groups: dict[tuple[str, str], list[Chunk]] = {}
    for c in chunks:
        groups.setdefault((c.content_hash, c.access_level), []).append(c)
    return [g for g in groups.values() if len({c.doc_no for c in g}) > 1]


def validate(chunks: list[Chunk]) -> list[str]:
    """적재 전 청크 검증 (적재 스크립트가 부른다). 문제 목록, 없으면 []."""
    problems = []
    if not chunks:
        return ['청크가 없음']
    if len({c.chunk_key for c in chunks}) != len(chunks):
        problems.append('chunk_key 중복')
    units: dict[str, list[Chunk]] = {}
    for c in chunks:
        units.setdefault(c.unit_key, []).append(c)
    for uid, parts in units.items():
        if [c.part for c in parts] != list(range(1, parts[0].parts + 1)):
            problems.append(f'{uid}: 조각 번호가 1..{parts[0].parts} 가 아님')
        if parts[0].chunk_type == 'item' and sum(len(c.body) for c in parts) > ITEM_UNIT_MAX:
            problems.append(f'{uid}: 항목이 {ITEM_UNIT_MAX}자를 넘음 (문서를 고친다)')
    return problems


# ── 단위 나누기 ────────────────────────────────────────────────

def _units(doc: ParsedDocument):
    """(종류, 장 제목, 항목 제목 요소, 요소들) 를 읽는 순서대로. 소제목(level 3)은 요소 안에 남긴다."""
    units: list[list] = []
    chapter = ''
    for e in doc.elements:
        if e.kind == 'heading' and e.level == 0:
            continue
        if e.kind == 'heading' and e.level == 1:
            chapter = e.text
            units.append(['chapter', chapter, None, []])
        elif e.kind == 'heading' and e.level == 2:
            units.append(['item', chapter, e, []])
        else:
            if not units:
                units.append(['preface', '', None, []])
            units[-1][3].append(e)
    return units


def _split_faq(pieces: list[Element]) -> list[list[Element]]:
    """질문(Q.)마다 나눈다. 질문 사이의 소제목(분류)은 앞 답변이 아니라 다음 질문에 붙인다."""
    groups: list[list[Element]] = []
    for e in pieces:
        only_heads = bool(groups) and all(x.kind == 'heading' for x in groups[-1])
        starts = e.kind == 'heading' or (e.kind == 'paragraph' and e.text.startswith('Q.'))
        if not groups or (starts and not only_heads):
            groups.append([])
        groups[-1].append(e)
    return [g for g in groups if any(x.kind != 'heading' for x in g)]


def _atoms(pieces: list[Element]) -> list[_Atom]:
    out: list[_Atom] = []
    sub = ''
    for e in pieces:
        if e.kind == 'heading':
            sub = e.text
            out.append(_Atom(f'### {e.text}', e.page, sub))
        elif e.kind == 'table':
            cells = [r for r in e.rows or [] if any(c.strip() for c in r)]
            if not cells:
                continue
            width = max(len(r) for r in cells)
            rows = [_row(r, width) for r in cells]
            for part in _table_parts(rows, width):
                out.append(_Atom(part, e.page, sub))
        elif e.kind == 'image':
            out.append(_Atom(f'[그림] {e.text}'.rstrip(), e.page, sub, e.meta.get('name', '')))
        elif e.kind == 'list_item':
            bare = NUM_RE.match(e.text) or e.text[:1] in CIRCLED
            out.append(_Atom(e.text if bare else f'- {e.text}', e.page, sub))
        elif e.text:
            out.extend(_Atom(t, e.page, sub) for t in _split_long(e.text))
    return out


def _split_long(text: str) -> list[str]:
    """MAX_CHARS 를 넘는 문단(구조 없이 읽힌 문서에서 생긴다)은 문장 단위로 TARGET_CHARS 안팎씩 나눈다."""
    if len(text) <= MAX_CHARS:
        return [text]
    segs: list[tuple[str, str]] = []                    # (조각, 앞 조각과 이을 글자). 줄바꿈은 지킨다
    for line in text.split('\n'):
        for i, s in enumerate(SENTENCE_RE.split(line)):
            if s:
                segs.append((s, '\n' if i == 0 else ' '))
    out, cur = [], ''
    for s, joint in segs:
        if len(s) > MAX_CHARS:                          # 마침표 없이 긴 글은 그냥 자른다
            if cur:                                     # 앞에 모아 둔 문장이 먼저 나가야 순서가 맞다
                out.append(cur)
                cur = ''
            while len(s) > MAX_CHARS:
                out.append(s[:TARGET_CHARS])
                s = s[TARGET_CHARS:]
        if cur and len(cur) + len(s) + 1 > TARGET_CHARS:
            out.append(cur)
            cur = ''
        cur = f'{cur}{joint}{s}' if cur else s
    return out + [cur] if cur else out


def _row(cells: list[str], width: int) -> str:
    """표 한 행. 칸 안의 '|'는 '\\|'로 바꾸고, 짧은 행은 빈 칸으로 채운다."""
    cells = [c.replace('\n', ' ').replace('|', '\\|').strip() for c in cells] + [''] * (width - len(cells))
    return '| ' + ' | '.join(cells) + ' |'


def _table_parts(rows: list[str], width: int) -> list[str]:
    """머리 행 뒤에 구분 행(|---|)을 넣는다. 긴 표는 행 단위로 나누고 나뉜 조각마다 머리 행을 반복한다."""
    head = rows[0] + '\n|' + '---|' * width
    whole = '\n'.join([head] + rows[1:])
    if len(whole) <= MAX_CHARS or len(rows) < 3:
        return [whole]
    parts, cur = [], []
    for r in rows[1:]:
        if cur and len(head) + sum(len(x) + 1 for x in cur) + len(r) > TARGET_CHARS:
            parts.append('\n'.join([head] + cur))
            cur = []
        cur.append(r)
    parts.append('\n'.join([head] + cur))
    return parts


def _size(atoms: list[_Atom]) -> int:
    return sum(len(a.text) + 1 for a in atoms)


def _pack(atoms: list[_Atom]) -> list[list[_Atom]]:
    """MAX_CHARS 안이면 그대로, 넘으면 소제목 묶음 단위로 TARGET_CHARS 안팎씩 나눈다."""
    if _size(atoms) <= MAX_CHARS:
        return [atoms]
    blocks: list[list[_Atom]] = []
    for a in atoms:
        if not blocks or a.text.startswith('### '):
            blocks.append([])
        blocks[-1].append(a)
    parts: list[list[_Atom]] = []
    cur: list[_Atom] = []
    for b in blocks:
        if _size(b) > MAX_CHARS:                        # 소제목 하나가 길면 요소 단위로
            for a in b:
                if cur and _size(cur) + len(a.text) > TARGET_CHARS:
                    carry = [cur.pop()] if cur[-1].text.startswith('### ') else []   # 소제목 줄은 내용과 같이 간다
                    if cur:
                        parts.append(cur)
                    cur = carry
                cur.append(a)
        elif cur and _size(cur) + _size(b) > TARGET_CHARS:
            parts.append(cur)
            cur = list(b)
        else:
            cur.extend(b)
    if cur:
        parts.append(cur)
    if len(parts) > 1 and _size(parts[-1]) < MIN_CHARS and _size(parts[-2]) + _size(parts[-1]) <= MAX_CHARS:
        parts[-2].extend(parts.pop())
    return parts


# ── 청크 만들기 ────────────────────────────────────────────────

def _make(doc, kind, path, props, atoms, part, parts) -> Chunk:
    m = doc.meta
    lines = [a.text for a in atoms]
    if atoms and atoms[0].sub and not atoms[0].text.startswith('### '):
        lines.insert(0, f'### {atoms[0].sub} (계속)')     # 소제목 중간에서 나뉜 조각
    body = '\n'.join(lines)
    head = ' > '.join([m.get('title') or doc.title] + path) + (f' ({part}/{parts})' if parts > 1 else '')
    head_lines = [head] + ([' · '.join(f'{k}: {v}' for k, v in props)] if props else [])
    text = '\n'.join(head_lines) + '\n\n' + body
    pd = dict(props)
    pages = sorted({a.page for a in atoms if a.page})
    faq_src = pd.get('관련 FAQ', '') + (body if kind == 'faq' else '')
    return Chunk(
        chunk_key='', doc_no=_doc_no(doc), version=m.get('version', ''), seq=0,
        chunk_type=kind, section_no=_section_no(path), heading_path=path, text=text, body=body,
        part=part, parts=parts,
        subheadings=list(dict.fromkeys(a.sub for a in atoms if a.sub)),
        props=pd,
        inquiry_type_codes=list(dict.fromkeys(SCENARIO_RE.findall(pd.get('문의 유형', '')))),
        faq_ids=list(dict.fromkeys(FAQ_RE.findall(faq_src))),
        handling=pd.get('처리 구분', ''),
        team=next(iter(_teams(pd.get('담당 부서') or pd.get('1차 처리', ''))), ''),
        escalation_teams=_teams(pd.get('이관 대상', '')),
        urgency=pd.get('기본 긴급도', ''),
        page_start=pages[0] if pages else None, page_end=pages[-1] if pages else None,
        images=[a.image for a in atoms if a.image],
        category=m.get('category', ''), doc_type=m.get('doc_type', ''), access_level=m.get('access_level', ''),
        char_count=len(text), content_hash=_sha1(body),
    )


def _teams(value: str) -> list[str]:
    """'정보보안팀 (도용 의심 시)'·'시스템인프라팀 / 네트워크팀'·'ITssue 챗봇·서비스데스크' → 팀 이름만. '없음'·'—' → []."""
    return list(dict.fromkeys(TEAM_RE.findall(value or '')))


def _question(body: str) -> str:
    """FAQ 청크 본문의 질문 줄 ('Q. …'). 앞에 분류 소제목이 올 수 있다."""
    return next((ln for ln in body.split('\n') if ln.startswith('Q.')), '')


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + '…'


def _as_list(value) -> list[str]:
    """문서 머리말의 목록 값. 'VPN, 접속'처럼 글자 하나로 오면 쉼표로 나눈다 (글자 단위로 쪼개지 않게)."""
    if not value:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(',') if x.strip()]
    return [str(x) for x in value]


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def _section_no(path: list[str]) -> str:
    if not path:
        return ''
    last = path[-1]
    if last.startswith('부록'):
        return '부록'
    mt = SECTION_NO_RE.match(last)
    return mt.group(1) if mt else ''


def _doc_no(doc: ParsedDocument) -> str:
    return doc.meta.get('doc_no') or os.path.splitext(os.path.basename(doc.path))[0].split('_')[0]


# ── 결과 확인 ─────────────────────────────────────────────────

def preview(chunks: list[Chunk]) -> str:
    """사람이 청크 결과를 확인하기 위한 미리보기 md."""
    out = []
    for c in chunks:
        tags = [c.chunk_type, f'{c.char_count}자'] + [x for x in (', '.join(c.inquiry_type_codes), ', '.join(c.faq_ids)) if x]
        if c.page_start:
            tags.append(f'p.{c.page_start}-{c.page_end}')
        out.append(f'## {c.chunk_key}  <sub>{c.unit_key} · {" · ".join(tags)}</sub>\n\n```text\n{c.text}\n```\n')
    return '\n'.join(out)


def baseline(chunks: list[Chunk]) -> dict[str, dict]:
    """문서별 청크 수·항목 수·단위 수. 정리본 기준표(chunker/baseline.json)와 비교해 파싱 누락을 잡는다."""
    out: dict[str, dict] = {}
    for c in chunks:
        b = out.setdefault(c.doc_no, {'chunks': 0, 'items': 0, 'units': set()})
        b['chunks'] += 1
        b['items'] += c.chunk_type == 'item' and c.part == 1
        b['units'].add(c.unit_key)
    return {k: {'chunks': v['chunks'], 'items': v['items'], 'units': len(v['units'])} for k, v in sorted(out.items())}


def main(argv=None) -> int:
    """python -m app.rag.chunker <파일 또는 폴더> [...] [--out 결과폴더] [--baseline 기준표.json]"""
    import argparse
    import logging

    from ..parser import ParseError, parse
    from ..parser.__main__ import iter_files

    ap = argparse.ArgumentParser(prog='python -m app.rag.chunker')
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--out', help='<이름>.chunks.md 미리보기를 저장할 폴더')
    ap.add_argument('--baseline', help='문서별 청크 수 기준표(json)를 이 경로에 쓴다 (문서마다 형식 하나만 넣을 것)')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    total, failed = [], 0
    for path in iter_files(a.paths):
        name = os.path.basename(path)
        try:
            chunks = chunk_document(parse(path))
        except ParseError as ex:
            print(f'[ERROR] {name}: {ex}')
            failed += 1
            continue
        except Exception as ex:                         # 한 문서 때문에 전체가 멈추지 않게
            print(f'[ERROR] {name}: {type(ex).__name__}: {ex}')
            failed += 1
            continue
        total += chunks
        sizes = sorted(c.char_count for c in chunks) or [0]
        problems = validate(chunks)
        print(f'[{"WARN" if problems else "ok"}] {name}: 청크 {len(chunks)} (항목 {sum(c.chunk_type == "item" for c in chunks)}) '
              f'길이 {sizes[0]}~{sizes[-1]}자 중앙 {sizes[len(sizes) // 2]}자' + ''.join(f'\n    {p}' for p in problems))
        if a.out:
            with open(os.path.join(a.out, os.path.splitext(name)[0] + '.chunks.md'), 'w', encoding='utf-8') as f:
                f.write(preview(chunks))
    groups = duplicate_groups(total)
    print(f'합계 청크 {len(total)}, 단위 {len({c.unit_key for c in total})}. '
          f'문서 사이 같은 본문 {len(groups)}묶음 {sum(len(g) for g in groups)}개 (지우지 않음, 검색에서 묶음)')
    if a.baseline:
        import json
        with open(a.baseline, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'chunker_version': CHUNKER_VERSION, 'docs': baseline(total)}, f, ensure_ascii=False, indent=1)
            f.write('\n')
    return 1 if failed else 0

