"""가이드 검증 D1~D6 도구 (WBS 2단계, 적재 M2-2-1 전에 사람이 확인하는 일).

검증 시트: 문서마다 파서·청커 결과와 manifest 를 대조하고, 검색 단위 목록을 사람이 원문과 비교할 수 있게 만든다.
검색 질문: 검증자가 문서마다 3개 이상 쓰는 질문과 정답 단위(unit_ref). 평가 도구(M2-2-2)의 추가 시험지가 된다.
평가셋(eval_inquiries.csv) 문장은 검색 자료와 질문에 쓰지 않는다 (dataset/README.md) — 겹침을 여기서 잡는다.

    cd backend
    python -m app.rag.review sheet IT-ACC-001 IT-ACS-001 --name D1        # 검증 시트 + 질문 양식
    python -m app.rag.review check ../dataset/guide_review/D1_질문.csv     # 질문 점검
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass

from ..chunker import (SKIP_CHAPTERS, SKIP_PREFIX_RE, Chunk, _units, baseline, chunk_document, unit_ref, validate,
                       view_scope)
from ..parser import ParsedDocument, parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
GUIDES = os.path.join(REPO, 'dataset', 'guides')
EVAL_CSV = os.path.join(REPO, 'dataset', 'data', 'eval_inquiries.csv')
TAXONOMY = os.path.join(REPO, 'dataset', 'data', 'taxonomy.json')
BASELINE = os.path.join(HERE, '..', 'chunker', 'baseline.json')
OUT = os.path.join(REPO, 'dataset', 'guide_review')

QUESTION_COLUMNS = ['문서 번호', '번호', '질문', '정답 단위', '작성자', '메모']
QUESTIONS_PER_DOC = 3
CROSS_DOC_MEMO = '다른 문서 정답:'      # 메모에 이 표시가 있으면 다른 문서의 정답 단위를 의도한 것으로 본다
ACCESS_BY_TYPE = {'guide': '사내 일반', 'standard': '사내 일반', 'manual': '사내 제한', 'policy': '사내 제한'}

_NORM_RE = re.compile(r'[\s.,?!~·\'"()\[\]]')
_TOKEN_RE = re.compile(r'[0-9A-Za-z가-힣]{2,}')


def known_scenarios(path: str = TAXONOMY) -> set[str]:
    """분류체계의 문의 유형 코드 50개 (DB inquiry_types 와 같은 원본)."""
    with open(path, encoding='utf-8') as f:
        return {s['id'] for s in json.load(f)['scenarios']}


def load_manifest(root: str = GUIDES) -> dict[str, dict]:
    with open(os.path.join(root, 'manifest.json'), encoding='utf-8') as f:
        return {d['doc_no']: d for d in json.load(f)}


def source_path(entry: dict, root: str = GUIDES) -> str:
    """검증·적재에 쓰는 형식 하나 (정리본 README 권장: md)."""
    return os.path.join(root, entry['files']['md'])


# ── 평가셋 겹침 ────────────────────────────────────────────────

@dataclass
class Overlap:
    eval_id: str
    query: str
    kind: str          # exact (원문 그대로 들어 있음) · similar (단어가 많이 겹침)


class EvalSet:
    """평가셋 문의 50건. 검색 질문·문서 문장이 평가셋을 베꼈는지 본다."""

    def __init__(self, path: str = EVAL_CSV):
        with open(path, encoding='utf-8-sig') as f:
            self.rows = [(r['eval_id'], r['query'].strip()) for r in csv.DictReader(f)]

    def overlaps(self, text: str) -> list[Overlap]:
        norm, out = _norm(text), []
        for eid, q in self.rows:
            nq = _norm(q)
            if len(nq) >= 6 and nq in norm:
                out.append(Overlap(eid, q, 'exact'))
                continue
            toks = _TOKEN_RE.findall(q)
            hit = [t for t in toks if t in text]
            if len(toks) >= 3 and len(hit) >= max(3, int(len(toks) * 0.6)):
                out.append(Overlap(eid, q, 'similar'))
        return out


def _norm(s: str) -> str:
    return _NORM_RE.sub('', s).lower()


# ── 검증 시트 ──────────────────────────────────────────────────

@dataclass
class Review:
    doc_no: str
    entry: dict
    doc: ParsedDocument
    chunks: list[Chunk]


def load(doc_no: str, manifest: dict[str, dict], root: str = GUIDES) -> Review:
    entry = manifest[doc_no]
    doc = parse(source_path(entry, root))
    return Review(doc_no, entry, doc, chunk_document(doc))


def doc_checks(r: Review, base: dict | None = None) -> list[tuple[str, str, str, str]]:
    """(항목, 문서에서 읽은 값, manifest·규칙 값, 결과) 목록. 결과는 일치 · ⚠ 다름 · 정보."""
    m, e = r.doc.meta, r.entry
    rows = []

    def same(name, got, want):
        rows.append((name, _show(got), _show(want), '일치' if got == want else '⚠ 다름'))

    for key, name in (('title', '제목'), ('category', '분류'), ('doc_type', '문서 유형'), ('version', '버전'),
                      ('owner', '관리 부서'), ('pair', '짝 문서'), ('access_level', '열람 등급')):
        same(name, m.get(key, ''), e.get(key, ''))
    same('열람 등급 ↔ 문서 유형 규칙', m.get('access_level', ''), ACCESS_BY_TYPE.get(e.get('doc_type', ''), '?'))
    rows.append(('열람 범위 (view_scope)', view_scope(m.get('access_level', '')), '사내 일반=ALL · 사내 제한=AGENT', '정보'))
    found = sorted({x for c in r.chunks for x in c.inquiry_type_codes})
    want = sorted(e.get('scenarios', []))
    diff = []
    if set(want) - set(found):
        diff.append(f'항목에 없음: {", ".join(sorted(set(want) - set(found)))}')
    if set(found) - set(want):
        diff.append(f'manifest 에 없음: {", ".join(sorted(set(found) - set(want)))}')
    unknown = sorted((set(found) | set(want)) - known_scenarios())
    if unknown:
        diff.append(f'분류체계에 없는 코드: {", ".join(unknown)}')
    rows.append(('포함 시나리오 ↔ 항목 문의 유형', _show(found), _show(want), '⚠ ' + ' · '.join(diff) if diff else '일치'))
    q = r.doc.quality
    rows.append(('파싱', f'{q.get("mode")} · 포함률 {q.get("coverage")}', '경고 0',
                 '일치' if not r.doc.warnings else f'⚠ 경고 {len(r.doc.warnings)}'))
    problems = validate(r.chunks)
    rows.append(('청크 검증 validate()', '문제 없음' if not problems else '; '.join(problems), '문제 없음',
                 '일치' if not problems else '⚠ 다름'))
    cov = coverage(r.doc, r.chunks)
    bad = [f'빠짐 {len(cov.missing)}'] * bool(cov.missing) + [f'순서 {len(cov.out_of_order)}'] * bool(cov.out_of_order)
    rows.append(('단위 본문 ↔ 파싱 결과 (빠짐·순서)', f'요소 {cov.expected}개 중 빠짐 {len(cov.missing)} · 순서 어긋남 {len(cov.out_of_order)}',
                 '빠짐 0 · 순서 0', '일치' if not bad else '⚠ ' + ' · '.join(bad) + ': ' + _short_list(cov.missing + cov.out_of_order)))
    if base is not None:
        got = baseline(r.chunks).get(r.doc_no)
        want_b = base.get(r.doc_no)
        rows.append(('청크 수 기준표', _show(got), _show(want_b), '일치' if got == want_b else '⚠ 다름'))
    tp = e.get('transfer_policy')
    rows.append(('외부 전송 (transfer_policy)', '-', tp or '(없음)', '정보: 미정이면 BLOCKED 로 적재 (D 결정 대기)' if not tp else '정보'))
    return rows


@dataclass
class Coverage:
    expected: int                  # 단위 본문에 들어가야 하는 파싱 요소(표는 칸) 수
    missing: list[str]             # 어느 단위에도 없는 것
    out_of_order: list[str]        # 들어 있지만 앞 요소보다 앞에 나온 것


_COVER_NORM_RE = re.compile(r'[\s|\\#*\-]')


def coverage(doc: ParsedDocument, chunks: list[Chunk]) -> Coverage:
    """파싱 결과의 본문 요소가 단위 본문에 빠짐없이, 원문 순서대로 들어갔는지 (청커 검사).

    청커가 일부러 빼는 것은 제외한다: 문서·장·항목 제목(머리말로 감), '개정 이력' 장, 제목만 있는 장.
    표는 칸 하나하나를, 그림은 설명을 찾는다. 비교는 공백·표 구분선·목록 기호를 지우고 한다.
    """
    hay = _COVER_NORM_RE.sub('', ''.join(c.body for c in chunks))
    pieces = []
    for _, chapter, _, elems in _units(doc):
        if SKIP_PREFIX_RE.sub('', chapter).startswith(SKIP_CHAPTERS) or not any(e.kind != 'heading' for e in elems):
            continue
        for e in elems:
            if e.kind == 'table':
                pieces += [c for row in e.rows or [] for c in row]
            else:
                pieces.append(e.text)
    missing, out_of_order, cursor, n = [], [], 0, 0
    for p in pieces:
        key = _COVER_NORM_RE.sub('', p)
        if len(key) < 2:                                  # '-'·'예' 같은 한 글자 칸은 어디에나 있어 의미가 없다
            continue
        n += 1
        pos = hay.find(key, cursor)
        if pos >= 0:
            cursor = pos + len(key)
        elif key in hay:
            out_of_order.append(p)
        else:
            missing.append(p)
    return Coverage(n, missing, out_of_order)


def _short_list(items: list[str], n: int = 3) -> str:
    return ' / '.join(f'"{_short(x, 30)}"' for x in items[:n]) + (' …' if len(items) > n else '')


def sheet(reviews: list[Review], name: str, evalset: EvalSet, base: dict | None = None) -> str:
    """검증 시트 md. 검증자는 ☐ 를 ☑ 로 바꾸거나 '문제' 칸에 적는다."""
    out = [f'# 가이드 검증 시트 {name}', '',
           '> `python -m app.rag.review sheet` 로 만든 파일입니다. 표 위쪽(자동 대조)은 도구가 채우고, '
           '**확인** 칸과 **문제** 칸은 검증자가 채웁니다.', '',
           '검증 순서 (문서마다)', '',
           '1. **자동 대조**에 ⚠ 가 있으면 원문(pdf)을 보고 어느 쪽이 맞는지 `문제` 칸에 적습니다.',
           '2. **검색 단위**의 경계를 봅니다. 빠짐·순서는 자동 대조의 "단위 본문 ↔ 파싱 결과" 줄이 이미 확인합니다. '
           '사람은 단위 하나가 한 상황을 온전히 담는지(절차 중간에서 잘리지 않음, 다른 항목 내용이 섞이지 않음, '
           'FAQ 질문과 답이 한 단위)만 보고 ☐ 를 ☑ 로 바꿉니다. 확인한 사람을 `문제` 칸에 적어도 됩니다. '
           '단위 본문은 `python -m app.rag.chunker <md 파일> --out <폴더>` 미리보기로 봅니다.',
           '3. **평가셋 겹침**이 있으면 그 표현이 `dataset/data/history.csv`·`faq.csv`에도 있는지 봅니다. '
           '있으면 일반 표현이라 괜찮고, 평가셋에만 있으면 고치도록 팀에 알립니다 (평가셋 문장은 검색 자료에 넣지 않음).',
           f'4. `{name}_질문.csv` 에 검색 질문을 {QUESTIONS_PER_DOC}개 이상 쓰고 `python -m app.rag.review check` 로 점검합니다.', '']
    for r in reviews:
        e = r.entry
        out += [f'## {r.doc_no} {e["title"]} ({e["version"]})', '',
                f'원문: `dataset/guides/{e["files"]["pdf"]}` · 검증 대상 형식: md', '',
                '### 자동 대조', '', '| 항목 | 문서 | manifest·규칙 | 결과 |', '|---|---|---|---|']
        out += [f'| {a} | {_cell(b)} | {_cell(c)} | {d} |' for a, b, c, d in doc_checks(r, base)]
        hits = _doc_overlaps(r, evalset)
        out += ['', '### 평가셋 겹침', '']
        out += [f'- ⚠ `{u}` {o.kind}: {o.eval_id} "{o.query}"' for u, o in hits] or ['- 없음']
        out += ['', '### 검색 단위', '', '| 확인 | 단위 (정답 단위로 씀) | 위치 | 제목 | 조각 | 글자 | 문의 유형 | 처리 구분 | 문제 |',
                '|---|---|---|---|---|---|---|---|---|']
        for unit in _group_units(r.chunks):
            c = unit[0]
            title = c.heading_path[-1] if c.heading_path else ''
            if c.chunk_type == 'faq':                     # FAQ 는 장 제목이 같아서 질문 첫 줄로 구분한다
                title = 'Q. ' + _short(c.body.strip().splitlines()[0] if c.body.strip() else '', 40)
            out.append(f'| ☐ | `{unit_ref(c.unit_key)}` | {c.section_no or "-"} | {_cell(title)} '
                       f'| {len(unit)} | {sum(x.char_count for x in unit)} | {", ".join(c.inquiry_type_codes) or "-"} '
                       f'| {c.handling or "-"} |  |')
        out.append('')
    return '\n'.join(out)


def _doc_overlaps(r: Review, evalset: EvalSet) -> list[tuple[str, Overlap]]:
    hits = [('키워드', o) for o in evalset.overlaps(' , '.join(r.doc.meta.get('keywords') or []))
            if o.kind == 'exact' or _keyword_hit(o, r.doc.meta.get('keywords') or [])]
    for c in r.chunks:
        hits += [(unit_ref(c.unit_key), o) for o in evalset.overlaps(c.body) if o.kind == 'exact']
    seen, out = set(), []
    for u, o in hits:
        if (u, o.eval_id) not in seen:
            seen.add((u, o.eval_id))
            out.append((u, o))
    return out


def _keyword_hit(o: Overlap, keywords: list[str]) -> bool:
    """키워드 하나가 평가셋 문장의 긴 부분과 같으면 (예: '로딩만 돌아요') 겹침으로 본다."""
    nq = _norm(o.query)
    return any(len(_norm(k)) >= 5 and _norm(k) in nq for k in keywords)


def _group_units(chunks: list[Chunk]) -> list[list[Chunk]]:
    units: dict[str, list[Chunk]] = {}
    for c in chunks:
        units.setdefault(c.unit_key, []).append(c)
    return list(units.values())


def _show(v) -> str:
    if v is None or v == '' or v == []:
        return '(없음)'
    if isinstance(v, list):
        return ', '.join(map(str, v))
    if isinstance(v, dict):
        return ', '.join(f'{k} {x}' for k, x in v.items())
    return str(v)


def _short(s: str, n: int) -> str:
    s = re.sub(r'^\W*Q\s*[.:)]\s*', '', s).strip()      # 'Q.' 머리만 지운다 ('QR코드…'의 Q 는 남김)
    return s if len(s) <= n else s[:n] + '…'


def _cell(s: str) -> str:
    return str(s).replace('|', '\\|').replace('\n', ' ')


def question_template(reviews: list[Review]) -> list[dict]:
    return [{'문서 번호': r.doc_no, '번호': n, '질문': '', '정답 단위': '', '작성자': '', '메모': ''}
            for r in reviews for n in range(1, QUESTIONS_PER_DOC + 1)]


# ── 검색 질문 점검 ─────────────────────────────────────────────

def sheet_docs(path: str) -> list[str]:
    """검증 시트에 들어 있는 문서 번호 ('## IT-ACC-001 …' 제목)."""
    with open(path, encoding='utf-8') as f:
        return re.findall(r'^## (IT-[A-Z]+-\d{3}(?:-M)?) ', f.read(), flags=re.M)


def check_questions(rows: list[dict], manifest: dict[str, dict], evalset: EvalSet,
                    units: dict[str, Chunk], targets: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(오류, 경고). 오류가 있으면 평가 도구에 넣지 않는다.

    units: unit_ref → 대표 청크 (현재 정리본에서 만든 것). 정답 단위는 ';' 로 여러 개 쓸 수 있다.
    검증 대상 문서는 targets(검증 시트의 문서) + csv 에 나온 문서 번호 전부다. 질문이 0개인 문서도 센다.
    """
    errors, warnings = [], []
    per_doc: dict[str, int] = {d: 0 for d in targets or []}
    seen: dict[str, str] = {}
    for i, row in enumerate(rows, start=2):                  # 2 = csv 머리줄 다음
        doc, q = (row.get('문서 번호') or '').strip(), (row.get('질문') or '').strip()
        answers = [a.strip() for a in (row.get('정답 단위') or '').split(';') if a.strip()]
        where = f'{i}행 {doc}'
        if doc:
            per_doc.setdefault(doc, 0)
        if not q and not answers:
            continue                                         # 양식의 빈 줄 (개수는 아래에서 센다)
        if doc not in manifest:
            errors.append(f'{where}: manifest 에 없는 문서 번호')
        elif not manifest[doc].get('rag_target', True):
            errors.append(f'{where}: 검색 대상이 아닌 문서 (rag_target=false)')
        if not q:
            errors.append(f'{where}: 질문이 비어 있음')
        if not answers:
            errors.append(f'{where}: 정답 단위가 비어 있음')
        for a in answers:
            if a not in units:
                errors.append(f'{where}: 정답 단위 {a} 가 없음 (검증 시트의 단위 칸에서 복사)')
            elif not a.startswith(doc + '/') and CROSS_DOC_MEMO not in (row.get('메모') or ''):
                warnings.append(f'{where}: 정답 단위 {a} 가 다른 문서 (의도한 것이면 메모에 "{CROSS_DOC_MEMO} <이유>")')
        if q:
            key = _norm(q)
            if key in seen:
                errors.append(f'{where}: 같은 질문이 {seen[key]} 에도 있음')
            seen[key] = where
            for o in evalset.overlaps(q):
                (errors if o.kind == 'exact' else warnings).append(
                    f'{where}: 평가셋 {o.eval_id} "{o.query}" 와 {"같음" if o.kind == "exact" else "비슷함"} → 다르게 쓰기')
            for a in answers:
                if a in units and len(key) >= 10 and key in _norm(units[a].body):
                    warnings.append(f'{where}: 질문이 정답 본문 문장을 그대로 옮김 (사용자 말투로 바꾸면 더 좋은 시험)')
            per_doc[doc] = per_doc.get(doc, 0) + 1
    if not per_doc:
        errors.append('문서 번호가 있는 행이 없음 (sheet 명령이 만든 양식을 쓴다)')
    for doc, n in per_doc.items():
        if n < QUESTIONS_PER_DOC:
            errors.append(f'{doc}: 질문 {n}개 (문서마다 {QUESTIONS_PER_DOC}개 이상)')
    return errors, warnings


def all_units(manifest: dict[str, dict], root: str = GUIDES) -> dict[str, Chunk]:
    """정리본 전체의 unit_ref → 첫 조각 (본문은 조각을 이어 붙인다)."""
    out: dict[str, Chunk] = {}
    for doc_no, e in manifest.items():
        if not e.get('rag_target', True):
            continue
        for unit in _group_units(chunk_document(parse(source_path(e, root)))):
            first = unit[0]
            ref = unit_ref(first.unit_key)
            out[ref] = Chunk(**{**first.to_dict(), 'body': '\n'.join(c.body for c in unit)})
    return out


def read_questions(path: str) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_questions(path: str, rows: list[dict]) -> None:
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:     # 엑셀에서 한글이 깨지지 않게 BOM
        w = csv.DictWriter(f, fieldnames=QUESTION_COLUMNS)
        w.writeheader()
        w.writerows(rows)
