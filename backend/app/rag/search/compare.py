"""임베딩 모델(+리랭커) 비교 (WBS M3-2-1). DB 없이 가이드 파일을 직접 임베딩해 Golden Set으로 잰다.

    python -m app.rag.search.compare                         # KURE-v1 · BGE-M3
    python -m app.rag.search.compare --rerank                # 각각에 리랭커를 붙인 구성까지 4가지
    python -m app.rag.search.compare --rerank --out 결과.md   # 결과표와 문항별 결과를 파일로

- 검색 대상: manifest 의 rag_target 문서 중 일반 임직원이 볼 수 있는 문서(사내 일반 → ALL).
  평가셋은 일반 임직원의 문의라서 실제 검색과 같은 범위로 잰다.
- 정답: 평가셋 expected_scenario 가 청크의 inquiry_type_codes 에 들어 있는 항목(단위).
  문서 정답은 manifest 의 scenarios 에 그 시나리오가 있는 문서.
- 점수: 청크마다 코사인 유사도를 재고, 단위 점수 = 그 단위 청크 점수 중 최댓값 (청크_메타데이터.md 8장).
- 평가셋 문장은 질문으로만 쓴다. 검색 대상·임베딩 캐시에 넣지 않는다 (dataset/README).
- 가이드 임베딩은 모델 폴더의 _cache/ 에 저장해 두고 다시 돌릴 때 쓴다 (모델당 CPU 약 15분).
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

import numpy as np

from app.rag.chunker import chunk_document, view_scope
from app.rag.embedding import Embedder, MODELS, model_dir, model_id
from app.rag.parser import parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
GUIDES = os.path.join(ROOT, 'dataset', 'guides')
EVAL = os.path.join(ROOT, 'dataset', 'data', 'eval_inquiries.csv')
RERANKER = {'folder': 'bge-reranker-v2-m3', 'repo': 'BAAI/bge-reranker-v2-m3',
            'revision': '953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
RERANK_TOP = 10          # 리랭커가 다시 매기는 후보 단위 수
KS = (1, 3, 5)


@dataclass
class Unit:
    key: str                       # unit_key
    doc_no: str
    chunk_type: str
    codes: set = field(default_factory=set)
    texts: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return '\n'.join(self.texts)


def load_units(scope: str = 'ALL'):
    """검색 대상 청크와 단위. scope 는 볼 수 있는 view_scope (ALL = 일반 임직원)."""
    with open(os.path.join(GUIDES, 'manifest.json'), encoding='utf-8') as f:
        manifest = [d for d in json.load(f) if d.get('rag_target') is not False]
    chunks, units, doc_scenarios = [], {}, {}
    for d in manifest:
        if view_scope(d.get('access_level', '')) != scope:
            continue
        doc_scenarios[d['doc_no']] = set(d.get('scenarios') or [])
        for c in chunk_document(parse(os.path.join(GUIDES, d['files']['md']))):
            chunks.append(c)
            u = units.setdefault(c.unit_key, Unit(c.unit_key, c.doc_no, c.chunk_type))
            u.codes.update(c.inquiry_type_codes)
            u.texts.append(c.text)
    return chunks, units, doc_scenarios


def load_eval(units, doc_scenarios):
    """정답이 있는 평가 문항. 정답 항목이 검색 범위에 없는 문항은 따로 센다."""
    with open(EVAL, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    usable, no_gold = [], []
    for r in rows:
        s = r['expected_scenario']
        if s in ('', '-'):
            continue
        gold_units = {k for k, u in units.items() if s in u.codes}
        gold_docs = {doc for doc, ss in doc_scenarios.items() if s in ss}
        item = {'id': r['eval_id'], 'query': r['query'], 'scenario': s, 'action': r['expected_action'],
                'gold_units': gold_units, 'gold_docs': gold_docs}
        (usable if gold_units else no_gold).append(item)
    return usable, no_gold


def cached_embeddings(key: str, texts: list[str]) -> np.ndarray:
    """가이드 청크 임베딩. 같은 모델·같은 글이면 캐시를 쓴다."""
    digest = hashlib.sha1('\x1e'.join(texts).encode('utf-8')).hexdigest()[:12]
    path = model_dir() / '_cache' / f"guides_{model_id(key).replace('/', '_').replace('@', '_')}_{digest}.npy"
    if path.exists():
        return np.load(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    vecs = np.array(Embedder(key).embed_documents(texts), dtype=np.float32)
    np.save(path, vecs)
    print(f'  [{key}] 가이드 청크 {len(texts)}개 임베딩 {time.perf_counter() - t0:.0f}초 → {path.name}')
    return vecs


def rank_units(scores: np.ndarray, chunks) -> list[tuple[str, float]]:
    best = {}
    for c, s in zip(chunks, scores):
        if s > best.get(c.unit_key, -9):
            best[c.unit_key] = float(s)
    return sorted(best.items(), key=lambda kv: -kv[1])


def first_hit(ranked_keys, gold) -> int | None:
    return next((i for i, k in enumerate(ranked_keys) if k in gold), None)


def evaluate(key, chunks, units, items, reranker=None):
    emb = Embedder(key)
    vecs = cached_embeddings(key, [c.text for c in chunks])
    rows, times = [], []
    for it in items:
        t0 = time.perf_counter()
        q = np.array(emb.embed_query(it['query']), dtype=np.float32)
        ranked = rank_units(vecs @ q, chunks)
        if reranker is not None:
            top = ranked[:RERANK_TOP]
            sc = reranker.predict([(it['query'], units[k].text) for k, _ in top], batch_size=4)
            ranked = [top[i] for i in np.argsort(-np.asarray(sc))] + ranked[RERANK_TOP:]
        times.append(time.perf_counter() - t0)
        keys = [k for k, _ in ranked]
        docs = list(dict.fromkeys(units[k].doc_no for k in keys))
        rows.append({'id': it['id'], 'scenario': it['scenario'], 'action': it['action'],
                     'unit_rank': first_hit(keys, it['gold_units']), 'doc_rank': first_hit(docs, it['gold_docs']),
                     'top1': keys[0], 'top1_score': ranked[0][1]})
    del emb
    return rows, times


def summarize(name, rows, times):
    ur = [r['unit_rank'] for r in rows]
    dr = [r['doc_rank'] for r in rows]
    hit = lambda ranks, k: sum(r is not None and r < k for r in ranks) / len(ranks)
    mrr = sum(1 / (r + 1) for r in ur if r is not None) / len(ur)
    return {'name': name, 'n': len(rows), **{f'unit@{k}': hit(ur, k) for k in KS},
            **{f'doc@{k}': hit(dr, k) for k in (1, 3)}, 'mrr': mrr, 'sec': sum(times) / len(times)}


def report(summaries, details, no_gold, n_chunks, n_units) -> str:
    lines = [f'검색 대상: 일반 임직원 범위 청크 {n_chunks}개 · 단위 {n_units}개. '
             f'평가 문항 {summaries[0]["n"]}개 (정답 항목이 범위에 없는 문항 {len(no_gold)}개 제외)', '',
             '| 구성 | 항목 Hit@1 | 항목 Hit@3 | 항목 Hit@5 | MRR | 문서 Hit@1 | 문서 Hit@3 | 질문 1개 |',
             '|---|---|---|---|---|---|---|---|']
    for s in summaries:
        lines.append(f"| {s['name']} | {s['unit@1']:.0%} | {s['unit@3']:.0%} | {s['unit@5']:.0%} | {s['mrr']:.3f} "
                     f"| {s['doc@1']:.0%} | {s['doc@3']:.0%} | {s['sec']:.2f}초 |")
    if no_gold:
        lines += ['', '정답 항목이 범위에 없어 뺀 문항: ' + ', '.join(f"{x['id']}({x['scenario']})" for x in no_gold)]
    lines += ['', '문항별 정답 항목 순위 (없음 = 끝까지 못 찾음)', '',
              '| 문항 | 시나리오 | ' + ' | '.join(s['name'] for s in summaries) + ' |',
              '|---|---|' + '---|' * len(summaries)]
    by_id = [{r['id']: r for r in d} for d in details]
    for r in details[0]:
        cells = [str(b[r['id']]['unit_rank'] + 1) if b[r['id']]['unit_rank'] is not None else '없음' for b in by_id]
        lines.append(f"| {r['id']} | {r['scenario']} | " + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description='임베딩 모델(+리랭커) 비교 (M3-2-1)')
    ap.add_argument('--models', nargs='+', choices=list(MODELS), default=list(MODELS))
    ap.add_argument('--rerank', action='store_true', help='각 모델에 리랭커를 붙인 구성도 잰다')
    ap.add_argument('--out', help='결과를 이 Markdown 파일로 저장')
    args = ap.parse_args()

    chunks, units, doc_scenarios = load_units('ALL')
    items, no_gold = load_eval(units, doc_scenarios)
    print(f'청크 {len(chunks)}개 · 단위 {len(units)}개 · 평가 문항 {len(items)}개 (정답 없음 {len(no_gold)}개)')
    reranker = None
    if args.rerank:
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(str(model_dir() / RERANKER['folder']), device='cpu', max_length=1024)
    summaries, details = [], []
    for key in args.models:
        for rr in ([None, reranker] if reranker else [None]):
            name = key + (' + 리랭커' if rr else '')
            rows, times = evaluate(key, chunks, units, items, rr)
            summaries.append(summarize(name, rows, times))
            details.append(rows)
            s = summaries[-1]
            print(f"  {name}: 항목 Hit@1 {s['unit@1']:.0%} Hit@3 {s['unit@3']:.0%} MRR {s['mrr']:.3f} · {s['sec']:.2f}초")
    text = report(summaries, details, no_gold, len(chunks), len(units))
    print('\n' + text)
    if args.out:
        with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
