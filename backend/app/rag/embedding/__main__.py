"""임베딩 모델 받기·확인·시험 (WBS M3-1-2). backend 폴더에서 실행한다.

    python -m app.rag.embedding check              # 파일이 다 있는지만 본다 (모델을 열지 않는다)
    python -m app.rag.embedding download           # 없는 모델을 받는다 (약 4.6GB, 고정 리비전)
    python -m app.rag.embedding smoke              # 두 모델을 열어 샘플 임베딩·메모리·속도·FAQ 적중을 잰다
    python -m app.rag.embedding smoke --model kure-v1 --chunks 0

모델 폴더는 EMBEDDING_MODEL_DIR (기본: 저장소 바로 옆 models/).
smoke 의 FAQ 시험은 faq.csv 를 쓴다. 평가셋(eval_inquiries.csv)은 쓰지 않는다.
"""
import argparse
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

from app.rag.embedding.models import MODELS, ROOT, check_files, model_dir, model_id


def rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / 2**20


def cmd_check(keys) -> int:
    base = model_dir()
    print(f'모델 폴더: {base}')
    bad = 0
    for k in keys:
        problems = check_files(k, base)
        print(f"  {'X' if problems else 'v'} {k:8} {MODELS[k]['repo']}@{MODELS[k]['revision'][:7]}")
        for p in problems:
            print(f'      {p}')
        bad += bool(problems)
    return 1 if bad else 0


def cmd_download(keys) -> int:
    os.environ.pop('HF_HUB_OFFLINE', None)                     # 받을 때는 온라인. import 전에
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '60')     # 기본 10초면 GB 파일이 끊긴다
    from huggingface_hub import snapshot_download

    base = model_dir()
    base.mkdir(parents=True, exist_ok=True)
    need = [k for k in keys if check_files(k, base)]
    if not need:
        print('받을 모델이 없습니다 (모두 있음).')
        return cmd_check(keys)
    free = shutil.disk_usage(base).free
    if free < 2.5e9 * len(need):
        sys.exit(f'디스크 여유 {free / 1e9:.1f}GB — {2.5 * len(need):.1f}GB 이상 필요합니다.')
    for k in need:
        spec = MODELS[k]
        print(f"[{k}] {spec['repo']}@{spec['revision'][:7]} → {base / spec['folder']}")
        for attempt in range(1, 4):
            try:
                snapshot_download(repo_id=spec['repo'], revision=spec['revision'],
                                  local_dir=base / spec['folder'], allow_patterns=spec['files'])
                break
            except Exception as e:                             # 끊겨도 받은 만큼은 남아 이어 받는다
                print(f'  {attempt}회차 실패: {type(e).__name__}: {e}')
                if attempt == 3:
                    return 1
                time.sleep(10)
    return cmd_check(keys)


