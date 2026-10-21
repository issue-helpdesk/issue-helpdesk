"""원천 JSON → Markdown. 코드 저장소에서 읽고 RAG 등록에도 쓸 수 있게 문서 정보를 머리말(front matter)로 둔다."""
import os

from model import COMPANY, CATEGORIES

BADGE_MARK = {'사용자 직접 조치': '🟢', '신청·승인 후 처리': '🟡', 'IT 담당자 처리': '🔵', '즉시 신고·이관': '🔴'}


def esc(s):
    return str(s).replace('|', '\\|').replace('\n', '<br>')


def md_table(head, rows):
    out = []
    if head:
        out.append('| ' + ' | '.join(esc(h) for h in head) + ' |')
        out.append('|' + '|'.join(' --- ' for _ in head) + '|')
    else:
        n = len(rows[0])
        out.append('| ' + ' | '.join(' ' for _ in range(n)) + ' |')
        out.append('|' + '|'.join(' --- ' for _ in range(n)) + '|')
    for r in rows:
        out.append('| ' + ' | '.join(esc(c) for c in r) + ' |')
    return '\n'.join(out)


def yaml_val(v):
    if isinstance(v, list):
        return '[' + ', '.join(f'"{x}"' for x in v) + ']'
    return f'"{v}"' if v else '""'


class M:
    def __init__(self, doc, img_rel):
        self.doc, self.m, self.img_rel = doc, doc['meta'], img_rel
        self.out = []
        self.fig_sec, self.fig_no = '', 0

    def w(self, s=''):
        self.out.append(s)

    def front(self):
        m = self.m
        keys = [('doc_no', m['doc_no']), ('title', m['title']), ('category', m['category']),
                ('category_name', CATEGORIES.get(m['category'], '')), ('doc_type', m['doc_type']),
                ('doc_kind', m.get('doc_kind', '')), ('access_level', m['access']), ('audience', m.get('audience', '')),
                ('readers', m.get('readers', '')), ('version', m['version']), ('effective_date', m['date']),
                ('owner', m['owner']), ('approver', m.get('approver', '')), ('pair', m.get('pair', '')),
                ('scenarios', m.get('scenarios', [])), ('faqs', m.get('faqs', [])), ('keywords', m.get('keywords', []))]
        self.w('---')
        for k, v in keys:
            if v in ('', [], None) and k in ('readers', 'faqs', 'keywords', 'pair', 'approver'):
                continue
            self.w(f'{k}: {yaml_val(v)}')
        self.w('---')
        self.w()

    def item(self, it):
        t = it['t']
        if t == 'h':
            self.w(f"#### {it['text']}")
        elif t == 'p':
            self.w(it['text'])
        elif t == 'ul':
            for x in it['items']:
                self.w(f'- {x}')
        elif t == 'ol':
            for n, x in enumerate(it['items'], 1):
                self.w(f'{n}. {x}')
        elif t == 'table':
            rows = it['rows']
            bc = it.get('badge_col')
            if bc is not None:
                rows = [[(f"{BADGE_MARK.get(c, '')} {c}".strip() if j == bc else c) for j, c in enumerate(r)] for r in rows]
            self.w(md_table(it['head'], rows))
        elif t == 'kv':
            self.w(md_table(['항목', '내용'], it['rows']))
        elif t == 'qa':
            for q, a in it['items']:
                self.w(f'**Q. {q}**')
                self.w()
                self.w(f'A. {a}')
                self.w()
        elif t == 'cols':
            for c in it['cols']:
                self.w(f"**{c['title']}**")
                self.w()
                for x in c['items']:
                    self.w(f'- {x}')
                self.w()
        elif t == 'note':
            mark = '★' if it['kind'] == 'star' else '※'
            self.w(f"> {mark} **{it['title']}**")
            for ln in it.get('lines', []):
                self.w('>')
                self.w(f'> {ln}')
        elif t == 'quote':
            self.w(f"> {it['text']}")
        elif t == 'code':
            self.w('```')
            self.w(it['text'])
            self.w('```')
        elif t == 'flow':
            self.w(' → '.join(f"**STEP {n} {s['title']}**: {s['desc']}" for n, s in enumerate(it['steps'], 1)))
        elif t == 'fig':
            self.fig_no += 1
            label = f'{self.fig_sec}-{self.fig_no}' if self.fig_sec else str(self.fig_no)
            cap = f"그림 {label}. {it.get('caption', '')}".strip().rstrip('.')
            self.w(f"![{cap}]({self.img_rel}/{it['src']})")
            self.w()
            self.w(f'*{cap}*')
            side = ([it['step']] if it.get('step') else []) + list(it.get('points', []))
            if side or it.get('note'):
                self.w()
                for s in side:
                    self.w(f'- {s}')
                if it.get('note'):
                    self.w(f"- {it['note']}")
        self.w()

    def build(self):
        m = self.m
        self.front()
        self.w(f"# {m['title']}")
        self.w()
        from model import series as _series, RESTRICTED_NOTE
        series = _series(m)
        self.w(f"> {series}  ")
        self.w(f"> {m['doc_no']} | {m['owner']} | {m['date']} | {m['version']} | **{m['access']}** ({m.get('audience', '')})")
        if m['access'] != '사내 일반':
            self.w('>')
            self.w('> ' + RESTRICTED_NOTE.get(m['doc_type'], RESTRICTED_NOTE['manual']))
        self.w()
        self.w('## 목차')
        self.w()
        for ch in self.doc['chapters']:
            label = f"{ch['no']}. {ch['title']}" if ch['no'].isdigit() else f"{ch['no']} · {ch['title']}"
            self.w(f'- {label}')
            for s in ch['sections']:
                self.w(f"  - {s['no']} {s['title']}")
        self.w('- 개정 이력')
        self.w()
        for ch in self.doc['chapters']:
            label = f"{ch['no']}. {ch['title']}" if ch['no'].isdigit() else f"{ch['no']} · {ch['title']}"
            self.w(f'## {label}')
            self.w()
            self.fig_sec, self.fig_no = (ch['no'] if ch['no'].isdigit() else ''), 0
            for it in ch['items']:
                self.item(it)
            for s in ch['sections']:
                self.fig_sec, self.fig_no = s['no'], 0
                self.w(f"### {s['no']} {s['title']}")
                self.w()
                if s.get('props'):
                    self.w(' · '.join(f"**{k}** {BADGE_MARK.get(v, '')} {v}".replace('  ', ' ') for k, v in s['props']))
                    self.w()
                for it in s['items']:
                    self.item(it)
        self.w('## 개정 이력')
        self.w()
        self.w(md_table(['버전', '개정일', '작성자', '변경 내용'], m['history']))
        self.w()
        return '\n'.join(self.out).rstrip() + '\n'


def render(doc, img_dir, path):
    rel = os.path.relpath(img_dir, os.path.dirname(path)).replace(os.sep, '/')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(M(doc, rel).build())
