"""파싱 결과 확인용 명령.

    cd backend
    python -m app.rag.parser <파일 또는 폴더> [...] [--out 결과폴더] [--json]

파일마다 요약(제목 수·표·그림·요소 수·문서 번호)을 출력하고, --out 을 주면 <이름>.<형식>.md 미리보기
(--json 이면 .json 도)를 저장한다. 한 파일이 실패해도 나머지는 계속한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import logging

from . import SUPPORTED, ParseError, parse


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith(SUPPORTED) and not f.startswith('~$') and f.lower() != 'readme.md':
                        yield os.path.join(root, f)
        else:
            yield p


def summary(doc, ms: int) -> str:
    levels = [sum(1 for e in doc.headings() if e.level == i) for i in range(4)]
    n_table = len(doc.tables())
    n_image = sum(1 for e in doc.elements if e.kind == 'image')
    q = doc.quality
    text = (f"{doc.format} 제목 L0-3={levels} 표={n_table} 그림={n_image} 요소={len(doc.elements)} "
            f"문서번호={doc.meta.get('doc_no', '-')} 모드={q.get('mode', '-')} 포함률={q.get('coverage', 0):.3f} {ms}ms")
    return text + (f" ⚠ {'; '.join(doc.warnings)}" if doc.warnings else '')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.parser')
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--out', help='미리보기를 저장할 폴더')
    ap.add_argument('--json', action='store_true', help='JSON 도 저장')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    used: set[str] = set()
    failed = 0
    for path in iter_files(a.paths):
        name = os.path.basename(path)
        t0 = time.time()
        try:
            doc = parse(path)
        except ParseError as ex:
            print(f'[ERROR] {name}: {ex}')
            failed += 1
            continue
        print(f'[ok] {name}: {summary(doc, int((time.time() - t0) * 1000))}')
        if a.out:
            stem = os.path.splitext(name)[0] + '.' + doc.format
            base, n = os.path.join(a.out, stem), 2
            while base in used:            # 같은 이름이 다른 폴더에 있으면 번호를 붙인다
                base, n = os.path.join(a.out, f'{stem}.{n}'), n + 1
            used.add(base)
            with open(base + '.md', 'w', encoding='utf-8') as f:
                f.write(doc.to_markdown())
            if a.json:
                with open(base + '.json', 'w', encoding='utf-8') as f:
                    json.dump(doc.to_dict(), f, ensure_ascii=False, indent=1)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
