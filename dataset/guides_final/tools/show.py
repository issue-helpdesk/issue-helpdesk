"""원천 JSON의 항목 하나를 사람이 읽기 좋게 출력한다.  python show.py IT-SYS-006 3.1"""
import sys
from model import *
import glob, os
def fmt(it):
    t = it['t']
    if t in ('h', 'p', 'quote', 'code'): return f"[{t}] {it['text']}"
    if t in ('ul', 'ol'): return f"[{t}] " + ' | '.join(it['items'])
    if t == 'cols': return '[cols] ' + ' || '.join(c['title'] + ': ' + ' | '.join(c['items']) for c in it['cols'])
    if t == 'note': return f"[note {it['kind']}] {it['title']} " + ' | '.join(it.get('lines', []))
    if t == 'fig': return f"[fig] {it['src']} {it.get('caption','')} {it.get('step','')} " + ' | '.join(it.get('points', []))
    if t in ('table', 'kv', 'qa'): return f"[{t}] " + str(it.get('head', '')) + ' ' + ' / '.join(' | '.join(map(str, r)) for r in (it.get('rows') or it.get('items')))
    return str(it)
doc = load(glob.glob(os.path.join(SOURCE, '*', sys.argv[1] + '.json'))[0])
want = sys.argv[2:] 
for ch in doc['chapters']:
    if not want or ch['no'] in want:
        print(f"## {ch['no']} {ch['title']}")
        for it in ch['items']: print('  ', fmt(it)[:600])
    for s in ch['sections']:
        if not want or s['no'] in want:
            print(f"### {s['no']} {s['title']} {s['props']}")
            for it in s['items']: print('  ', fmt(it)[:600])
