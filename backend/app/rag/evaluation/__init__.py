"""검색 평가 도구 (WBS M2-2-2). 질문 → 검색 → 상위 k개 안에 정답이 있는가를 묶음별로 채점한다.

시험지 두 가지:
- 가이드 검색 질문 (dataset/guide_review/*_질문.csv): 정답 단위(unit_ref). 단위 적중·문서 적중
- 평가셋 (dataset/data/eval_inquiries.csv): expected_scenario → taxonomy.json scenarios[].manual(가이드 번호)로 문서 적중,
  항목 머리 문의 유형에 그 시나리오가 있는 단위로 단위 적중

검색기는 바꿔 끼운다: BM25(메모리, DB·모델 없이) / 실제 검색 search() / DB 벡터(적재된 청크 벡터를 읽고 질문만 임베딩).
분류·긴급도·처리 방향·팀 채점은 judgment.py (M2-4-1, 판단 흐름 run_flow 로).
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..chunker import chunk_document, transfer_policy, unit_ref, view_scope
from ..parser import parse
from ..review import GUIDES, load_manifest, source_path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
QUESTIONS_DIR = os.path.join(REPO, 'dataset', 'guide_review')
EVAL_CSV = os.path.join(REPO, 'dataset', 'data', 'eval_inquiries.csv')
TAXONOMY = os.path.join(REPO, 'dataset', 'data', 'taxonomy.json')
OUT = os.path.join(REPO, '작업대', '평가결과')

TOP_K = (1, 3, 5)
MRR_K = 10
CANDIDATES = 100          # 같은 본문 묶기 전 후보 수 = k × 100 (사실상 전부). 검색 API 8장은 k × 3 이지만,
                          # 같은 '문의처' 장이 27개 문서에 있어 30개 후보가 묶이면 결과가 k개보다 적어진다.
                          # 평가는 모델의 순위 실력을 재므로 이 제한으로 점수가 깎이지 않게 한다 (README '알려진 것')
ROLE_SCOPES = {'EMPLOYEE': ('ALL',), 'AGENT': ('ALL', 'AGENT'), 'ADMIN': ('ALL', 'AGENT', 'ADMIN')}   # search/result.py 와 같다

# 가이드 질문 묶음: 메모 태그는 ' / '로 이어 붙어 있어 포함 여부로 본다 (dataset/guide_review/README.md)
TAG_RUDE, TAG_EASY, TAG_BRANCH = '말투: 반말·무례', '난이도: 쉬움', '분기:'


# ── 검색 단위 ──────────────────────────────────────────────────

@dataclass
class Unit:
    ref: str                       # IT-SW-003/item:3.1 (버전 없는 단위 참조)
    doc: str
    text: str                      # 머리말 + 본문 (조각을 이은 것) — 키워드 검색 대상
    body_hash: str                 # sha1(본문). 같은 본문이 여러 문서에 있으면 같은 정답으로 본다
    view_scope: str
    transfer_policy: str = 'BLOCKED'
    codes: frozenset = frozenset()  # 항목 머리의 문의 유형 코드 (평가셋 단위 정답에 쓴다)

    @property
    def dup_key(self) -> tuple[str, str]:
        return self.body_hash, self.transfer_policy


def corpus_units(manifest: dict[str, dict] | None = None, root: str = GUIDES) -> list[Unit]:
    """정리본의 검색 대상 문서를 청커로 나눈 단위 목록 (조각은 이어 붙인다)."""
    manifest = manifest or load_manifest(root)
    units: dict[str, list] = {}
    for doc_no, e in manifest.items():
        if not e.get('rag_target', True):
            continue
        for c in chunk_document(parse(source_path(e, root))):
            units.setdefault(c.unit_key, []).append(c)
    out = []
    for parts in units.values():
        c = parts[0]
        body = '\n'.join(p.body for p in parts)
        out.append(Unit(unit_ref(c.unit_key), c.doc_no, '\n'.join(p.text for p in parts), body_hash(body),
                        view_scope(c.access_level), transfer_policy(manifest[c.doc_no].get('transfer_policy')),
                        frozenset(x for p in parts for x in p.inquiry_type_codes)))
    return out


def body_hash(body: str) -> str:
    return hashlib.sha1(body.encode('utf-8')).hexdigest()


def same_body(units: list[Unit]) -> dict[str, set[str]]:
    """단위 → 본문과 외부 전송 정책이 같은 단위들(자기 포함).

    검색 API가 이런 단위를 하나로 묶어 보여 주므로(청크_메타데이터.md 8장 3번) 정답도 같은 묶음으로 본다.
    """
    by_key: dict[tuple, set[str]] = defaultdict(set)
    for u in units:
        by_key[u.dup_key].add(u.ref)
    return {u.ref: by_key[u.dup_key] for u in units}


# ── 시험지 ─────────────────────────────────────────────────────

@dataclass
class Question:
    set: str                       # guide · eval
    qid: str                       # IT-ACC-001#2 · EV-001
    text: str
    answers: set[str] = field(default_factory=set)      # 정답 단위 (같은 본문 단위 포함). 비어 있으면 단위 채점에서 뺀다
    answer_docs: set[str] = field(default_factory=set)
    groups: list[str] = field(default_factory=list)     # 집계 묶음 이름


def load_guide_questions(units: list[Unit], path: str = QUESTIONS_DIR) -> list[Question]:
    eq = same_body(units)
    doc_of = {u.ref: u.doc for u in units}
    out = []
    for f in sorted(glob.glob(os.path.join(path, '*_질문.csv'))):
        with open(f, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                q = (r.get('질문') or '').strip()
                if not q:
                    continue
                refs = [a.strip() for a in (r.get('정답 단위') or '').split(';') if a.strip()]
                answers = set().union(*(eq.get(a, {a}) for a in refs)) if refs else set()
                memo = r.get('메모') or ''
                doc = r['문서 번호'].strip()
                groups = ['전체', '반말·무례' if TAG_RUDE in memo else '반말 제외', '쉬움' if TAG_EASY in memo else '쉬움 제외',
                          f"작성: {r.get('작성자') or '?'}", '매뉴얼 질문' if doc.endswith('-M') else '가이드·기준 질문']
                if TAG_BRANCH in memo:
                    groups.append('분기 질문')
                out.append(Question('guide', f"{doc}#{r['번호']}", q, answers,
                                    {doc_of[a] for a in answers if a in doc_of} or {a.split('/', 1)[0] for a in refs},
                                    groups))
    return out


def load_eval_set(path: str = EVAL_CSV, taxonomy: str = TAXONOMY,
                  units: list[Unit] | None = None) -> tuple[list[Question], list[str]]:
    """평가셋 → 질문들, 시나리오가 없어(-) 검색 채점에서 뺀 eval_id 들.

    문서 정답: taxonomy 의 가이드 번호. 단위 정답(units 를 주면): 항목 머리 문의 유형에 그 시나리오가 있는 단위
    (C의 모델 비교 search/compare.py 와 같은 정의). 같은 본문 단위도 정답으로 넓힌다.
    """
    eq = same_body(units) if units else {}
    with open(taxonomy, encoding='utf-8') as f:
        docs_of = {s['id']: {d.strip() for d in s['manual'].split(',') if d.strip()} for s in json.load(f)['scenarios']}
    out, skipped = [], []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            docs = docs_of.get(r['expected_scenario'].strip())
            if not docs:
                skipped.append(r['eval_id'])
                continue
            scen = r['expected_scenario'].strip()
            ans = set().union(*(eq[u.ref] for u in units if scen in u.codes)) if units else set()
            out.append(Question('eval', r['eval_id'], r['query'].strip(), ans, docs, ['전체', r['dataset_split']]))
    return out, skipped


# ── 검색기 ─────────────────────────────────────────────────────

@dataclass
class Hit:
    ref: str
    doc: str
    score: float
    also: list[tuple[str, str]] = field(default_factory=list)   # 같은 본문이라 이 결과에 묶인 (단위, 문서)

    @property
    def refs(self) -> set[str]:
        return {self.ref} | {r for r, _ in self.also}

    @property
    def docs(self) -> set[str]:
        return {self.doc} | {d for _, d in self.also}


def collapse(hits: list[Hit], dup_key: dict[str, tuple] | None, k: int) -> list[Hit]:
    """본문·전송 정책이 같은 결과를 처음 나온 것 하나로 묶고 k개로 자른다 (검색 API 8장 3번과 같은 순서)."""
    if not dup_key:
        return hits[:k]
    first: dict[tuple, Hit] = {}
    out: list[Hit] = []
    for h in hits:
        key = dup_key.get(h.ref, ('ref', h.ref))
        if key in first:
            first[key].also.append((h.ref, h.doc))
            continue
        first[key] = h
        out.append(h)
    return out[:k]


_WORD_RE = re.compile(r'[0-9A-Za-z가-힣]+')


def tokens(text: str) -> list[str]:
    """단어 + 한글 2글자 묶음. 조사가 붙은 한국어도 겹치게 한다 ('로그인이' ↔ '로그인')."""
    out = []
    for w in _WORD_RE.findall(text.lower()):
        out.append(w)
        if len(w) > 2 and re.search('[가-힣]', w):
            out += [w[i:i + 2] for i in range(len(w) - 1)]
    return out


class BM25Retriever:
    """기준선 검색기. DB·모델 없이 청커 결과를 메모리에서 찾는다."""

    def __init__(self, units: list[Unit], k1: float = 1.5, b: float = 0.75):
        self.name, self.units, self.k1, self.b = 'bm25', units, k1, b
        self.dup_key = {u.ref: u.dup_key for u in units}
        self.docs = [Counter(tokens(u.text)) for u in units]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, k: int = MRR_K) -> list[Hit]:
        q = Counter(tokens(query))
        scores = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in q:
                tf = d.get(t)
                if tf:
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        return [Hit(self.units[i].ref, self.units[i].doc, s) for s, i in scores[:k]]


class VectorRetriever:
    """청크 벡터와 질문 벡터의 내적(단위 벡터라 코사인). 단위 점수는 조각 점수 중 가장 높은 값 (8장 unit_score)."""

    def __init__(self, name: str, rows: list[tuple[str, str, list[float]]], embed_query, dup_key: dict | None = None):
        import numpy as np
        self.name, self._embed, self.dup_key = name, embed_query, dup_key
        self.refs = [r for r, _, _ in rows]
        self.docs = [d for _, d, _ in rows]
        self.mat = np.asarray([v for _, _, v in rows], dtype='float32')

    def search(self, query: str, k: int = MRR_K) -> list[Hit]:
        import numpy as np
        scores = self.mat @ np.asarray(self._embed(query), dtype='float32')
        best: dict[str, tuple[float, str]] = {}
        for i in np.argsort(-scores):
            ref = self.refs[i]
            if ref not in best:
                best[ref] = (float(scores[i]), self.docs[i])
                if len(best) >= k:
                    break
        return [Hit(r, d, s) for r, (s, d) in best.items()]


class SearchApiRetriever:
    """실제 검색 기능 search() (C, M3-2-2)으로 찾는다: 조각 복원·같은 본문 묶기·k×6 재시도·권한 필터를 그대로 쓴다.

    챗봇이 쓰는 경로를 채점한다. 읽기 전용 트랜잭션에서 돌고, 결과가 이미 묶여 있어 평가 쪽에서 다시 묶지 않는다.
    """
    final_k = True                 # search() 가 k개로 잘라 준다 → 후보를 더 받지 않는다

    def __init__(self, database_url: str, embedder, role: str):
        from sqlalchemy import create_engine
        self.engine = create_engine(database_url.replace('postgresql://', 'postgresql+psycopg://', 1), pool_pre_ping=True)
        self.name, self.role, self.emb, self.dup_key = f'search:{embedder.key} ({embedder.model_id})', role, embedder, None

    def search(self, query: str, k: int = MRR_K) -> list[Hit]:
        from sqlalchemy import exc, text
        from sqlalchemy.orm import Session
        from ..search import SearchRequest
        from ..search.service import search
        try:
            with Session(self.engine) as s:
                s.execute(text('set transaction read only'))
                resp = search(s, SearchRequest(query=query, service_role=self.role, sources=('DOCUMENT',), top_k=k), self.emb)
                s.rollback()
        except exc.OperationalError as ex:
            raise RuntimeError(f'DB 연결 실패 ({type(ex.orig).__name__}, 주소는 출력하지 않음)') from None
        return hits_from_response(resp)


def hits_from_response(resp) -> list[Hit]:
    """SearchResponse.documents → Hit. also_in(같은 본문이라 묶인 단위)은 묶인 출처로 둔다."""
    return [Hit(unit_ref(d.unit_key), d.doc_code, float(d.unit_score),
                [(unit_ref(x), unit_ref(x).split('/', 1)[0]) for x in d.also_in]) for d in resp.documents]


def db_vector_rows(database_url: str, model_id: str, role: str = 'AGENT') -> tuple[list[tuple[str, str, list[float]]], dict]:
    """적재된 청크 벡터와 단위별 묶기 키(sha1(본문), 전송 정책)를 읽는다 (읽기 전용).

    검색 API와 같은 조인 조건: 활성 문서, 현행·DONE 버전, 열람 범위. 연결 오류 메시지에 주소가 섞이지 않게 감싼다.
    """
    import psycopg
    from pgvector.psycopg import register_vector
    try:
        conn = psycopg.connect(database_url, connect_timeout=15)
    except psycopg.Error as ex:
        raise RuntimeError(f'DB 연결 실패 ({type(ex).__name__}, 주소는 출력하지 않음)') from None
    with conn:
        conn.read_only = True
        register_vector(conn)
        rows = conn.execute(
            """select ch.unit_key, d.doc_code, e.embedding, ch.part, ch.content, v.transfer_policy
                 from document_chunk_embeddings e
                 join document_chunks ch on ch.id = e.chunk_id
                 join document_versions v on v.id = ch.version_id
                 join knowledge_documents d on d.id = v.document_id
                where e.model = %s and d.is_active and v.is_current and v.ingest_status = 'DONE'
                  and v.view_scope = any(%s)""",
            (model_id, list(ROLE_SCOPES[role]))).fetchall()
    if not rows:
        raise RuntimeError(f'DB에 {model_id} 벡터가 없습니다 (적재 전이거나 모델 이름이 다름)')
    parts: dict[str, list] = defaultdict(list)
    policy: dict[str, str] = {}
    for uk, _, _, part, content, tp in rows:
        parts[unit_ref(uk)].append((part, content))
        policy[unit_ref(uk)] = tp
    dup_key = {r: (body_hash('\n'.join(c for _, c in sorted(ps))), policy[r]) for r, ps in parts.items()}
    vecs = [(unit_ref(uk), doc, vec.to_list() if hasattr(vec, 'to_list') else list(vec))   # pgvector Vector
            for uk, doc, vec, _, _, _ in rows]
    return vecs, dup_key


# ── 채점 ───────────────────────────────────────────────────────

@dataclass
class Result:
    question: Question
    hits: list[Hit]
    unit_rank: int | None          # 처음 맞힌 순위 (1부터), 없으면 None. 정답 단위가 없는 질문도 None
    doc_rank: int | None


def rank_of(hits: list[Hit], ok) -> int | None:
    return next((i for i, h in enumerate(hits, 1) if ok(h)), None)


def evaluate(retriever, questions: list[Question], k: int = MRR_K) -> list[Result]:
    """검색 → 같은 본문 묶기 → k개 → 순위. 묶인 출처(also)도 정답 판정에 쓴다."""
    dup_key = getattr(retriever, 'dup_key', None)
    n = k if getattr(retriever, 'final_k', False) else k * CANDIDATES
    out = []
    for q in questions:
        hits = collapse(retriever.search(q.text, n), dup_key, k)
        unit = rank_of(hits, lambda h: bool(h.refs & q.answers)) if q.answers else None
        out.append(Result(q, hits, unit, rank_of(hits, lambda h: bool(h.docs & q.answer_docs))))
    return out


def scores(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if not n:
        return {'n': 0}
    d = {'n': n}
    for k in TOP_K:
        d[f'hit@{k}'] = sum(1 for r in ranks if r and r <= k) / n
    d[f'mrr@{MRR_K}'] = sum(1 / r for r in ranks if r and r <= MRR_K) / n
    return d


def summarize(results: list[Result]) -> dict[str, dict[str, dict]]:
    """{시험지: {묶음: {단위: 점수, 문서: 점수}}}"""
    groups: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in results:
        for g in r.question.groups:
            groups[(r.question.set, g)].append(r)
    out: dict[str, dict] = defaultdict(dict)
    for (s, g), rs in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1] != '전체', x[0][1])):   # 전체를 먼저
        out[s][g] = {'문서': scores([r.doc_rank for r in rs])}
        with_units = [r for r in rs if r.question.answers]
        if with_units:
            out[s][g]['단위'] = scores([r.unit_rank for r in with_units])
    return dict(out)


def restrict_to_role(questions: list[Question], units: list[Unit], role: str) -> tuple[list[Question], list[str]]:
    """역할이 볼 수 없는 문서만 정답인 질문은 뺀다 (예: 직원 권한에서 매뉴얼 질문)."""
    visible = {u.doc for u in units if u.view_scope in ROLE_SCOPES[role]}
    keep, dropped = [], []
    for q in questions:
        (keep if q.answer_docs & visible else dropped).append(q)
    return keep, [q.qid for q in dropped]


# ── 기록 ───────────────────────────────────────────────────────

def file_hash(paths: list[str]) -> str:
    h = hashlib.sha1()
    for p in sorted(paths):
        with open(p, 'rb') as f:
            h.update(f.read())
    return h.hexdigest()[:12]


def code_fingerprint() -> str:
    """채점에 영향을 주는 코드(평가·청커·파서·검증 도구·검색·임베딩)의 지문. 커밋 전 변경도 구분한다."""
    rag = os.path.join(HERE, '..')
    files = []
    for sub in ('evaluation', 'chunker', 'parser', 'review', 'search', 'embedding'):   # search: 는 search()·Embedder 를 실행
        files += glob.glob(os.path.join(rag, sub, '*.py'))
    return file_hash(files)


def units_fingerprint(units: list[Unit]) -> str:
    """검색 대상 단위(참조·본문·열람·전송 정책)의 지문. 가이드나 청커가 바뀌면 달라진다."""
    h = hashlib.sha1()
    for u in sorted(units, key=lambda x: x.ref):
        h.update(f'{u.ref}|{u.body_hash}|{u.view_scope}|{u.transfer_policy}\n'.encode('utf-8'))
    return h.hexdigest()[:12]


def new_run_dir(base: str, name: str) -> str:
    """결과 폴더를 새로 만든다. 이미 있으면 -2, -3 … (같은 시각에 다시 실행해도 덮어쓰지 않는다)."""
    os.makedirs(base, exist_ok=True)
    for n in range(1, 1000):
        path = os.path.join(base, name if n == 1 else f'{name}-{n}')
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f'결과 폴더를 만들 수 없음: {name}')


def git_state() -> str:
    import subprocess
    try:
        head = subprocess.run(['git', '-C', REPO, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', REPO, 'status', '--porcelain', '--', 'backend', 'dataset'],
                               capture_output=True, text=True).stdout.strip()
        return head + (' (커밋 안 된 변경 있음)' if dirty else '')
    except OSError:
        return '?'


def write_results(out_dir: str, results: list[Result], meta: dict) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, '질문별.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['시험지', '질문 id', '묶음', '질문', '정답 단위', '정답 문서', '단위 순위', '문서 순위'] +
                   [f'{i}위' for i in range(1, 6)])
        for r in results:
            q = r.question
            w.writerow([q.set, q.qid, ' / '.join(q.groups[1:]), q.text, '; '.join(sorted(q.answers)), '; '.join(sorted(q.answer_docs)),
                        r.unit_rank or '', r.doc_rank or ''] + [f'{h.ref} ({h.score:.3f})' + (f' +{len(h.also)}' if h.also else '') for h in r.hits[:5]])
    summary = {'meta': meta, '점수': summarize(results)}
    with open(os.path.join(out_dir, '요약.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, '요약.md'), 'w', encoding='utf-8') as f:
        f.write(summary_md(summary))
    return summary


def summary_md(summary: dict) -> str:
    m = summary['meta']
    out = [f"# 검색 평가 — {m['retriever']}", '', '| 항목 | 값 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in m.items()]
    names = {'guide': '가이드 검색 질문', 'eval': '평가셋'}
    for s, groups in summary['점수'].items():
        cols = ['문서'] + (['단위'] if any('단위' in v for v in groups.values()) else [])
        out += ['', f'## {names.get(s, s)}', '',
                '| 묶음 | n | ' + ' | '.join(f'{c} {x}' for c in cols for x in (*[f'Hit@{k}' for k in TOP_K], f'MRR@{MRR_K}')) + ' |',
                '|---|---|' + '---|' * (len(cols) * (len(TOP_K) + 1))]
        for g, sc in groups.items():
            cells = [f"{sc[c].get(x, 0):.3f}" if c in sc else '—' for c in cols for x in (*[f'hit@{k}' for k in TOP_K], f'mrr@{MRR_K}')]
            out.append(f"| {g} | {sc['문서']['n']} | " + ' | '.join(cells) + ' |')
    return '\n'.join(out) + '\n'
