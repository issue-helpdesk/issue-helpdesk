"""HW·NET·SYS 원본 docx(dataset/guides/{HW,NET,SYS})를 공통 모델로 옮긴다.

한 번만 실행하는 변환 스크립트다. docx의 제목 스타일(Heading1·2·3)과 표·그림 순서를 그대로 따라간다.
"""
import glob
import os
import re

import docx
from docx.oxml.ns import qn

from model import *

SRC_ROOT = os.path.join(os.path.dirname(ROOT), 'guides')
ACTOR_MAP = {'신청 후 처리': APPLY}
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
# 사용자 화면을 그대로 되풀이한 매뉴얼 소절. 짝이 되는 가이드에 같은 그림이 있으므로 옮기지 않는다.
DROP_H3 = {'사용자 화면 (안내용)'}
PAIR_COLS = [('해결 확인', '해결되지 않으면', '문의 시 알려 주실 정보'),
             ('접수 시 확인 질문', '판단 기준'),
             ('재발 방지', '이관 시 전달 정보')]


def style_of(el):
    ps = el.find(qn('w:pPr'))
    if ps is None:
        return '-', None
    st = ps.find(qn('w:pStyle'))
    num = ps.find(qn('w:numPr'))
    numid = None
    if num is not None and num.find(qn('w:numId')) is not None:
        numid = num.find(qn('w:numId')).get(qn('w:val'))
    return (st.get(qn('w:val')) if st is not None else '-'), numid


def text_of(el):
    out = []
    for r in el.iter(qn('w:r')):
        bold = r.find(qn('w:rPr')) is not None and r.find(qn('w:rPr')).find(qn('w:b')) is not None
        t = ''.join(x.text or '' for x in r.iter(qn('w:t')))
        if not t:
            continue
        out.append(t)
    s = ''.join(out).replace('****', '')
    return re.sub(r'\s+', ' ', s).strip()


def numfmt_map(d):
    """numId -> 'ol' | 'ul'"""
    res = {}
    try:
        numbering = d.part.numbering_part.element
    except Exception:
        return res
    absfmt = {}
    for a in numbering.findall(qn('w:abstractNum')):
        lvl = a.find(qn('w:lvl'))
        fmt = lvl.find(qn('w:numFmt')).get(qn('w:val')) if lvl is not None and lvl.find(qn('w:numFmt')) is not None else 'bullet'
        absfmt[a.get(qn('w:abstractNumId'))] = fmt
    for n in numbering.findall(qn('w:num')):
        aid = n.find(qn('w:abstractNumId')).get(qn('w:val'))
        res[n.get(qn('w:numId'))] = 'ul' if absfmt.get(aid, 'bullet') == 'bullet' else 'ol'
    return res


def cell_shaded(c):
    tcpr = c._tc.find(qn('w:tcPr'))
    if tcpr is None:
        return False
    shd = tcpr.find(qn('w:shd'))
    return shd is not None and shd.get(qn('w:fill')) not in (None, 'auto', 'FFFFFF', 'ffffff')


def table_rows(t):
    rows = []
    for r in t.rows:
        cells, last = [], None
        for c in r.cells:
            if c._tc is last:
                continue
            last = c._tc
            cells.append('\n'.join(text_of(p._p) for p in c.paragraphs if text_of(p._p)))
        rows.append(cells)
    return rows


class Ctx:
    def __init__(self, path, cat):
        self.path, self.cat = path, cat
        self.d = docx.Document(path)
        self.nf = numfmt_map(self.d)
        self.img_n = 0
        self.doc_no = None

    def save_image(self, rid):
        part = self.d.part.related_parts[rid]
        ext = os.path.splitext(part.partname)[1].lower() or '.png'
        self.img_n += 1
        name = f'{self.doc_no}_{self.img_n:02d}{ext}'
        out = os.path.join(ROOT, self.cat, 'images')
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'wb') as f:
            f.write(part.blob)
        return name


def elements(ctx):
    """본문 요소를 (종류, 값) 순서로 낸다."""
    for el in ctx.d.element.body.iterchildren():
        tag = el.tag.split('}')[1]
        if tag == 'p':
            st, numid = style_of(el)
            imgs = [b.get(qn('r:embed')) for b in el.iter(qn('a:blip'))]
            for rid in imgs:
                yield 'img', rid
            t = text_of(el)
            if st == 'Title':
                yield 'title', t
            elif st.startswith('Heading'):
                yield 'h' + st[-1], t
            elif numid:
                yield ctx.nf.get(numid, 'ul'), t
            elif t:
                yield 'p', t
        elif tag == 'tbl':
            imgs = [b.get(qn('r:embed')) for b in el.iter(qn('a:blip'))]
            if imgs:
                for rid in imgs:
                    yield 'img', rid
                continue
            t = docx.table.Table(el, ctx.d)
            head = all(cell_shaded(c) for c in t.rows[0].cells)
            yield 'table', (table_rows(t), head)


