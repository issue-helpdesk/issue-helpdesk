"""python -m app.rag.case_guide — 해결 사례 가이드화. 사용법은 README.md. 검토·승인 API·화면(A·F) 전까지 시연·검수용.

    python -m app.rag.case_guide --database-url <DB> candidates                         # 가이드화할 수 있는 CLS 티켓
    python -m app.rag.case_guide --database-url <DB> draft --ticket 12 --out case.md     # 초안 md + case.md.json (DB 에 안 씀)
    python -m app.rag.case_guide --database-url <DB> register --file case.md             # 고친 md 등록 + 적재 → DONE(초안)
    python -m app.rag.ingest ...                                                          # 승인(현행 전환)은 관리자가 따로

draft 는 초안을 만들 때의 기준(현행·이어 쓰던 초안·기준 md)을 <out>.json 에 같이 쓴다. register 는 그 기준으로 검사한다:
초안을 새로 만들지 않는다 (새로 만들면 고치는 동안 그새 들어간 사례를 오래된 md 가 지워도 못 잡는다).
"""
import argparse
import sys
from pathlib import Path

from app.rag.case_guide import CaseGuideError, Draft, candidates, draft, register
from app.rag.embedding import DEFAULT_MODEL, MODELS
from app.rag.ingest import ROOT, FakeEmbedder, connect, is_local


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.case_guide')
    ap.add_argument('--database-url', required=True, help='.env 는 읽지 않는다')
    ap.add_argument('--allow-remote', action='store_true', help='localhost 가 아닌 DB(공유 DB)에 쓸 때 꼭 준다')
    ap.add_argument('--files-root', type=Path, default=ROOT,
                    help='파일 저장 루트 (버전 file_path 의 기준). 기본은 저장소 루트, 사례 md 는 그 아래 storage/case_guides')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('candidates', help='가이드화할 수 있는 CLS 티켓')
    c.add_argument('--category', help='이 분류만 (SW 등)')
    d = sub.add_parser('draft', help='초안 md (DB 에 쓰지 않는다)')
    d.add_argument('--ticket', type=int, required=True, help='티켓 id')
    d.add_argument('--doc', help='넣을 가이드 문서 번호 (문의 유형이 없거나 여러 가이드가 다룰 때)')
    d.add_argument('--out', help='초안 md 를 쓸 파일 (초안 정보는 <out>.json). 없으면 화면에만 (등록은 못 함)')
    r = sub.add_parser('register', help='고친 md 등록 + 적재')
    r.add_argument('--file', required=True, help='관리자가 고친 md')
    r.add_argument('--draft', help='초안 정보 (기본 <file>.json, draft --out 이 만든 것)')
    r.add_argument('--admin-id', type=int, help='감사 로그에 남길 관리자 id')
    r.add_argument('--embedder', choices=('real', 'fake'), default='real', help='fake: 모델 파일 없이 시험용 벡터')
    r.add_argument('--model', default=DEFAULT_MODEL, choices=sorted(MODELS))
    a = ap.parse_args(argv)

    if not a.allow_remote and not is_local(a.database_url):
        print('localhost 가 아닌 DB 입니다. 공유 DB 에 쓰려면 --allow-remote 를 주세요.')
        return 2
    if a.cmd == 'register':
        info = Path(a.draft or f'{a.file}.json')
        if not info.exists():
            print(f'초안 정보 {info} 가 없습니다. draft --out 으로 만든 초안만 등록합니다')
            return 2
    try:
        with connect(a.database_url, a.allow_remote) as conn:
            if a.cmd == 'candidates':
                rows = candidates(conn, a.category)
                for x in rows:
                    print(f"  티켓 {x['ticket_id']} {x['receipt_no']} [{x['code'] or '유형 없음'}] → "
                          f"{x['doc_code'] or '가이드 없음 (--doc)'} · {x['summary']}")
                print(f'{len(rows)}건')
                return 0
            if a.cmd == 'draft':
                d = draft(conn, a.ticket, a.doc, a.files_root)
                if a.out:
                    Path(a.out).write_text(d.md, encoding='utf-8')
                    d.save(Path(f'{a.out}.json'))
                    print(f'{d.doc_code} {d.version} 초안 → {a.out} (새 항목 {d.section_no}, 초안 정보 {a.out}.json)')
                else:
                    print(d.md)
                _warn(d.warnings)
                return 0
            d = Draft.load(info)
            md = Path(a.file).read_text(encoding='utf-8')
            out = register(conn, d, md, a.admin_id, a.files_root)
            print(f"{d.doc_code} {d.version} 등록: 버전 {out['version_id']} · {out['file_path']}")
            _warn(out['warnings'])
            from app.rag.ingest.upload import ingest_version
            res = ingest_version(conn, out['version_id'], _embedder(a), a.files_root)
            print(f"  적재: {res['status']}" + (f" · 청크 {res['chunks']}" if res['chunks'] else '')
                  + (f" · {res['error']}" if res['error'] else ''))
            _warn(res['warnings'])
            if res['status'] == 'DONE':
                print('  승인(현행 전환) 전에는 검색에 나오지 않습니다')
            return 1 if res['status'] == 'FAILED' else 0
    except CaseGuideError as ex:
        print('[안 됨] ' + '\n[안 됨] '.join(ex.problems))
        return 1


def _warn(warnings: list[str]) -> None:
    for w in warnings:
        print(f'  [경고] {w}')


def _embedder(a):
    if a.embedder == 'fake':
        return FakeEmbedder(a.model)
    from app.rag.embedding import Embedder
    from app.rag.ingest.__main__ import _Lazy
    return _Lazy(a.model, Embedder)


if __name__ == '__main__':
    sys.exit(main())
