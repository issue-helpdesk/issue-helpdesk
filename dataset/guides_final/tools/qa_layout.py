"""장표 레이아웃 점검: 본문 영역을 넘은 요소, 거의 빈 장표, 너무 작은 그림을 찾는다."""
import layout as LY
from model import *

issues = []
stats = []
for p_ in all_sources():
    doc = load(p_)
    m = doc['meta']
    from build import img_dir
    d = LY.layout(doc, img_dir(m))
    stats.append((m['doc_no'], len(d.pages)))
    for n, pg in enumerate(d.pages, 1):
        if pg.kind != 'content':
            continue
        maxy = 0
        body = 0
        for el in pg.els:
            if el['k'] == 'text':
                y2 = el['y'] + len(el['lines']) * el['leading']
                if el['y'] >= LY.TOP - 1 and el['y'] < 505:
                    maxy = max(maxy, y2)
                    body += 1
                w = max((sum(LY.sw(t, el['size'], b) for t, b, _ in ln) for ln in el['lines']), default=0)
                if w > el['w'] + 2 and el['x'] + w > LY.W - LY.MR + 2:
                    issues.append((m['doc_no'], n, 'wide', ''.join(t for t, _, _ in el['lines'][0])[:40]))
            elif el['k'] in ('table', 'image', 'rect'):
                h_ = sum(r['h'] for r in el['rows']) if el['k'] == 'table' else el['h']
                if el['y'] >= LY.TOP - 1:
                    maxy = max(maxy, el['y'] + h_)
                    body += 1
                if el['k'] == 'image' and el['h'] < 90:
                    issues.append((m['doc_no'], n, 'small-image', f"{el['w']:.0f}x{el['h']:.0f}"))
        if maxy > LY.BOTTOM + 6:
            issues.append((m['doc_no'], n, 'overflow', f'{maxy:.0f}'))
        if maxy and maxy < LY.TOP + 30:
            issues.append((m['doc_no'], n, 'near-empty', pg.title[:40]))
for i in issues:
    print(*i)
print(len(issues), 'issues;', sum(s for _, s in stats), 'pages in', len(stats), 'docs')
