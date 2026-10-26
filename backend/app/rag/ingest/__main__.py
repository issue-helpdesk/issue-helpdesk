"""python -m app.rag.ingest — 가이드 적재. 사용법은 README.md.

    python -m app.rag.ingest --embedder fake                               # 검증까지만 (DB 없이)
    python -m app.rag.ingest --embedder fake --database-url <임시 DB>       # 임시 DB에 적재
    python -m app.rag.ingest --models kure-v1,bge-m3 --database-url <임시 DB>
"""
import argparse
import sys
import time

from app.rag.embedding import MODELS
from app.rag.ingest import FakeEmbedder, IngestError, connect, drop_model, is_local, run, summary

ACTIONS = {'new': '새 버전', 'reloaded': '다시 적재', 'unchanged': '변화 없음', 'failed': '실패'}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.ingest')
    ap.add_argument('--database-url', help='적재할 DB. 없으면 검증까지만 한다 (.env 는 읽지 않는다)')
    ap.add_argument('--allow-remote', action='store_true', help='localhost 가 아닌 DB(공유 DB)에 쓸 때 꼭 준다')
    ap.add_argument('--dry-run', action='store_true', help='DB 를 주어도 읽기만 하고 쓰지 않는다')
    ap.add_argument('--embedder', choices=('real', 'fake'), default='real', help='fake: 모델 파일 없이 시험용 벡터')
    ap.add_argument('--models', default='kure-v1,bge-m3', help=f'쉼표로 구분 ({", ".join(MODELS)})')
    ap.add_argument('--docs', help='이 문서만 (쉼표로 구분한 문서 번호)')
    ap.add_argument('--no-activate', action='store_true', help='DONE 까지만 하고 현행으로 바꾸지 않는다')
    ap.add_argument('--no-baseline', action='store_true', help='기준표 비교를 하지 않는다 (새 문서·청커 수정 확인용)')
    ap.add_argument('--force-activate', action='store_true',
                    help='다른 현행이 있어도 이번에 넣은 버전을 현행으로 (예: 실패했던 새 버전을 고쳐 다시 넣을 때)')
    ap.add_argument('--apply-policy', action='store_true', help='이미 있는 버전의 열람 범위·외부 전송 정책을 manifest 값으로 바꾼다')
    ap.add_argument('--drop-model', metavar='MODEL_ID', help='이 model 값의 임베딩을 지우고 끝낸다 (예: bge-m3@5617a9f/v1)')
    a = ap.parse_args(argv)

    url = a.database_url
    if url and not a.allow_remote and not is_local(url):
        print('localhost 가 아닌 DB 입니다 (?host=·hostaddr·PGHOST 포함). 공유 DB 에 쓰려면 --allow-remote 를 주세요.')
        return 2
    if a.drop_model:
        if not url or a.dry_run:
            print('--drop-model 은 --database-url 이 필요하다')
            return 2
        with connect(url, a.allow_remote) as conn:
            n = drop_model(conn, a.drop_model)
            conn.commit()
        print(f'{a.drop_model} 임베딩 {n}개 삭제')
        return 0

    keys = [k.strip() for k in a.models.split(',') if k.strip()]
    if not keys or len(set(keys)) != len(keys):
        print('--models 에 모델을 하나 이상, 겹치지 않게 주세요')
        return 2
    if unknown := set(keys) - set(MODELS):
        print(f'모르는 모델: {", ".join(sorted(unknown))}')
        return 2
    if a.embedder == 'fake':
        embedders = [FakeEmbedder(k) for k in keys]
    else:
        from app.rag.embedding import Embedder
        embedders = [_Lazy(k, Embedder) for k in keys]

    started = time.time()
    try:
        report = run(url, embedders, docs=a.docs.split(',') if a.docs else None, base=not a.no_baseline,
                     dry_run=a.dry_run, activate_version=not a.no_activate, allow_remote=a.allow_remote,
                     apply_policy=a.apply_policy, force_activate=a.force_activate)
    except IngestError as ex:
        print(f'[검증 실패] DB 에 쓰지 않았습니다. {len(ex.problems)}건')
        print('\n'.join(f'  {p}' for p in ex.problems))
        return 1

    for w in report.warnings:
        print(f'[경고] {w}')
    for mid, s in report.embedded.items():
        print(f'임베딩 {mid}: 새로 {s["new"]}, 다시 씀 {s["reused"]}')
    for r in report.results:
        extra = ''.join(f' · {x}' for x in (r.get('note'), r.get('error')) if x)
        extra += ''.join(f' · {m} 임베딩 {n}개 빠짐(다시 넣을 것)' for m, n in (r.get('dropped') or {}).items())
        if r['action'] != 'unchanged' or extra or r['activated']:
            print(f'  {r["doc"]} {r["version"]}: {ACTIONS[r["action"]]}{" · 현행 전환" if r["activated"] else ""}{extra}')
    counts = {k: sum(r['action'] == k for r in report.results) for k in ACTIONS}
    if url and not a.dry_run:
        print('문서 ' + ' · '.join(f'{ACTIONS[k]} {n}' for k, n in counts.items()))
        with connect(url, a.allow_remote) as conn:
            _print_summary(summary(conn))
    else:
        print('검증 통과 (DB 에 쓰지 않음)' + ('' if url else ', DB 검사(문의 유형 코드·관리 부서)는 건너뜀'))
    print(f'{time.time() - started:.0f}초')
    return 1 if counts['failed'] else 0


def _print_summary(rows) -> None:
    models = sorted({m for *_, emb in rows for m in emb})
    print('\n현행 버전 기준')
    print('| 분류 | 문서 | 청크 | ' + ' | '.join(models) + ' |')
    print('|---|---:|---:|' + '---:|' * len(models))
    for cat, nd, nc, emb in rows:
        print(f'| {cat} | {nd} | {nc} | ' + ' | '.join(str(emb.get(m, 0)) for m in models) + ' |')
    print(f'| 합계 | {sum(r[1] for r in rows)} | {sum(r[2] for r in rows)} | '
          + ' | '.join(str(sum(r[3].get(m, 0) for r in rows)) for m in models) + ' |')


class _Lazy:
    """진짜 모델은 실제로 임베딩할 글이 있을 때만 연다 (여는 데 10초·메모리 2~3GB). 다 다시 쓰면 열지 않는다."""

    def __init__(self, key, cls):
        from app.rag.embedding import model_id
        self.key, self._cls, self._emb = key, cls, None
        self.model_id = model_id(key)

    def embed_documents(self, texts):
        if self._emb is None:
            print(f'{self.key} 모델 여는 중… 청크 {len(texts)}개 임베딩', flush=True)
            self._emb = self._cls(self.key)
        out = self._emb.embed_documents(texts)
        self._emb = None                                   # 다음 모델을 열기 전에 메모리를 돌려준다
        return out


if __name__ == '__main__':
    sys.exit(main())
