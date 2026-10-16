"""문서 사이 참조 점검: 없는 문서·없는 항목(3.x)·문서명 불일치를 찾는다."""
import json
import re
import sys

from model import *

docs = {}
secs = {}
for p_ in all_sources():
    d = load(p_)
    n = d['meta']['doc_no']
    docs[n] = d['meta']['title']
    secs[n] = {s['no'] for ch in d['chapters'] for s in ch['sections']}

REF = re.compile(r'(IT-[A-Z]+-\d{3}(?:-M)?)(?:\s+(\d+\.\d+))?')
problems = []
for p_ in all_sources():
    d = load(p_)
    me = d['meta']['doc_no']
    text = json.dumps(d['chapters'], ensure_ascii=False)
    for m in REF.finditer(text):
        n, s = m.group(1), m.group(2)
        if n not in docs:
            problems.append((me, 'no-doc', m.group(0)))
        elif s and s not in secs[n]:
            problems.append((me, 'no-section', m.group(0)))
    # 관련 문서 표의 문서명
    for ch in d['chapters']:
        for it in ch['items']:
            if it['t'] == 'table' and it['head'][:2] == ['문서 번호', '문서명']:
                for r in it['rows']:
                    if r[0] in docs and r[1] != docs[r[0]]:
                        problems.append((me, 'title', f'{r[0]}: "{r[1]}" → "{docs[r[0]]}"'))
for pr in sorted(set(problems)):
    print(*pr)
print(len(set(problems)), 'problems')
