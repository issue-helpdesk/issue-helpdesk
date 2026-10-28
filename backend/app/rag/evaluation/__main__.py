"""검색 평가 명령 (저장소의 backend 폴더에서).

    uv run python -m app.rag.evaluation                                         # BM25 기준선 (DB·모델 없이)
    uv run python -m app.rag.evaluation --retriever search:bge-m3 --database-url <DB>   # 실제 검색 기능 search() 로 (챗봇 경로)
    uv run python -m app.rag.evaluation --retriever db:bge-m3 --database-url <DB>       # 적재된 벡터만 읽어 순위 (묶기는 평가 쪽에서)
    uv run python -m app.rag.evaluation --role EMPLOYEE                         # 직원 권한 (매뉴얼 제외)

search: · db: 는 uv sync --extra embedding 이 필요하다.

DB는 읽기만 한다. 주소는 --database-url 로만 받고 .env 는 읽지 않는다.
결과는 작업대/평가결과/<날짜시각>_<검색기>_<역할>/ 에 질문별.csv · 요약.md · 요약.json.
"""
import argparse
import glob
import logging
import os
import sys
from datetime import datetime

from . import (EVAL_CSV, MRR_K, OUT, QUESTIONS_DIR, TAXONOMY, BM25Retriever, SearchApiRetriever, VectorRetriever,
               code_fingerprint,
               corpus_units, db_vector_rows, evaluate, file_hash, git_state, load_eval_set, load_guide_questions,
               new_run_dir, restrict_to_role, summary_md, units_fingerprint, write_results)


def make_retriever(name: str, units, role: str, database_url: str | None):
    if name == 'bm25':
        from . import ROLE_SCOPES
        return BM25Retriever([u for u in units if u.view_scope in ROLE_SCOPES[role]])
    if name.startswith('search:'):
        if not database_url:
            raise SystemExit(f'{name} 은 --database-url 이 필요합니다')
        from ..embedding import Embedder
        return SearchApiRetriever(database_url, Embedder(name[7:]), role)
    if name.startswith('db:'):
        if not database_url:
            raise SystemExit(f'{name} 은 --database-url 이 필요합니다')
        from ..embedding import Embedder
        emb = Embedder(name[3:])
        rows, dup_key = db_vector_rows(database_url, emb.model_id, role)
        r = VectorRetriever(f'{name} ({emb.model_id})', rows, emb.embed_query, dup_key)
        print(f'  {emb.model_id}: 청크 벡터 {len(rows)}개')
        return r
    raise SystemExit(f'모르는 검색기: {name} (bm25 · search:<모델> · db:<모델>, 모델은 bge-m3 · kure-v1)')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.evaluation')
    ap.add_argument('--retriever', default='bm25', help='쉼표로 여럿: bm25, search:bge-m3 (실제 검색), db:bge-m3 (벡터만)')
    ap.add_argument('--database-url', help='search: · db: 검색기용 (읽기 전용)')
    ap.add_argument('--role', default='AGENT', choices=('EMPLOYEE', 'AGENT', 'ADMIN'))
    ap.add_argument('--sets', default='guide,eval', help='guide(가이드 검색 질문) · eval(평가셋)')
    ap.add_argument('--questions', default=QUESTIONS_DIR)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    units = corpus_units()
    sets = a.sets.split(',')
    questions, notes = [], {}
    if 'guide' in sets:
        guide, dropped = restrict_to_role(load_guide_questions(units, a.questions), units, a.role)
        questions += guide
        notes['가이드 질문'] = f'{len(guide)}개' + (f' (역할 {a.role}이 볼 수 없는 문서 정답 {len(dropped)}개 제외)' if dropped else '')
    if 'eval' in sets:
        ev, skipped = load_eval_set(units=units)
        ev, dropped = restrict_to_role(ev, units, a.role)
        questions += ev
        notes['평가셋'] = f'{len(ev)}개 (시나리오 없음 {len(skipped)}개 제외: {", ".join(skipped)})' + \
            (f' (역할 {a.role}이 볼 수 없는 문서 정답 {len(dropped)}개 제외)' if dropped else '')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name in a.retriever.split(','):
        r = make_retriever(name.strip(), units, a.role, a.database_url)
        results = evaluate(r, questions, MRR_K)
        meta = {'retriever': r.name, '역할': a.role, '실행': stamp, 'git': git_state(), '코드 지문': code_fingerprint(),
                '단위 지문': units_fingerprint(units), '같은 본문 묶기': '본문·전송 정책이 같으면 하나로 (8장 3번)',
                '질문 파일': f"{file_hash(glob.glob(os.path.join(a.questions, '*_질문.csv')))} ({a.questions})",
                '평가셋 파일': file_hash([EVAL_CSV, TAXONOMY]), **notes}
        out_dir = new_run_dir(a.out, f"{stamp}_{name.strip().replace(':', '-')}_{a.role}")
        summary = write_results(out_dir, results, meta)
        print(summary_md(summary))
        print(f'→ {out_dir}')
    return 0


raise SystemExit(main())
