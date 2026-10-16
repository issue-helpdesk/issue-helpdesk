"""16:9 장표 레이아웃 엔진. PDF(render_pdf)와 PPTX(render_pptx)가 같은 결과를 그린다.

디자인 기준: IT-SW-001 업무용 SW 설치 가이드 (표지 → Contents → 장 구분 → 본문 장표).
좌표 단위는 pt, 원점은 왼쪽 위. 한 장 = 960 x 540.

결과는 Page 목록이고, 각 Page 는 그리기 요소(dict) 목록을 가진다.
  rect  {x,y,w,h,fill,stroke,lw,radius}
  line  {x1,y1,x2,y2,color,lw,dash}
  text  {x,y,w,lines:[[(글자,굵게,색)]],size,leading,align}
  image {x,y,w,h,path}
  table {x,y,w,cols:[폭],rows:[{h,cells:[{lines,fill,bold,color,size}]}]}   (PPTX는 표 개체로 만든다)
"""
import os
import re

from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = os.environ.get('GUIDE_FONT_DIR', r'C:\Windows\Fonts')
FONT, FONT_B = 'MalgunGothic', 'MalgunGothic-Bold'
FONT_FACE = 'Malgun Gothic'      # PPTX·DOCX 글꼴 이름
MONO = 'Consolas'
pdfmetrics.registerFont(TTFont(FONT, os.path.join(FONT_DIR, 'malgun.ttf')))
pdfmetrics.registerFont(TTFont(FONT_B, os.path.join(FONT_DIR, 'malgunbd.ttf')))
try:
    pdfmetrics.registerFont(TTFont('Mono', os.path.join(FONT_DIR, 'consola.ttf')))
    MONO_PDF = 'Mono'
except Exception:
    MONO_PDF = FONT

# 색 (IT-SW-001 기준)
BG = '#FAFAF9'
INK = '#1D2433'
MUTED = '#5A6270'
NAVY = '#1F3A5F'
DARK = '#1D293A'
ORANGE = '#E8590C'
SUB = '#B8430E'
LINE = '#DBD9D3'
CELL = '#FFFEFA'
KEY = '#ECEFF2'
GREEN = '#2E7D3A'
CODE_BG = '#1D2533'
CODE_FG = '#E3E8EF'
DIV_SUB = '#AEB6C2'
STAR_BG = '#FDF0E7'
STAR_LINE = '#F2C4A6'
INFO_BG = '#EEF1F4'
WHITE = '#FFFFFF'
BADGE = {
    '사용자 직접 조치': ('#E5F2E7', '#2E7D3A'),
    '신청·승인 후 처리': ('#FDF3D8', '#8A5A00'),
    'IT 담당자 처리': ('#E3EAF3', '#1F3A5F'),
    '즉시 신고·이관': ('#FBE3DC', '#B8430E'),
}

W, H = 960, 540
ML, MR = 46, 46
CW = W - ML - MR
TOP = 92          # 본문 시작
BOTTOM = 498      # 본문 끝
GAP = 9

S_BODY = 11.5
S_SMALL = 10
S_TABLE = 10
S_H = 13.5
S_TITLE = 22
LEAD = 1.42


def sw(s, size, bold=False):
    return pdfmetrics.stringWidth(s, FONT_B if bold else FONT, size)


# ---------------------------------------------------------------- 글자 처리
def runs(text, color=INK, bold=False):
    """'**굵게**' 표시를 (글자, 굵게, 색) 묶음으로 나눈다."""
    out = []
    parts = re.split(r'(\*\*.+?\*\*)', text or '')
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            out.append((part[2:-2], True, color))
        else:
            out.append((part, bold, color))
    return out


def plain(text):
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text or '')


def wrap(rs, width, size):
    """묶음 목록을 폭에 맞게 줄로 나눈다. 띄어쓰기 단위로 끊고, 긴 낱말은 글자 단위로 끊는다."""
    # 낱말 단위 토큰: (글자, 굵게, 색)
    tokens = []
    for t, b, c in rs:
        for piece in re.findall(r'\S+|\s+', t.replace('\n', ' \n ')):
            tokens.append((piece, b, c))
    lines, cur, cw = [], [], 0.0

    def push_line():
        nonlocal cur, cw
        while cur and not cur[-1][0].strip():
            cur.pop()
        lines.append(cur)
        cur, cw = [], 0.0

    for t, b, c in tokens:
        if t == '\n':
            push_line()
            continue
        if not t.strip():
            if cur:
                wsp = sw(' ', size, b)
                cur.append((' ', b, c))
                cw += wsp
            continue
        tw = sw(t, size, b)
        if cw + tw <= width + 0.01:
            cur.append((t, b, c))
            cw += tw
            continue
        if tw <= width and cur:
            push_line()
            cur.append((t, b, c))
            cw = tw
            continue
        # 글자 단위로 끊기
        for ch in t:
            chw = sw(ch, size, b)
            if cw + chw > width + 0.01 and cur:
                push_line()
            cur.append((ch, b, c))
            cw += chw
    if cur or not lines:
        push_line()
    # 같은 스타일 묶기
    merged = []
    for ln in lines:
        m = []
        for t, b, c in ln:
            if m and m[-1][1] == b and m[-1][2] == c:
                m[-1] = (m[-1][0] + t, b, c)
            else:
                m.append((t, b, c))
        merged.append(m)
    return merged