def faq_pairs():
    with open(ROOT / 'dataset' / 'data' / 'faq.csv', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return [r['question'] for r in rows], [r['answer'] for r in rows]


def guide_chunks():
    from app.rag.chunker import chunk_document
    from app.rag.parser import parse
    texts = []
    for path in sorted(glob.glob(str(ROOT / 'dataset' / 'guides' / '**' / '*.md'), recursive=True)):
        if os.path.basename(path).upper() == 'README.MD':
            continue
        texts += [c.text for c in chunk_document(parse(path))]
    return texts


def cmd_smoke(keys, n_chunks) -> int:
    """모델마다 따로 프로세스를 띄워 잰다. 한 프로세스에서 이어 재면 앞 모델의 메모리가 남아 값이 틀린다."""
    if cmd_check(keys):
        return 1
    summary = []
    for k in keys:
        out = subprocess.run([sys.executable, '-m', 'app.rag.embedding', 'smoke-one', '--model', k,
                              '--chunks', str(n_chunks)], capture_output=True, text=True, encoding='utf-8',
                             env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        for line in out.stdout.splitlines():
            if line.startswith('RESULT '):
                summary.append(json.loads(line[7:]))
            else:
                print(line)
        if out.returncode:
            print(out.stderr[-2000:])
            return out.returncode

    print('\n| 모델 | 여는 시간 | 질문 1개 | FAQ Top1 | FAQ Top3 | MRR | 메모리 | 가이드 청크 |')
    print('|---|---|---|---|---|---|---|---|')
    for r in summary:
        mem = f"{r['peak_mb'] / 1024:.1f}GB" if r['peak_mb'] else '-'
        print(f"| {r['key']} | {r['load_s']:.1f}초 | {r['query_ms']:.0f}ms | {r['top1']:.0%} | {r['top3']:.0%} "
              f"| {r['mrr']:.3f} | {mem} | {r['chunk_note'] or '-'} |")
    return 0


def cmd_smoke_one(k, n_chunks) -> int:
    """모델 하나를 열어 잰다. smoke 가 모델마다 새 프로세스로 부른다."""
    import numpy as np
    from app.rag.embedding.embedder import Embedder

    questions, answers = faq_pairs()
    chunks = guide_chunks() if n_chunks else []
    print(f'\n[{k}] {model_id(k)}')
    before = rss_mb()
    t0 = time.perf_counter()
    emb = Embedder(k)
    load_s = time.perf_counter() - t0
    after = rss_mb()

    t0 = time.perf_counter()
    sample = np.array(emb.embed_documents(questions[:20]))
    sample_s = time.perf_counter() - t0
    assert sample.shape == (20, emb.dim), sample.shape
    norms = np.linalg.norm(sample, axis=1)
    print(f'  차원 {sample.shape[1]} · 벡터 길이 {norms.min():.3f}~{norms.max():.3f} · 여는 데 {load_s:.1f}초'
          f' · 샘플 문장 20개 {sample_s:.2f}초')

    t0 = time.perf_counter()
    for x in questions[:10]:
        emb.embed_query(x)
    query_ms = (time.perf_counter() - t0) / 10 * 1000
    a = np.array(emb.embed_documents(answers))
    q = np.array(emb.embed_documents(questions))
    ranks = (-(q @ a.T)).argsort(axis=1)
    pos = np.array([list(r).index(i) for i, r in enumerate(ranks)])
    top1, top3, mrr = (pos == 0).mean(), (pos < 3).mean(), (1 / (pos + 1)).mean()
    print(f'  질문 1개 {query_ms:.0f}ms · FAQ {len(questions)}개 질문→답변 적중 Top1 {top1:.0%} · Top3 {top3:.0%}'
          f' · MRR {mrr:.3f}')

    chunk_note = ''
    if chunks:
        batch = chunks[:n_chunks]
        t0 = time.perf_counter()
        emb.embed_documents(batch)
        per = (time.perf_counter() - t0) / len(batch)
        chunk_note = f'{per:.2f}초/청크 → 전체 {len(chunks)}개 약 {per * len(chunks) / 60:.1f}분'
        print(f'  가이드 청크 {len(batch)}개: {chunk_note}')
    peak = rss_mb()
    if before is not None:
        print(f'  메모리 {before:.0f}MB → 연 뒤 {after:.0f}MB → 시험 뒤 {peak:.0f}MB')
    print('RESULT ' + json.dumps({'key': k, 'load_s': load_s, 'query_ms': query_ms, 'top1': float(top1),
                                  'top3': float(top3), 'mrr': float(mrr), 'peak_mb': peak,
                                  'chunk_note': chunk_note}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='임베딩 모델 받기·확인·시험 (M3-1-2)')
    ap.add_argument('command', choices=['check', 'download', 'smoke', 'smoke-one'])
    ap.add_argument('--model', choices=list(MODELS), help='한 모델만 (기본: 둘 다)')
    ap.add_argument('--chunks', type=int, default=64, help='smoke: 속도를 잴 가이드 청크 수 (0이면 생략)')
    args = ap.parse_args()
    keys = [args.model] if args.model else list(MODELS)
    if args.command == 'check':
        return cmd_check(keys)
    if args.command == 'download':
        return cmd_download(keys)
    if args.command == 'smoke-one':                            # smoke 가 모델마다 띄우는 하위 명령
        return cmd_smoke_one(keys[0], args.chunks)
    return cmd_smoke(keys, args.chunks)


if __name__ == '__main__':
    sys.exit(main())
