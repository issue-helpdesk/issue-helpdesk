"""매뉴얼 항목별 내용 전송 허용 목록 (해결 사례 가이드화 기획 v4 "선행 작업", 질문지 답 Q10~Q13).

허용 목록 JSON 은 매뉴얼 3.x 항목마다 한 줄: 문서 번호·항목 번호·제목·지문·내용 전송(ALLOWED·BLOCKED, M4 가 채움).
적재는 목록에 있고 지문이 같으면 ALLOWED, 아니면 BLOCKED 로 청크에 적는다 (판정 연결은 다음 작업).

지문 = 3장(장 번호 3) 안 3.x 항목 **하나 전체**(조각으로 나누기 전)를 **파서가 읽은 그대로** 정해진 JSON 으로 만들어 sha256.
넣는 것: 항목 제목·머리 정보(순서대로)·요소마다 [종류, 제목 수준, 글, 표 칸 배열, 코드 여부]. 표는 칸 배열 그대로라 칸 경계가
바뀌면 지문이 바뀐다. 빼는 것: 쪽 번호·조각 경계·그림 파일 (그림은 설명 글만 — 그림 파일만 바뀐 것은 잡지 못한다).
정리는 최소로: 글자 NFC, 줄 끝 LF, **줄 끝 공백**만 지운다. 줄 앞 공백(코드 들여쓰기)·기호(✓·✗·★)는 그대로 — 외부로
나가는 청크 글과 같은 것을 지문으로 삼는다 (md 파서가 지우는 이모지는 md 청크에도 없다). 빈 표 행은 청커처럼 뺀다.
같은 내용이라도 파서가 다르게 읽으면 지문이 달라져 **차단**된다 (안전한 쪽). 그때는 목록을 다시 만들어 M4 가 확인한다.
형식별 일치 수는 README "매뉴얼 항목별 내용 전송 허용 목록".

    python -m app.rag.ingest.allowlist skeleton --out ../dataset/guides/transfer_allowlist.json   # backend 폴더에서
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

from app.rag.chunker import SECTION_NO_RE, _units
from app.rag.ingest import GUIDES, load_manifest
from app.rag.parser import parse
from app.rag.parser.models import Element, ParsedDocument

FINGERPRINT_VERSION = 1                                    # 지문 계산법이 바뀌면 올린다 (목록의 값과 다르면 모두 차단)
CONTENT_VALUES = ('ALLOWED', 'BLOCKED')


def _norm(text: str) -> str:
    lines = unicodedata.normalize('NFC', text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return '\n'.join(line.rstrip() for line in lines).strip('\n')


def _element(e: Element) -> list:
    rows = [[_norm(c) for c in r] for r in e.rows or [] if any((c or '').strip() for c in r)] if e.kind == 'table' else []
    return [e.kind, e.level if e.kind == 'heading' else None, _norm(e.text), rows, bool(e.meta.get('code'))]


def _canonical(title: str, props: list, elements: list[Element]) -> list:
    return [_norm(title), [[_norm(k), _norm(v)] for k, v in props or []], [_element(e) for e in elements]]


def fingerprint(title: str, props: list, elements: list[Element]) -> str:
    data = json.dumps(_canonical(title, props, elements), ensure_ascii=False, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(data.encode('utf-8')).hexdigest()


def item_text(title: str, props: list, elements: list[Element]) -> str:
    """사람이 차이를 볼 때 쓰는 글 (지문 입력은 _canonical JSON)."""
    t, ps, els = _canonical(title, props, elements)
    out = [f'## {t}', *(f'{k}: {v}' for k, v in ps), '']
    for kind, level, text, rows, code in els:
        if kind == 'table':
            out.append('\n'.join('| ' + ' | '.join(c.replace('|', r'\|') for c in r) + ' |' for r in rows))
        elif code:
            out.append(f'```\n{text}\n```')
        elif kind == 'heading':
            out.append(f"{'#' * (level or 3)} {text}")
        else:
            out.append({'image': f'[그림] {text}', 'list_item': f'- {text}'}.get(kind, text))
    return '\n'.join(out)


def items(doc: ParsedDocument) -> list[dict]:
    """문서의 3.x 항목들: [{section, title, fingerprint}] (읽는 순서). **장 번호가 3** 인 장 안의 '3.x' 항목만
    (다른 장의 '3.x' 제목·서문·장 없는 항목은 뺀다 — M4 Q10 "3.x 밖은 BLOCKED")."""
    out = []
    for kind, chapter, item, pieces in _units(doc):
        if kind != 'item' or item is None:
            continue
        c = SECTION_NO_RE.match(chapter or '')
        if not c or c.group(1) != '3':
            continue
        m = SECTION_NO_RE.match(item.text)
        if not m or not m.group(1).startswith('3.'):
            continue
        props = [tuple(p) for p in (item.meta.get('props') or [])]
        out.append({'section': m.group(1), 'title': SECTION_NO_RE.sub('', item.text, count=1).strip(),
                    'fingerprint': fingerprint(item.text, props, pieces)})
    return out


def skeleton(guides: Path = GUIDES) -> dict:
    """manifest 의 매뉴얼(doc_type manual) 정리본 md 에서 허용 목록 뼈대. content 는 비워 둔다 (M4 가 채움)."""
    rows = []
    for e in load_manifest(guides):
        if e.get('doc_type') != 'manual':
            continue
        doc = parse(str((Path(guides) / e['files']['md']).resolve()))
        found = items(doc)
        if dup := sorted({i['section'] for i in found if [x['section'] for x in found].count(i['section']) > 1}):
            raise ValueError(f"{e['doc_no']}: 3장 항목 번호가 겹칩니다 ({', '.join(dup)}). 문서를 고친 뒤 다시 만드세요")
        rows += [{'doc_no': e['doc_no'], 'section': i['section'], 'title': i['title'], 'content': None,
                  'fingerprint': i['fingerprint']} for i in found]
    return {'fingerprint_version': FINGERPRINT_VERSION,
            'note': 'content: ALLOWED(내용 전송) · BLOCKED(제목만). 비어 있으면 BLOCKED. 지문은 B 가 만든다 (allowlist.py)',
            'items': rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.ingest.allowlist', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sk = sub.add_parser('skeleton', help='매뉴얼 정리본에서 허용 목록 뼈대(JSON)를 만든다 (content 비움)')
    sk.add_argument('--guides', default=str(GUIDES))
    sk.add_argument('--out', help='쓸 파일 (없으면 화면). 이미 있으면 --force 없이는 덮어쓰지 않는다')
    sk.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    data = skeleton(Path(a.guides))
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if not a.out:
        sys.stdout.write(text)
        return 0
    out = Path(a.out)
    if out.exists() and not a.force:
        print(f'{out} 가 이미 있습니다 (채운 값을 지우지 않게 멈춤). 덮어쓰려면 --force', file=sys.stderr)
        return 2
    out.write_text(text, encoding='utf-8')
    print(f'{out}: 매뉴얼 {len({r["doc_no"] for r in data["items"]})}종, 항목 {len(data["items"])}개')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
