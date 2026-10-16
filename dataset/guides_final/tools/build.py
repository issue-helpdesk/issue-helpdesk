"""원천 JSON → md·docx·pptx·pdf 생성.

  python build.py                 # 전체
  python build.py IT-ACC-001 ...  # 일부
  python build.py --only pdf      # 형식 하나만
"""
import argparse
import os
import time

from model import *
import layout as LY


def out_dir(m):
    if m['doc_type'] in ('policy', 'standard'):
        return os.path.join(ROOT, 'common')
    return os.path.join(ROOT, m['category'], m['doc_type'])


def img_dir(m):
    return os.path.join(ROOT, m['category'] if m['doc_type'] in ('guide', 'manual') else 'common', 'images')


def base_name(m):
    return f"{m['doc_no']}_{m['title']}"


def build(path, only=None):
    doc = load(path)
    m = doc['meta']
    od = out_dir(m)
    os.makedirs(od, exist_ok=True)
    base = os.path.join(od, base_name(m))
    done = []
    if only in (None, 'pdf', 'pptx'):
        d = LY.layout(doc, img_dir(m))
        if only in (None, 'pdf'):
            import render_pdf
            render_pdf.render(d, base + '.pdf')
            done.append('pdf')
        if only in (None, 'pptx'):
            import render_pptx
            render_pptx.render(d, base + '.pptx')
            done.append('pptx')
    if only in (None, 'docx'):
        import render_docx
        render_docx.render(doc, img_dir(m), base + '.docx')
        done.append('docx')
    if only in (None, 'md'):
        import render_md
        render_md.render(doc, img_dir(m), base + '.md')
        done.append('md')
    return base, done


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('docs', nargs='*')
    ap.add_argument('--only')
    a = ap.parse_args()
    paths = all_sources()
    if a.docs:
        paths = [p for p in paths if os.path.basename(p)[:-5] in a.docs]
    t0 = time.time()
    for p in paths:
        base, done = build(p, a.only)
        print(os.path.relpath(base, ROOT), done)
    print(f'{len(paths)} docs, {time.time() - t0:.1f}s')
