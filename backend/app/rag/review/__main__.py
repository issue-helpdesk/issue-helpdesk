"""가이드 검증 명령 (저장소의 backend 폴더에서).

    python -m app.rag.review sheet IT-ACC-001 IT-ACS-001 --name D1     # D1_검증시트.md + D1_질문.csv
    python -m app.rag.review sheet --category ACC --name ACC           # 분류 하나 전체
    python -m app.rag.review check ../dataset/guide_review/D1_질문.csv  # 질문 점검 (오류가 있으면 종료 코드 1)

결과는 dataset/guide_review/ 에 쓴다. 이미 있는 파일은 덮어쓰지 않는다 (--force 는 시트만 새로 만든다).
check 는 같은 이름의 검증 시트에 있는 문서를 대상으로 본다 (양식에서 행을 지워도 빠지지 않게).
"""
import argparse
import json
import logging
import os
import re
import sys

from . import (BASELINE, OUT, EvalSet, all_units, check_questions, load, load_manifest, question_template,
               read_questions, sheet, sheet_docs, write_questions)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.review')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sheet', help='검증 시트와 질문 양식을 만든다')
    s.add_argument('docs', nargs='*', help='문서 번호 (IT-ACC-001 …)')
    s.add_argument('--category', help='분류 하나 전체 (ACC …)')
    s.add_argument('--name', required=True, help='파일 이름 앞부분 (D1 …)')
    s.add_argument('--out', default=OUT)
    s.add_argument('--force', action='store_true', help='이미 있는 검증 시트를 새로 만든다 (적은 확인·문제 칸이 지워짐)')
    c = sub.add_parser('check', help='검색 질문 csv 를 점검한다')
    c.add_argument('csv')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    manifest = load_manifest()
    evalset = EvalSet()
    if a.cmd == 'sheet':
        docs = list(a.docs) + [d for d, e in manifest.items() if a.category and e['category'] == a.category]
        unknown = [d for d in docs if d not in manifest]
        if unknown or not docs:
            print(f'문서 번호를 확인하세요: {", ".join(unknown) or "(없음)"}')
            return 2
        docs = [d for d in dict.fromkeys(docs) if manifest[d].get('rag_target', True)]
        with open(BASELINE, encoding='utf-8') as f:
            base = json.load(f)['docs']
        reviews = [load(d, manifest) for d in docs]
        os.makedirs(a.out, exist_ok=True)
        sheet_path = os.path.join(a.out, f'{a.name}_검증시트.md')
        q_path = os.path.join(a.out, f'{a.name}_질문.csv')
        if os.path.exists(sheet_path) and not a.force:      # 사람이 채운 확인·문제 칸을 지키려고 덮어쓰지 않는다
            print(f'이미 있음 (그대로 둠): {sheet_path}\n  새로 만들려면 --force (적은 내용이 지워짐), 다른 이름은 --name')
        else:
            with open(sheet_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(sheet(reviews, a.name, evalset, base))
            print(sheet_path)
        if os.path.exists(q_path):                          # 질문은 --force 여도 덮어쓰지 않는다
            print(f'이미 있음 (그대로 둠): {q_path}')
        else:
            write_questions(q_path, question_template(reviews))
            print(q_path)
        print(f'문서 {len(reviews)}개')
        return 0

    sheet_file = re.sub(r'_질문\.csv$', '_검증시트.md', a.csv)
    targets = sheet_docs(sheet_file) if sheet_file != a.csv and os.path.exists(sheet_file) else None
    if targets is None:
        print(f'[경고] 같은 이름의 검증 시트가 없어 csv 의 문서 번호만 대상으로 봄: {sheet_file}')
    errors, warnings = check_questions(read_questions(a.csv), manifest, evalset, all_units(manifest), targets)
    for x in errors:
        print(f'[오류] {x}')
    for x in warnings:
        print(f'[경고] {x}')
    print(f'오류 {len(errors)} · 경고 {len(warnings)}')
    return 1 if errors else 0


raise SystemExit(main())
