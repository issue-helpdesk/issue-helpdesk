"""내용 점검
  1. 정답셋(eval_inquiries) 문장이 가이드에 들어갔는지: 문의이력·FAQ에 없는 10자 이상 일치
  2. 시연·가상 표시 문구, 미확정 표시가 남았는지
"""
import csv
import json
import os
import re

from model import *

DATA = os.path.join(os.path.dirname(ROOT), 'data')


def squash(s):
    return re.sub(r'[\s\W_]+', '', s)


corpus = {}
for p_ in all_sources():
    d = load(p_)
    corpus[d['meta']['doc_no']] = squash(json.dumps(d, ensure_ascii=False))

allowed = ''
for r in csv.DictReader(open(os.path.join(DATA, 'history.csv'), encoding='utf-8-sig')):
    allowed += squash(r['title'] + r['description'] + r['resolution']) + '|'
for r in csv.DictReader(open(os.path.join(DATA, 'faq.csv'), encoding='utf-8-sig')):
    allowed += squash(r['question'] + r['answer']) + '|'

hits = set()
for r in csv.DictReader(open(os.path.join(DATA, 'eval_inquiries.csv'), encoding='utf-8-sig')):
    q = squash(r['query'])
    for i in range(len(q) - 9):
        w = q[i:i + 10]
        if w in allowed:
            continue
        for no, text in corpus.items():
            if w in text:
                hits.add((r['eval_id'], no, w))
for h_ in sorted(hits):
    print('정답셋 일치', *h_)

BAN = ['가상', '교육용', '교육 프로젝트', '화면 예시', '예시 화면', '회의 후 확정', '확인 필요]', '가칭', 'WIP', 'OPS', 'hangyeol', '시연']
for p_ in all_sources():
    d = load(p_)
    s = json.dumps(d, ensure_ascii=False)
    for b in BAN:
        for m in re.finditer(re.escape(b), s):
            print('금지 문구', d['meta']['doc_no'], b, s[max(0, m.start() - 30):m.end() + 20].replace('\n', ' '))
print('done')