def build_items(raw, ctx):
    """(종류, 값) 목록을 모델 items 로 바꾼다."""
    items = []
    i = 0
    while i < len(raw):
        k, v = raw[i]
        if k in ('ul', 'ol'):
            lst = [v]
            while i + 1 < len(raw) and raw[i + 1][0] == k:
                i += 1
                lst.append(raw[i][1])
            items.append({'t': k, 'items': lst})
        elif k == 'h3':
            items.append(h(v))
        elif k == 'table':
            rows, head = v
            if head and len(rows) > 1:
                items.append(table(rows[0], rows[1:]))
            elif len(rows[0]) == 2:
                items.append(kv(rows))
            elif len(rows[0]) % 2 == 0 and len(rows) == 1:
                r = rows[0]
                items.append(kv([[r[j], r[j + 1]] for j in range(0, len(r), 2)]))
            else:
                items.append(table(rows[0], rows[1:]))
        elif k == 'img':
            f = fig(ctx.save_image(v))
            # 뒤따르는 그림 설명·번호 설명·확인 문구를 그림에 붙인다
            j = i + 1
            if j < len(raw) and raw[j][0] == 'p' and raw[j][1].startswith('그림'):
                f['caption'] = strip_caption_no(raw[j][1])
                j += 1
            pts, notes = [], []
            while j < len(raw) and raw[j][0] == 'p' and (raw[j][1][:1] in CIRCLED or re.match(r'^(확인|주의|※)\s*:?', raw[j][1])):
                if raw[j][1][:1] in CIRCLED:
                    pts.append(raw[j][1])
                else:
                    notes.append(raw[j][1])
                j += 1
            if pts:
                f['points'] = pts
            if notes:
                f['note'] = ' '.join(notes)
            items.append(f)
            i = j - 1
        elif k == 'p':
            m = re.match(r'^화면\s*\d+/\d+\s*·\s*(.*)$', v)
            if m:
                # 다음 그림의 단계 제목
                if i + 1 < len(raw) and raw[i + 1][0] == 'img':
                    items.append({'t': '_step', 'text': m.group(1)})
                i += 1
                continue
            items.append(p(v))
        i += 1
    # 단계 제목을 그림에 합친다
    out = []
    for it in items:
        if out and out[-1].get('t') == '_step' and it.get('t') == 'fig':
            it['step'] = out.pop()['text']
        out.append(it)
    out = [it for it in out if it.get('t') != '_step']
    return pair_cols(out)


def pair_cols(items):
    """'해결 확인/해결되지 않으면/문의 시 알려 주실 정보' 같은 연속 소절을 카드 묶음으로 합친다."""
    out, i = [], 0
    while i < len(items):
        done = False
        for names in PAIR_COLS:
            n = len(names)
            seq = items[i:i + 2 * n]
            if len(seq) == 2 * n and all(seq[2 * j].get('t') == 'h' and seq[2 * j]['text'] == names[j] for j in range(n)):
                body = [seq[2 * j + 1] for j in range(n)]
                if all(b['t'] in ('ul', 'ol', 'p') for b in body):
                    out.append({'t': 'cols', 'cols': [{'title': names[j], 'items': body[j]['items'] if body[j]['t'] != 'p' else [body[j]['text']]} for j in range(n)]})
                    i += 2 * n
                    done = True
                    break
        if not done:
            out.append(items[i])
            i += 1
    return out


def drop_subsections(raw):
    out, skip = [], False
    for k, v in raw:
        if k in ('h1', 'h2'):
            skip = False
        if k == 'h3':
            skip = v in DROP_H3
        if not skip:
            out.append((k, v))
    return out


def faq_items(items):
    qs, cur = [], None
    rest = []
    for it in items:
        if it['t'] == 'p' and it['text'].startswith('Q.'):
            cur = [it['text'][2:].strip(), '']
            qs.append(cur)
        elif it['t'] == 'p' and it['text'].startswith('A.') and cur:
            cur[1] = it['text'][2:].strip()
        else:
            rest.append(it)
    return ([qa(qs)] if qs else []) + rest