def text_h(nlines, size, lead=LEAD):
    return nlines * size * lead


def T(x, y, w, lines, size, align='left', lead=LEAD):
    return {'k': 'text', 'x': x, 'y': y, 'w': w, 'lines': lines, 'size': size, 'leading': size * lead, 'align': align}


def R(x, y, w, h, fill=None, stroke=None, lw=0.8, radius=0):
    return {'k': 'rect', 'x': x, 'y': y, 'w': w, 'h': h, 'fill': fill, 'stroke': stroke, 'lw': lw, 'radius': radius}


def L(x1, y1, x2, y2, color=LINE, lw=0.8, dash=None):
    return {'k': 'line', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'color': color, 'lw': lw, 'dash': dash}


# ---------------------------------------------------------------- 페이지
class Page:
    def __init__(self, kind, title='', tag='', bg=BG):
        self.kind, self.title, self.tag, self.bg = kind, title, tag, bg
        self.els = []
        self.bookmark = None     # (단계, 제목)
        self.bookmarks = []

    def add(self, *els):
        self.els.extend(els)


class Doc:
    def __init__(self, doc, img_dir):
        self.doc = doc
        self.meta = doc['meta']
        self.img_dir = img_dir
        self.pages = []
        self.toc = []         # (장 번호, 제목, 쪽 번호)

    @property
    def footer_left(self):
        from model import COPYRIGHT
        return f"{COPYRIGHT} · {self.meta['doc_no']} · {self.meta['access']}"


def frame(page, d):
    """본문 장표의 머리·꼬리를 그린다 (쪽 번호는 마지막에 채운다)."""
    page.add(R(0, 0, W, H, fill=page.bg))
    title_lines = wrap(runs(page.title, INK, True), CW - 210, S_TITLE)
    size = S_TITLE if len(title_lines) == 1 else 17
    title_lines = wrap(runs(page.title, INK, True), CW - 210, size)[:2]
    ty = 52 - text_h(len(title_lines), size, 1.25) + size * 0.9
    page.add(T(ML, ty, CW - 200, title_lines, size, lead=1.25))
    if page.tag:
        page.add(T(W - MR - 220, 50, 220, [[(page.tag, True, NAVY)]], 10, align='right'))
    page.add(L(ML, 74, W - MR, 74, NAVY, 1.6))


def footer(page, d, n, total):
    color = DIV_SUB if page.kind == 'divider' else MUTED
    page.add(T(ML, 512, 500, [[(d.footer_left, False, color)]], 8.5))
    page.add(T(W - MR - 100, 512, 100, [[(f'{n} / {total}', False, color)]], 8.5, align='right'))


