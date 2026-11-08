"""매뉴얼 항목별 내용 전송 허용 목록 (해결 사례 가이드화 기획 v4 "선행 작업", 질문지 답 Q10~Q13).

허용 목록 JSON 은 매뉴얼 3.x 항목마다 한 줄: 문서 번호·항목 번호·제목·지문·내용 전송(ALLOWED·BLOCKED, M4 가 채움).
적재는 목록에 있고 지문이 같으면 ALLOWED, 아니면 BLOCKED 로 청크에 적는다 (판정 연결은 다음 작업).

지문 = 3.x 항목 **하나 전체**(조각으로 나누기 전)의 내용. 항목 제목·머리 정보(문의 유형 등)·요소(소제목·문단·목록·표·그림 설명)를
정해진 모양의 글로 이어 sha256. 쪽 번호·조각 경계는 넣지 않는다 (청커가 나누는 규칙이 바뀌어도 내용이 같으면 같은 지문).
줄 끝을 LF 로, 글자를 NFC 로 맞추고, 꾸밈 기호(md 파서가 지우는 이모지·★ 범위 EMOJI_RE)와 줄 앞뒤 공백만 지운다
(낱말 사이 공백·대소문자는 그대로 — 내용 변경을 숨기지 않게).
그림은 설명 글만 넣는다 (md 정리본엔 그림 내용 확인 값이 없어 형식마다 달라지지 않게). 그림 파일만 바뀐 것은 잡지 못한다.
파서가 같은 내용을 다르게 읽게 바뀌면 지문이 달라져 차단된다 — 그때는 목록을 다시 만들어 확인한다 (안전한 쪽).
형식별 (2026-11-08, 매뉴얼 143 항목을 정리본 md 지문과 비교): docx 143 같음, pptx 115·pdf 113 같음 — 나머지는 그림 설명
자리·끝 마침표처럼 슬라이드·쪽을 읽는 차이라 차단된다 (내용 변경까지 숨길 수 있어 더 맞추지 않는다).

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
from app.rag.parser.md_parser import EMOJI_RE
from app.rag.parser.models import Element, ParsedDocument

FINGERPRINT_VERSION = 1                                    # 지문 계산법이 바뀌면 올린다 (목록의 값과 다르면 모두 차단)
CONTENT_VALUES = ('ALLOWED', 'BLOCKED')


def _norm(text: str) -> str:
    text = EMOJI_RE.sub('', unicodedata.normalize('NFC', text or ''))   # ★·🟢 등 꾸밈 기호: md 파서는 지우고 docx 등은 남김
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return '\n'.join(line.strip() for line in lines).strip('\n')


def _element_text(e: Element) -> str:
    if e.kind == 'heading':
        return f'### {_norm(e.text)}'
    if e.kind == 'table':
        rows = [[_norm(c) for c in r] for r in e.rows or [] if any((c or '').strip() for c in r)]
        return '\n'.join('| ' + ' | '.join(r) + ' |' for r in rows)
    if e.kind == 'image':
        return f'[그림] {_norm(e.text)}'.rstrip()
    if e.kind == 'list_item':
        return f'- {_norm(e.text)}'
    return _norm(e.text)


def item_text(title: str, props: list, elements: list[Element]) -> str:
    """지문을 내는 글 (사람이 차이를 볼 때도 쓴다)."""
    head = [f'## {_norm(title)}', *(f'{_norm(k)}: {_norm(v)}' for k, v in props or [])]
    body = [t for t in (_element_text(e) for e in elements) if t]
    return '\n'.join(head + [''] + body)


def fingerprint(title: str, props: list, elements: list[Element]) -> str:
    return 'sha256:' + hashlib.sha256(item_text(title, props, elements).encode('utf-8')).hexdigest()


def items(doc: ParsedDocument) -> list[dict]:
    """문서의 3.x 항목들: [{section, title, fingerprint}] (읽는 순서). 3장 밖의 장·서문·하위 절이 아닌 항목은 뺀다."""
    out = []
    for kind, _chapter, item, pieces in _units(doc):
        if kind != 'item' or item is None:
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
        rows += [{'doc_no': e['doc_no'], 'section': i['section'], 'title': i['title'], 'content': None,
                  'fingerprint': i['fingerprint']} for i in items(doc)]
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
