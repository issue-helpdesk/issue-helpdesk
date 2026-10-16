"""layout 결과를 PDF로 그린다 (reportlab)."""
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

import layout as LY


def _c(h):
    return HexColor(h) if h else None


def draw_text(cv, el):
    size = el['size']
    lead = el['leading']
    mono = el.get('mono')
    for n, ln in enumerate(el['lines']):
        base = el['y'] + n * lead + size * 0.95 + (lead - size * 1.25) / 2
        yb = LY.H - base
        if el['align'] in ('center', 'right'):
            tw = sum(LY.sw(t, size, b) for t, b, _ in ln)
            x = el['x'] + (el['w'] - tw) / (2 if el['align'] == 'center' else 1)
        else:
            x = el['x']
        for t, b, col in ln:
            font = LY.MONO_PDF if mono else (LY.FONT_B if b else LY.FONT)
            cv.setFont(font, size)
            cv.setFillColor(_c(col))
            cv.drawString(x, yb, t)
            x += LY.pdfmetrics.stringWidth(t, font, size)


def draw_rect(cv, el):
    fill, stroke = _c(el.get('fill')), _c(el.get('stroke'))
    if fill:
        cv.setFillColor(fill)
    if stroke:
        cv.setStrokeColor(stroke)
        cv.setLineWidth(el.get('lw', 0.8))
    y = LY.H - el['y'] - el['h']
    if el.get('radius'):
        cv.roundRect(el['x'], y, el['w'], el['h'], el['radius'], stroke=1 if stroke else 0, fill=1 if fill else 0)
    else:
        cv.rect(el['x'], y, el['w'], el['h'], stroke=1 if stroke else 0, fill=1 if fill else 0)


def draw_table(cv, el):
    y = el['y']
    pad = el['pad']
    for r in el['rows']:
        x = el['x']
        for w, c in zip(el['cols'], r['cells']):
            draw_rect(cv, {'x': x, 'y': y, 'w': w, 'h': r['h'], 'fill': c.get('fill'), 'stroke': LY.LINE, 'lw': 0.6})
            draw_text(cv, {'x': x + pad, 'y': y + 5, 'w': w - 2 * pad, 'lines': c['lines'], 'size': c['size'],
                           'leading': c['size'] * 1.3, 'align': c.get('align', 'left')})
            x += w
        y += r['h']


def render(d, path):
    m = d.meta
    cv = canvas.Canvas(path, pagesize=(LY.W, LY.H))
    cv.setTitle(f"{m['doc_no']} {m['title']}")
    cv.setAuthor(m['owner'])
    cv.setSubject(f"{m['access']} · {m.get('audience', '')}")
    cv.setKeywords(', '.join(m.get('keywords', [])))
    cv.setCreator('ITssue guide builder')
    key_n = 0
    for pg in d.pages:
        for lvl, title in pg.bookmarks:
            key = f'b{key_n}'
            key_n += 1
            cv.bookmarkPage(key)
            cv.addOutlineEntry(title, key, level=lvl, closed=False)
        for el in pg.els:
            k = el['k']
            if k == 'rect':
                draw_rect(cv, el)
            elif k == 'line':
                cv.setStrokeColor(_c(el['color']))
                cv.setLineWidth(el['lw'])
                cv.setDash(*el['dash']) if el.get('dash') else cv.setDash()
                cv.line(el['x1'], LY.H - el['y1'], el['x2'], LY.H - el['y2'])
                cv.setDash()
            elif k == 'text':
                draw_text(cv, el)
            elif k == 'image':
                cv.drawImage(el['path'], el['x'], LY.H - el['y'] - el['h'], el['w'], el['h'], mask='auto')
            elif k == 'table':
                draw_table(cv, el)
        cv.showPage()
    cv.save()