# ---------------------------------------------------------------- 블록 측정·그리기
class Flow:
    """한 장표 안에서 위에서 아래로 쌓는다. 자리가 모자라면 새 장표를 만든다."""

    def __init__(self, d, title, tag, bookmark=None):
        self.d, self.title, self.tag = d, title, tag
        self.page = None
        self.y = TOP
        self.first_bookmark = bookmark
        self.new_page()
        self.start_no = len(d.pages)

    def new_page(self, cont=False):
        title = self.title + (' (계속)' if cont else '')
        self.page = Page('content', title, self.tag)
        frame(self.page, self.d)
        if self.first_bookmark and not cont:
            self.page.bookmarks.append(self.first_bookmark)
        self.d.pages.append(self.page)
        self.y = TOP

    def room(self):
        return BOTTOM - self.y

    def need(self, h):
        if h > self.room() and self.y > TOP + 1:
            self.new_page(cont=True)

    def add_gap(self, g=GAP):
        self.y += g

    # ---- 기본 글
    def heading(self, text):
        lines = wrap(runs(text, SUB, True), CW, S_H)
        h = text_h(len(lines), S_H, 1.3)
        self.need(h + 75)
        self.page.add(T(ML, self.y, CW, lines, S_H, lead=1.3))
        self.y += h + 4

    def para(self, text, size=S_BODY, color=INK, x=ML, w=CW, indent=0):
        lines = wrap(runs(text, color), w - indent, size)
        self._lines(lines, size, x + indent, w - indent)

    def _lines(self, lines, size, x, w, bullet=None, bullet_color=INK, lead=LEAD):
        i = 0
        lh = size * lead
        while i < len(lines):
            fit = max(1, int(self.room() // lh))
            if fit < 1 or (self.room() < lh and self.y > TOP + 1):
                self.new_page(cont=True)
                continue
            chunk = lines[i:i + fit]
            if bullet and i == 0:
                self.page.add(T(x - 16, self.y, 16, [[(bullet, True, bullet_color)]], size, lead=lead))
            self.page.add(T(x, self.y, w, chunk, size, lead=lead))
            self.y += len(chunk) * lh
            i += fit
            if i < len(lines):
                self.new_page(cont=True)

    def bullets(self, items, ordered=False, size=S_BODY, x=ML, w=CW):
        for n, it in enumerate(items, 1):
            mark = _circ(n) if ordered else '•'
            lines = wrap(runs(it), w - 20, size)
            h = text_h(len(lines), size)
            if h <= BOTTOM - TOP:
                self.need(h)
            col = ORANGE if ordered else NAVY
            self._lines(lines, size, x + 20, w - 20, bullet=mark, bullet_color=col)
            self.y += 2.5

    # ---- 표
    def table(self, head, rows, widths=None, badge_col=None, key_col=False, size=S_TABLE):
        ncol = len(head) if head else len(rows[0])
        widths = widths or _auto_widths(head, rows, ncol, size)
        tot = sum(widths)
        colw = [CW * w_ / tot for w_ in widths]
        pad = 6

        def cell_lines(txt, cw, bold=False, color=INK):
            return wrap(runs(str(txt), color, bold), cw - 2 * pad, size)

        hdr = None
        if head:
            hl = [cell_lines(c, colw[j], True, WHITE) for j, c in enumerate(head)]
            hh = max(len(x) for x in hl) * size * 1.3 + 2 * 5
            hdr = {'h': hh, 'cells': [{'lines': hl[j], 'fill': NAVY, 'size': size, 'align': 'center'} for j in range(ncol)]}
        body = []
        for r in rows:
            r = list(r) + [''] * (ncol - len(r))
            cells = []
            for j in range(ncol):
                txt = r[j]
                fill = KEY if (key_col and j == 0) else CELL
                bold = key_col and j == 0
                color = INK
                if badge_col is not None and j == badge_col and txt in BADGE:
                    fill, color = BADGE[txt]
                    bold = True
                cells.append({'lines': cell_lines(txt, colw[j], bold, color), 'fill': fill, 'size': size,
                              'align': 'center' if (badge_col is not None and j == badge_col) else 'left'})
            rh = max(len(c['lines']) for c in cells) * size * 1.3 + 2 * 5
            body.append({'h': rh, 'cells': cells})
        total = (hdr['h'] if hdr else 0) + sum(b['h'] for b in body)
        if total > self.room() and total <= BOTTOM - TOP and self.y > TOP + 1:
            # 한 장에 들어가는 표는 나누지 않는다. 다만 남은 자리가 넉넉하고 표가 길면 나눈다
            fit_rows = 0
            acc = hdr['h'] if hdr else 0
            for b in body:
                if acc + b['h'] > self.room():
                    break
                acc += b['h']
                fit_rows += 1
            self.new_page(cont=True)
        i = 0
        first = True
        while i < len(body) or first:
            avail = self.room() - (hdr['h'] if hdr else 0)
            take, acc = [], 0
            while i < len(body) and acc + body[i]['h'] <= avail:
                take.append(body[i])
                acc += body[i]['h']
                i += 1
            if not take and i < len(body):
                if self.y > TOP + 1:
                    self.new_page(cont=True)
                    continue
                take.append(body[i])     # 한 줄이 장표보다 크면 그대로 둔다
                acc += body[i]['h']
                i += 1
            rows_ = ([hdr] if hdr else []) + take
            th = sum(r['h'] for r in rows_)
            self.page.add({'k': 'table', 'x': ML, 'y': self.y, 'w': CW, 'cols': colw, 'rows': rows_, 'pad': pad,
                           'header': bool(hdr)})
            self.y += th
            first = False
            if i < len(body):
                self.new_page(cont=True)
        self.y += 4

    def kv(self, rows):
        self.table(None, rows, widths=[1, 3.2], key_col=True)

    # ---- 카드 (여러 칸)
    def cols(self, cols, size=S_BODY - 0.5):
        n = len(cols)
        gap = 12
        cw = (CW - gap * (n - 1)) / n
        pad = 10
        blocks = []
        for c in cols:
            tl = wrap(runs(c['title'], NAVY, True), cw - 2 * pad, size + 0.5)
            body = []
            for it in c['items']:
                ls = wrap(runs(it), cw - 2 * pad - 10, size)
                body.append(ls)
            h = text_h(len(tl), size + 0.5) + 6 + sum(text_h(len(b), size) + 3 for b in body) + 2 * pad
            blocks.append((tl, body, h))
        hmax = max(b[2] for b in blocks)
        if hmax > BOTTOM - TOP:
            # 너무 크면 위아래로 쌓는다
            for c in cols:
                self.heading(c['title'])
                self.bullets(c['items'])
            return
        self.need(hmax)
        for k, (tl, body, h) in enumerate(blocks):
            x = ML + k * (cw + gap)
            self.page.add(R(x, self.y, cw, hmax, fill=WHITE, stroke=LINE))
            self.page.add(R(x, self.y, cw, 3, fill=[NAVY, ORANGE, GREEN, NAVY][k % 4]))
            yy = self.y + pad
            self.page.add(T(x + pad, yy, cw - 2 * pad, tl, size + 0.5))
            yy += text_h(len(tl), size + 0.5) + 6
            for b in body:
                self.page.add(T(x + pad, yy, 10, [[('·', True, MUTED)]], size))
                self.page.add(T(x + pad + 10, yy, cw - 2 * pad - 10, b, size))
                yy += text_h(len(b), size) + 3
        self.y += hmax + 4

    # ---- 강조 상자
    def note(self, kind, title, lines_):
        pad = 10
        size = S_BODY - 0.5
        star = kind == 'star'
        head = ('★ ' if star else '※ ') + title
        tl = wrap(runs(head, SUB if star else MUTED, star), CW - 2 * pad, size + (0.5 if star else 0))
        bl = []
        for l_ in lines_:
            bl += wrap(runs(l_), CW - 2 * pad, size)
        h = text_h(len(tl), size) + (text_h(len(bl), size) + 3 if bl else 0) + 2 * pad - 4
        self.need(h)
        self.page.add(R(ML, self.y, CW, h, fill=STAR_BG if star else INFO_BG, stroke=STAR_LINE if star else None))
        yy = self.y + pad - 2
        self.page.add(T(ML + pad, yy, CW - 2 * pad, tl, size + (0.5 if star else 0)))
        yy += text_h(len(tl), size) + 3
        if bl:
            self.page.add(T(ML + pad, yy, CW - 2 * pad, bl, size))
        self.y += h + 4

    def quote(self, text):
        pad = 10
        lines = wrap(runs(text), CW - 2 * pad - 6, S_BODY)
        h = text_h(len(lines), S_BODY) + 2 * pad - 4
        self.need(h)
        self.page.add(R(ML, self.y, CW, h, fill=WHITE, stroke=LINE))
        self.page.add(R(ML, self.y, 4, h, fill=NAVY))
        self.page.add(T(ML + pad + 6, self.y + pad - 2, CW - 2 * pad - 6, lines, S_BODY))
        self.y += h + 4

    def code(self, text):
        size = 10
        lines = [[(l_, False, CODE_FG)] for l_ in text.split('\n')]
        h = len(lines) * size * 1.5 + 20
        self.need(h)
        self.page.add(R(ML, self.y, CW, h, fill=CODE_BG))
        self.page.add({'k': 'text', 'x': ML + 14, 'y': self.y + 10, 'w': CW - 28, 'lines': lines, 'size': size,
                       'leading': size * 1.5, 'align': 'left', 'mono': True})
        self.y += h + 4

    def flow(self, steps):
        n = len(steps)
        gap = 22
        bw = (CW - gap * (n - 1)) / n
        pad = 8
        tl = [wrap(runs(s['title'], WHITE, True), bw - 2 * pad, S_BODY) for s in steps]
        dl = [wrap(runs(s['desc'], INK), bw - 2 * pad, S_SMALL) for s in steps]
        hh = max(text_h(len(t), S_BODY) for t in tl) + 2 * pad
        dh = max(text_h(len(d_), S_SMALL) for d_ in dl) + 2 * pad
        self.need(hh + dh + 18)
        for k in range(n):
            x = ML + k * (bw + gap)
            self.page.add(T(x, self.y, bw, [[(f'STEP {k + 1}', True, ORANGE)]], 9.5))
            self.page.add(R(x, self.y + 16, bw, hh, fill=NAVY))
            self.page.add(T(x + pad, self.y + 16 + pad, bw - 2 * pad, tl[k], S_BODY, align='center'))
            self.page.add(R(x, self.y + 16 + hh, bw, dh, fill=WHITE, stroke=LINE))
            self.page.add(T(x + pad, self.y + 16 + hh + pad, bw - 2 * pad, dl[k], S_SMALL, align='center'))
            if k < n - 1:
                self.page.add(T(x + bw + 3, self.y + 16 + hh / 2 - 7, gap - 6, [[('▶', True, ORANGE)]], 10, align='center'))
        self.y += 16 + hh + dh + 6

    # ---- 그림
    def figure(self, f):
        path = os.path.join(self.d.img_dir, f['src'])
        if not os.path.exists(path):
            self.para(f"[그림 없음: {f['src']}]", color=SUB)
            return
        iw, ih = Image.open(path).size
        cap = f.get('caption', '')
        self.d.fig_no += 1
        cap_text = f"그림 {self.d.fig_label()}. {cap}" if cap else f"그림 {self.d.fig_label()}"
        side = list(f.get('points', []))
        if f.get('step'):
            side = [f['step']] + side
        note_ = f.get('note', '')
        if side or note_:
            # 왼쪽 그림, 오른쪽 설명
            lw_ = CW * 0.6
            rw = CW - lw_ - 16
            slines = []
            for k, s in enumerate(side):
                slines.append(wrap(runs(s, INK, k == 0 and bool(f.get('step'))), rw - 4, S_SMALL + 0.5))
            nl = wrap(runs(note_, SUB), rw - 4, S_SMALL) if note_ else []
            rh = sum(text_h(len(s), S_SMALL + 0.5) + 4 for s in slines) + (text_h(len(nl), S_SMALL) + 6 if nl else 0)
            cap_l = wrap(runs(cap_text, MUTED), lw_, S_SMALL)
            maxh = BOTTOM - TOP - text_h(len(cap_l), S_SMALL) - 6
            sc = min(lw_ / iw, maxh / ih)
            dw, dh = iw * sc, ih * sc
            need = max(dh + text_h(len(cap_l), S_SMALL) + 6, rh)
            if need > self.room():
                avail = self.room() - text_h(len(cap_l), S_SMALL) - 6
                if avail >= maxh * 0.55 and avail >= rh:
                    sc = min(sc, avail / ih)
                    dw, dh = iw * sc, ih * sc
                else:
                    self.new_page(cont=True)
            y0 = self.y
            self.page.add(R(ML, y0, dw, dh, fill=WHITE, stroke=LINE))
            self.page.add({'k': 'image', 'x': ML, 'y': y0, 'w': dw, 'h': dh, 'path': path})
            self.page.add(T(ML, y0 + dh + 4, lw_, cap_l, S_SMALL))
            yy = y0
            x2 = ML + lw_ + 16
            for s in slines:
                self.page.add(T(x2, yy, rw, s, S_SMALL + 0.5))
                yy += text_h(len(s), S_SMALL + 0.5) + 4
            if nl:
                self.page.add(T(x2, yy + 2, rw, nl, S_SMALL))
                yy += text_h(len(nl), S_SMALL) + 6
            self.y = max(y0 + dh + 4 + text_h(len(cap_l), S_SMALL), yy) + 8
        else:
            cap_l = wrap(runs(cap_text, MUTED), CW, S_SMALL)
            maxh = BOTTOM - TOP - text_h(len(cap_l), S_SMALL) - 6
            maxw = CW * (0.8 if iw > ih else 0.55)
            sc = min(maxw / iw, maxh / ih)
            dw, dh = iw * sc, ih * sc
            if dh + 30 > self.room():
                avail = self.room() - text_h(len(cap_l), S_SMALL) - 6
                if avail >= dh * 0.6:
                    sc = avail / ih
                    dw, dh = iw * sc, ih * sc
                else:
                    self.new_page(cont=True)
            x = ML + (CW - dw) / 2
            self.page.add(R(x, self.y, dw, dh, fill=WHITE, stroke=LINE))
            self.page.add({'k': 'image', 'x': x, 'y': self.y, 'w': dw, 'h': dh, 'path': path})
            self.page.add(T(ML, self.y + dh + 4, CW, cap_l, S_SMALL, align='center'))
            self.y += dh + 4 + text_h(len(cap_l), S_SMALL) + 8

    def steps_with_fig(self, lst, f):
        path = os.path.join(self.d.img_dir, f['src'])
        if not os.path.exists(path):
            return False
        iw, ih = Image.open(path).size
        lw_ = CW * 0.46
        rw = CW - lw_ - 18
        ordered = lst['t'] == 'ol'
        blocks = [wrap(runs(x), lw_ - 20, S_BODY) for x in lst['items']]
        th = sum(text_h(len(b), S_BODY) + 2.5 for b in blocks)
        cap = f.get('caption', '')
        self.d.fig_no += 1
        cap_text = f"그림 {self.d.fig_label()}. {cap}" if cap else f"그림 {self.d.fig_label()}"
        cap_l = wrap(runs(cap_text, MUTED), rw, S_SMALL)
        caph = text_h(len(cap_l), S_SMALL) + 4
        maxh = BOTTOM - TOP - caph
        sc = min(rw / iw, maxh / ih)
        dw, dh = iw * sc, ih * sc
        need = max(th, dh + caph)
        if need > BOTTOM - TOP:
            self.d.fig_no -= 1
            return False
        if need > self.room():
            # 남은 자리에 그림을 줄여 넣을 수 있으면 줄이고, 아니면 새 장표
            avail = self.room() - caph
            if th <= self.room() and avail >= dh * 0.7:
                sc = avail / ih
                dw, dh = iw * sc, ih * sc
            else:
                self.new_page(cont=True)
        y0 = self.y
        yy = y0
        for n, b in enumerate(blocks, 1):
            mark = _circ(n) if ordered else '•'
            self.page.add(T(ML, yy, 18, [[(mark, True, ORANGE if ordered else NAVY)]], S_BODY))
            self.page.add(T(ML + 20, yy, lw_ - 20, b, S_BODY))
            yy += text_h(len(b), S_BODY) + 2.5
        x2 = ML + lw_ + 18 + (rw - dw) / 2
        self.page.add(R(x2, y0, dw, dh, fill=WHITE, stroke=LINE))
        self.page.add({'k': 'image', 'x': x2, 'y': y0, 'w': dw, 'h': dh, 'path': path})
        self.page.add(T(ML + lw_ + 18, y0 + dh + 4, rw, cap_l, S_SMALL, align='center'))
        self.y = max(yy, y0 + dh + caph) + 6
        return True

    def props(self, rows):
        """항목 머리 정보 (문의 유형 · 처리 구분 · 담당 부서 …) 한 줄 띠."""
        n = len(rows)
        size = S_SMALL
        pad = 6
        cells = []
        for k_, v in rows:
            fill, color = BADGE.get(v, (CELL, INK))
            cells.append((k_, v, fill, color))
        kw = [sw(k_, size, True) + 2 * pad for k_, *_ in cells]
        vw = [sw(v, size, True) + 2 * pad for _, v, *_ in cells]
        tot = sum(kw) + sum(vw)
        sc = CW / tot if tot > CW else 1
        h = size * 1.3 + 2 * 5
        if sc < 1:
            # 폭이 모자라면 두 줄로
            half = (n + 1) // 2
            self.props(rows[:half])
            self.props(rows[half:])
            return
        self.need(h + 6)
        x = ML
        for (k_, v, fill, color), a, b in zip(cells, kw, vw):
            self.page.add(R(x, self.y, a, h, fill=KEY, stroke=LINE))
            self.page.add(T(x + pad, self.y + 4, a - 2 * pad, [[(k_, True, NAVY)]], size))
            self.page.add(R(x + a, self.y, b, h, fill=fill, stroke=LINE))
            self.page.add(T(x + a + pad, self.y + 4, b - 2 * pad, [[(v, True, color)]], size))
            x += a + b
        self.y += h + 10


def _circ(n):
    s = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
    return s[n - 1] if n <= len(s) else f'{n}.'


def _auto_widths(head, rows, ncol, size):
    ws = []
    for j in range(ncol):
        vals = ([head[j]] if head else []) + [str(r[j]) if j < len(r) else '' for r in rows]
        m = max(min(sw(plain(v), size), 260) for v in vals) + 14
        ws.append(max(m, 40))
    return ws


# ---------------------------------------------------------------- 문서 배치
def measure(it):
    """블록 높이 어림값 (쪽 나눔 판단용)."""
    t = it['t']
    if t == 'p':
        return text_h(len(wrap(runs(it['text']), CW, S_BODY)), S_BODY) + 7
    if t in ('ul', 'ol'):
        return sum(text_h(len(wrap(runs(x), CW - 20, S_BODY)), S_BODY) + 2.5 for x in it['items']) + 4
    if t in ('table', 'qa', 'kv'):
        head = it.get('head') if t == 'table' else (['질문', '답변'] if t == 'qa' else None)
        rows = it['rows'] if t != 'qa' else it['items']
        ncol = len(head) if head else len(rows[0])
        widths = it.get('widths') or ([4, 8] if t == 'qa' else [1, 3.2] if t == 'kv' else _auto_widths(head, rows, ncol, S_TABLE))
        tot = sum(widths)
        colw = [CW * w_ / tot for w_ in widths]
        hh = 0
        for r in ([head] if head else []) + [list(r) for r in rows]:
            hh += max(len(wrap(runs(str(c)), colw[j] - 12, S_TABLE)) for j, c in enumerate(r[:ncol])) * S_TABLE * 1.3 + 10
        return hh + 8
    if t == 'note':
        return 30 + sum(text_h(len(wrap(runs(x), CW - 20, S_BODY)), S_BODY) for x in it.get('lines', []))
    if t == 'cols':
        return 120
    if t == 'quote':
        return 40
    if t == 'code':
        return len(it['text'].split(chr(10))) * 15 + 28
    if t == 'flow':
        return 110
    if t == 'fig':
        return 220
    if t == 'h':
        return 24
    return 30


def render_items(flow, items):
    """조치 목록 바로 뒤에 설명 없는 그림이 오면 둘을 나란히 놓는다 (IT-SW-001 장표 배치).
    소제목은 바로 뒤 블록(짧은 문단이면 그다음 블록까지)과 같은 장에 둔다."""
    i = 0
    while i < len(items):
        it = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if it['t'] == 'h' and nxt is not None and flow.y > TOP + 1:
            follow = measure(nxt)
            if nxt['t'] == 'p' and i + 2 < len(items):
                follow += measure(items[i + 2])
            page_h = BOTTOM - TOP
            need = 26 + (follow if follow <= page_h - 30 else 90)
            if need > flow.room():
                flow.new_page(cont=True)
        if it['t'] in ('ol', 'ul') and nxt and nxt['t'] == 'fig' and not nxt.get('points') and not nxt.get('step'):
            if flow.steps_with_fig(it, nxt):
                i += 2
                flow.y += 4
                continue
        item(flow, it)
        i += 1


def item(flow, it):
    t = it['t']
    if t == 'h':
        flow.heading(it['text'])
    elif t == 'p':
        flow.para(it['text'])
        flow.y += 3
    elif t == 'ul':
        flow.bullets(it['items'])
    elif t == 'ol':
        flow.bullets(it['items'], ordered=True)
    elif t == 'table':
        flow.table(it['head'], it['rows'], it.get('widths'), it.get('badge_col'))
    elif t == 'kv':
        flow.kv(it['rows'])
    elif t == 'cols':
        flow.cols(it['cols'])
    elif t == 'note':
        flow.note(it['kind'], it['title'], it.get('lines', []))
    elif t == 'fig':
        flow.figure(it)
    elif t == 'quote':
        flow.quote(it['text'])
    elif t == 'code':
        flow.code(it['text'])
    elif t == 'flow':
        flow.flow(it['steps'])
    elif t == 'qa':
        flow.table(['질문', '답변'], it['items'], [4, 8], key_col=True)
    else:
        raise ValueError(t)
    flow.y += 4


def chapter_tag(ch):
    return f"{int(ch['no']):02d}. {ch['title']}" if ch['no'].isdigit() else ch['no']


def layout(doc, img_dir):
    from model import COMPANY, CATEGORIES
    d = Doc(doc, img_dir)
    d.fig_no = 0
    d.fig_sec = ''
    d.fig_label = lambda: f'{d.fig_sec}-{d.fig_no}' if d.fig_sec else str(d.fig_no)
    m = d.meta

    # 표지
    pg = Page('cover')
    pg.add(R(0, 0, W, H, fill=BG))
    pg.add(R(ML, 130, 92, 4, fill=ORANGE))
    from model import series as _series, RESTRICTED_NOTE
    series = _series(m)
    pg.add(T(ML, 166, CW, [[(series, False, MUTED)]], 15))
    tl = wrap(runs(m['title'], INK, True), CW, 40)
    pg.add(T(ML, 196, CW, tl, 40, lead=1.2))
    yy = 196 + text_h(len(tl), 40, 1.2) + 4
    line = f"{m['doc_no']}  |  {m['owner']}  |  {m['date'].replace('-', '.')}  |  Ver {m['version'].lstrip('v')}"
    pg.add(T(ML, yy, CW, [[(line, True, NAVY)]], 14))
    yy += 34
    restricted = m['access'] != '사내 일반'
    badge = f"{m['access']} · {m.get('audience', '')}"
    bw_ = sw(badge, 11, True) + 26
    pg.add(R(ML, yy, bw_, 24, fill=SUB if restricted else NAVY, radius=4))
    pg.add(T(ML + 13, yy + 5, bw_, [[(badge, True, WHITE)]], 11))
    if restricted:
        pg.add(T(ML, 448, CW, wrap(runs(RESTRICTED_NOTE.get(m['doc_type'], RESTRICTED_NOTE['manual']), MUTED), CW, 10), 10))
    pg.bookmarks.append((0, m['title']))
    d.pages.append(pg)

    # 문서 정보
    f = Flow(d, '문서 정보', m['doc_no'], bookmark=(0, '문서 정보'))
    f.table(None, doc_info_rows(m), widths=[1.1, 2.4, 1.1, 2.4], key_col=False)
    _shade_info(f.page)
    if m.get('keywords'):
        f.y += 4
        f.table(None, [['키워드', ', '.join(m['keywords'])]], widths=[1.1, 5.9], key_col=True)

    # Contents (쪽 번호는 뒤에서 채운다)
    contents = Page('contents', 'Contents', '')
    d.pages.append(contents)
    contents.bookmarks.append((0, 'Contents'))

    for ch in doc['chapters']:
        # 장 구분
        dv = Page('divider', bg=DARK)
        dv.add(R(0, 0, W, H, fill=DARK))
        num = f"{int(ch['no']):02d}" if ch['no'].isdigit() else ch['no']
        dv.add(T(ML, 196, CW, [[(num, True, ORANGE)]], 58 if ch['no'].isdigit() else 40, lead=1.1))
        dv.add(T(ML, 276, CW, wrap(runs(ch['title'], WHITE, True), CW, 34), 34, lead=1.2))
        label = f"{ch['no']}. {ch['title']}" if ch['no'].isdigit() else f"{ch['no']} · {ch['title']}"
        dv.bookmarks.append((0, label))
        d.pages.append(dv)
        d.toc.append((label, len(d.pages)))
        tag = chapter_tag(ch)
        if ch['items']:
            d.fig_sec, d.fig_no = (ch['no'] if ch['no'].isdigit() else ''), 0
            fl = Flow(d, ch['title'], tag)
            render_items(fl, ch['items'])
        for s in ch['sections']:
            d.fig_sec, d.fig_no = s['no'], 0
            fl = Flow(d, f"{s['no']} {s['title']}", tag, bookmark=(1, f"{s['no']} {s['title']}"))
            if s.get('props'):
                fl.props(s['props'])
            render_items(fl, s['items'])
    # 개정 이력
    fl = Flow(d, '개정 이력', '부록' if doc['chapters'][-1]['no'] == '부록' else '', bookmark=(0, '개정 이력'))
    fl.table(['버전', '개정일', '작성자', '변경 내용'], m['history'], [1, 1.4, 1.6, 7])

    # Contents 채우기
    frame(contents, d)
    y = TOP + 6
    rows = d.toc + [('개정 이력', fl.start_no)]
    step = min(34, (BOTTOM - TOP - 10) / max(len(rows), 1))
    for label, pno in rows:
        main = label[0].isdigit()
        size = 14 if main else 12.5
        col = NAVY if main else MUTED
        tw = sw(label, size, main)
        contents.add(T(ML + 30, y, CW - 120, [[(label, main, col)]], size))
        contents.add(L(ML + 40 + tw, y + size * 1.05, W - MR - 120, y + size * 1.05, '#C9CDD3', 0.6, dash=(1, 2)))
        contents.add(T(W - MR - 112, y, 60, [[(f'{pno}p', False, MUTED)]], 12, align='right'))
        y += step
    total = len(d.pages)
    for n, pg in enumerate(d.pages, 1):
        footer(pg, d, n, total)
    return d


def doc_info_rows(m):
    from model import CATEGORIES
    pair_label = '대상 사용자 가이드' if m['doc_type'] == 'manual' else '담당자 매뉴얼'
    rows = [
        ['문서 번호', m['doc_no'], '버전', m['version']],
        ['분류', f"{m['category']} {CATEGORIES.get(m['category'], '')}", '시행일', m['date']],
        ['문서 유형', m.get('doc_kind', ''), '열람 등급', f"{m['access']} ({m.get('audience', '')})"],
        ['관리 부서', m['owner'], '승인자', m.get('approver', '')],
    ]
    r5 = []
    if m['doc_type'] == 'manual':
        r5 = ['열람 대상', m.get('readers', ''), pair_label, m.get('pair', '') or '-']
    else:
        r5 = ['대상', m.get('target', ''), pair_label, m.get('pair', '') or '-']
    rows.append(r5)
    rows.append(['포함 시나리오', ', '.join(m.get('scenarios', [])) or '-', '관련 FAQ', ', '.join(m.get('faqs', [])) or '-'])
    return rows


def _shade_info(page):
    """문서 정보 표의 1·3열을 키 색으로 칠한다."""
    for el in page.els:
        if el['k'] == 'table':
            for r in el['rows']:
                for j in (0, 2):
                    if j < len(r['cells']):
                        r['cells'][j]['fill'] = KEY
                        r['cells'][j]['lines'] = [[(t, True, NAVY) for t, b, c in ln] for ln in r['cells'][j]['lines']]
