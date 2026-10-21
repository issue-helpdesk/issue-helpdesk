"""guides 기준 파서 채점 도구 (개발용, 운영 코드 아님).

정리본은 원천 JSON(tools/source/{분류}/{문서 번호}.json) 하나에서 pdf·pptx·docx·md를 만든다.
그래서 원천 JSON을 정답으로 두고, 형식마다 파서 결과를 비교한다. tests/test_parser.py 도 이 채점을 쓴다.

- 구조: 제목 순서 (0 문서 제목, 1 장, 2 항목 3.x, 3 소제목·카드 제목)가 정답과 같은지
- 내용: 원천의 문장·목록·표 칸·그림 설명이 파싱 결과에 들어 있는지 (포함률)
- 항목 머리: 3.x 항목의 props(문의 유형 등)가 정답과 같은지
- 메타데이터: 문서 번호·버전·열람 등급·포함 시나리오
- 순서: md 결과 대비 본문 요소 순서

    python tests/check_guides.py                          # 전체 (저장소 루트에서, 약 1분)
    python tests/check_guides.py IT-SW-002 --show         # 한 문서, 다른 곳 보기
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'backend'))
from app.rag.parser import parse  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', 'dataset', 'guides'))
FORMATS = ('md', 'docx', 'pptx', 'pdf')


CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'


def norm(s: str) -> str:
    """비교용 정규화: 굵게 표시·이모지·공백 제거, ①→1. , 끝 마침표 제거 (그림 설명은 형식마다 끝 마침표가 다르다)."""
    s = re.sub(r'\*\*|[\U0001F300-\U0001FAFF☀-➿]️?', '', str(s))
    s = re.sub(f'[{CIRCLED}]', lambda m: f'{CIRCLED.index(m.group()) + 1}.', s)
    return re.sub(r'\s+', '', s).rstrip('.')


def label(ch):
    return f"{ch['no']}. {ch['title']}" if ch['no'].isdigit() else f"{ch['no']} · {ch['title']}"


def expected(src: dict):
    """원천 JSON → (제목 순서, 내용 문자열 목록, 항목별 props)."""
    m = src['meta']
    outline = [(0, m['title'])]
    texts: list[str] = []
    props = {}

    def items(its):
        for it in its:
            t = it['t']
            if t == 'h':
                outline.append((3, it['text']))
            elif t == 'cols':
                for c in it['cols']:
                    outline.append((3, c['title']))
                    texts.extend(c['items'])
            elif t == 'p':
                texts.append(it['text'])
            elif t in ('ul', 'ol'):
                texts.extend(it['items'])
            elif t == 'table':
                texts.extend([c for c in (it.get('head') or [])] + [c for r in it['rows'] for c in r])
            elif t == 'kv':
                texts.extend(c for r in it['rows'] for c in r)
            elif t == 'qa':
                texts.extend(x for qa in it['items'] for x in qa)
            elif t == 'note':
                texts.append(it['title'])
                texts.extend(it.get('lines', []))
            elif t in ('quote', 'code'):
                texts.extend(it['text'].split('\n'))
            elif t == 'flow':
                texts.extend(x for s in it['steps'] for x in (s['title'], s['desc']))
            elif t == 'fig':
                if it.get('caption'):
                    texts.append(it['caption'])
                texts.extend(([it['step']] if it.get('step') else []) + list(it.get('points', [])))
                if it.get('note'):
                    texts.append(it['note'])

    for ch in src['chapters']:
        outline.append((1, label(ch)))
        items(ch['items'])
        for s in ch['sections']:
            name = f"{s['no']} {s['title']}"
            outline.append((2, name))
            if s.get('props'):
                props[name] = [[k, v] for k, v in s['props']]
            items(s['items'])
    outline.append((1, '개정 이력'))
    texts.extend(c for r in m.get('history', []) for c in r)
    texts = [t for t in texts if norm(t)]
    return outline, texts, props


def parsed_text(doc) -> str:
    parts = []
    for e in doc.elements:
        if e.kind == 'table':
            parts.extend(c for r in (e.rows or []) for c in r)
        else:
            parts.append(e.text)
        for k, v in e.meta.get('props', []) or []:
            parts.append(f'{k}{v}')
    return norm(''.join(parts))


def score(doc, exp_outline, exp_texts, exp_props, meta):
    got = [(lv, norm(t)) for lv, t in doc.outline()]
    want = [(lv, norm(t)) for lv, t in exp_outline]
    sm = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
    outline_ratio = sm.ratio()
    body = parsed_text(doc)
    missing = [t for t in exp_texts if norm(t) not in body]
    coverage = 1 - len(missing) / max(len(exp_texts), 1)
    got_props = {e.text: e.meta.get('props') for e in doc.headings() if e.level == 2}
    prop_ok = sum(1 for k, v in exp_props.items()
                  if [[a, norm(b)] for a, b in (got_props.get(k) or [])] == [[a, norm(b)] for a, b in v])
    props_ratio = prop_ok / len(exp_props) if exp_props else 1.0
    meta_ok = (doc.meta.get('doc_no') == meta.get('doc_no') and doc.meta.get('version') == meta.get('version')
               and doc.meta.get('access_level') == meta.get('access')
               and list(doc.meta.get('scenarios', [])) == list(meta.get('scenarios', [])))
    return {
        'outline': round(outline_ratio, 3), 'outline_exact': got == want,
        'coverage': round(coverage, 3), 'props': round(props_ratio, 3), 'meta': meta_ok,
        'missing': missing, 'opcodes': sm.get_opcodes(), 'want': want, 'got': got,
    }


def iter_docs(only=None):
    with open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    for d in manifest:          # RAG 대상이 아닌 문서(IT-AI-001)도 파서 검증에는 넣는다
        if only and not any(d['doc_no'] == o or d['doc_no'].startswith(o) for o in only):
            continue
        src = os.path.join(ROOT, 'tools', 'source', d['category'], d['doc_no'] + '.json')
        if os.path.exists(src):
            yield d, src


def body_seq(doc) -> list[str]:
    """본문 순서 비교용: 문단·목록·그림 설명·표 칸을 읽는 순서대로."""
    out = []
    for e in doc.elements:
        if e.kind == 'table':
            out += [norm(c) for r in (e.rows or []) for c in r if norm(c)]
        elif norm(e.text):
            out.append(norm(e.text))
    return out


def run(only=None, formats=FORMATS, show=False, quiet=False):
    rows = []
    for d, src_path in iter_docs(only):
        with open(src_path, encoding='utf-8') as f:
            src = json.load(f)
        eo, et, ep = expected(src)
        base = body_seq(parse(os.path.join(ROOT, d['files']['md']))) if d['files'].get('md') else None
        for fmt in formats:
            rel = d['files'].get(fmt)
            if not rel:
                continue
            path = os.path.join(ROOT, rel)
            try:
                doc = parse(path)
            except Exception as ex:
                rows.append((d['doc_no'], fmt, None, str(ex)))
                continue
            sc = score(doc, eo, et, ep, src['meta'])
            sc['order'] = round(difflib.SequenceMatcher(a=base, b=body_seq(doc), autojunk=False).ratio(), 3) if base else 1.0
            rows.append((d['doc_no'], fmt, sc, ''))
            if show:
                _show(d['doc_no'], fmt, sc)
    if not quiet:
        _report(rows, formats)
    return rows


def _show(no, fmt, sc):
    print(f'\n=== {no} [{fmt}] outline={sc["outline"]} coverage={sc["coverage"]} props={sc["props"]} meta={sc["meta"]}')
    for tag, i1, i2, j1, j2 in sc['opcodes']:
        if tag == 'equal':
            continue
        for x in sc['want'][i1:i2]:
            print(f'   - 정답에만: L{x[0]} {x[1][:60]}')
        for x in sc['got'][j1:j2]:
            print(f'   + 결과에만: L{x[0]} {x[1][:60]}')
    for t in sc['missing'][:8]:
        print(f'   ? 빠진 내용: {t[:70]}')


def _report(rows, formats):
    print(f'\n{"형식":<6}{"문서":>5}{"구조 평균":>10}{"구조 일치":>10}{"내용 포함":>10}{"항목 머리":>10}{"메타":>8}{"순서(md 대비)":>14}{"오류":>6}')
    for fmt in formats:
        rs = [r for r in rows if r[1] == fmt]
        ok = [r[2] for r in rs if r[2]]
        if not rs:
            continue
        avg = lambda k: sum(x[k] for x in ok) / len(ok) if ok else 0
        print(f'{fmt:<6}{len(rs):>5}{avg("outline"):>10.3f}{sum(x["outline_exact"] for x in ok):>7}/{len(ok):<3}'
              f'{avg("coverage"):>9.3f}{avg("props"):>10.3f}{sum(x["meta"] for x in ok):>5}/{len(ok):<3}'
              f'{avg("order"):>12.3f}{sum(1 for r in rs if not r[2]):>6}')
    worst = sorted([r for r in rows if r[2]], key=lambda r: (r[2]['outline'] + r[2]['coverage']))[:8]
    print('\n낮은 문서:', ', '.join(f'{r[0]}[{r[1]}] 구조 {r[2]["outline"]} 내용 {r[2]["coverage"]}' for r in worst))
    for r in rows:
        if not r[2]:
            print(f'오류 {r[0]}[{r[1]}]: {r[3]}')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python tests/check_guides.py')
    ap.add_argument('only', nargs='*', help='문서 번호 (앞부분만 써도 됨)')
    ap.add_argument('--format', choices=FORMATS, action='append')
    ap.add_argument('--show', action='store_true', help='정답과 다른 제목·빠진 내용 보기')
    a = ap.parse_args(argv)
    run(a.only or None, tuple(a.format) if a.format else FORMATS, a.show)
    return 0


if __name__ == '__main__':
    sys.exit(main())