def related_items(items):
    out = []
    for it in items:
        if it['t'] in ('ul', 'ol') and all(re.match(r'^IT-[A-Z]+-\d+', x) for x in it['items']):
            rows = []
            for x in it['items']:
                m = re.match(r'^(IT-[A-Z]+-\d+(?:-M)?)\s+(.*)$', x)
                rows.append([m.group(1), m.group(2), ''])
            out.append(table(['문서 번호', '문서명', '이럴 때 봅니다'], rows, [2, 4.5, 5.5]))
        else:
            out.append(it)
    return out


def convert(path, cat):
    ctx = Ctx(path, cat)
    raw = list(elements(ctx))
    title = next(v for k, v in raw if k == 'title')
    head_line = next(v for k, v in raw if k == 'p' and re.match(r'^IT-', v.replace('*', '')))
    ctx.doc_no = head_line.replace('*', '').split()[0]
    title = title.replace('*', '')
    is_manual = ctx.doc_no.endswith('-M')
    # 문서 정보 표
    info = {}
    first_h1 = next(i for i, (k, _) in enumerate(raw) if k == 'h1')
    for k, v in raw[:first_h1]:
        if k == 'table':
            for r in v[0]:
                for j in range(0, len(r) - 1, 2):
                    info[r[j]] = r[j + 1]
    raw = drop_subsections(raw[first_h1:])
    chapters, cur_ch, cur_sec, buf = [], None, None, []

    def flush():
        nonlocal buf
        items = build_items(buf, ctx)
        buf = []
        if cur_sec is not None:
            props = []
            if items and items[0]['t'] == 'kv':
                props = items.pop(0)['rows']
            cur_sec['props'] = props
            cur_sec['items'] = items
        elif cur_ch is not None:
            cur_ch['items'] = items

    for k, v in raw:
        if k == 'h1':
            flush()
            cur_sec = None
            m = re.match(r'^(\d+)\.\s*(.*)$', v)
            cur_ch = chapter(m.group(1), m.group(2)) if m else chapter('부록', '관련 문서 · 용어 · 개정 이력' if v == '부록' else v)
            chapters.append(cur_ch)
        elif k == 'h2':
            flush()
            m = re.match(r'^(\d+\.\d+)\s+(.*)$', v)
            cur_sec = section(m.group(1), m.group(2), [], [])
            cur_ch['sections'].append(cur_sec)
        else:
            buf.append((k, v))
    flush()

    hist = []
    for ch in chapters:
        if '자주 묻는 질문' in ch['title']:
            ch['items'] = faq_items(ch['items'])
        if ch['no'] == '부록':
            ch['items'] = related_items(ch['items'])
            # 개정 이력은 meta 로 옮긴다
            keep = []
            skip_next = False
            for idx, it in enumerate(ch['items']):
                if it['t'] == 'h' and it['text'] == '개정 이력':
                    skip_next = True
                    continue
                if skip_next and it['t'] == 'table':
                    hist = it['rows']
                    skip_next = False
                    continue
                keep.append(it)
            ch['items'] = keep
        for s in ch['sections']:
            s['props'] = [[a, ACTOR_MAP.get(b, b) if a == '처리 주체' else b] for a, b in s['props']]
        # 목차 표의 처리 주체 값도 맞춘다
        for it in ch['items']:
            if it['t'] == 'table' and '처리 주체' in it['head']:
                c = it['head'].index('처리 주체')
                for r in it['rows']:
                    r[c] = ACTOR_MAP.get(r[c], r[c])

    def sl(s):
        return [x.strip() for x in s.split(',') if x.strip() and x.strip() != '-']

    meta = {
        'doc_no': ctx.doc_no, 'title': title, 'category': cat,
        'doc_type': 'manual' if is_manual else 'guide',
        'access': ACCESS_RESTRICTED if is_manual else ACCESS_PUBLIC,
        'owner': info.get('관리 부서', ''), 'approver': info.get('승인자', ''),
        'pair': info.get('대상 사용자 가이드' if is_manual else '담당자 매뉴얼', ''),
        'scenarios': sl(info.get('포함 시나리오', '')),
        'history': hist,
    }
    if is_manual:
        meta['readers'] = info.get('열람 대상', '')
        meta['faqs'] = sl(info.get('관련 FAQ', ''))
    else:
        meta['doc_kind'] = info.get('문서 유형', '')
        meta['target'] = info.get('대상', '전 임직원')
        meta['keywords'] = sl(info.get('키워드', ''))
    return {'meta': meta, 'chapters': chapters}


def main():
    for cat in ['HW', 'NET', 'SYS']:
        for f in sorted(glob.glob(os.path.join(SRC_ROOT, cat, '*', '*.docx'))):
            doc = convert(f, cat)
            print(save(doc), len(doc['chapters']), sum(len(c['sections']) for c in doc['chapters']))


if __name__ == '__main__':
    main()
