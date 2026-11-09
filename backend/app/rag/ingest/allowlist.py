"""매뉴얼 항목별 내용 전송 허용 목록 (해결 사례 가이드화 기획 v4 "선행 작업", 질문지 답 Q10~Q13).

허용 목록 JSON 은 매뉴얼 3.x 항목마다 한 줄: 문서 번호·항목 번호·제목·지문·내용 전송(ALLOWED·BLOCKED, M4 가 채움).
적재(일괄·업로드·다시 적재)는 매뉴얼이면 모든 청크에, 목록에 ALLOWED 이고 지문이 같으면 ALLOWED, 아니면 BLOCKED 를
적는다 (load·policies, 아래 "적재 판정").

지문 = 3장(장 번호 3) 안 3.x 항목 **하나 전체**(조각으로 나누기 전)를 **파서가 읽은 그대로** 정해진 JSON 으로 만들어 sha256.
넣는 것: 항목 제목·머리 정보(순서대로)·요소마다 [종류, 제목 수준, 글, 표 칸 배열, 코드 여부]. 표는 칸 배열 그대로라 칸 경계가
바뀌면 지문이 바뀐다. 빼는 것: 쪽 번호·조각 경계·그림 파일 (그림은 설명 글만 — 그림 파일만 바뀐 것은 잡지 못한다).
정리는 최소로: 글자 NFC, 줄 끝 LF, **줄 끝 공백**만 지운다. 줄 앞 공백(코드 들여쓰기)·기호(✓·✗·★)는 그대로 — 외부로
나가는 청크 글과 같은 것을 지문으로 삼는다 (md 파서가 지우는 이모지는 md 청크에도 없다). 빈 표 행은 청커처럼 뺀다.
같은 내용이라도 파서가 다르게 읽으면 지문이 달라져 **차단**된다 (안전한 쪽). 그때는 목록을 다시 만들어 M4 가 확인한다.
형식별 일치 수는 README "매뉴얼 항목별 내용 전송 허용 목록".

    python -m app.rag.ingest.allowlist skeleton --out app/rag/ingest/transfer_allowlist.json   # backend 폴더에서
    python -m app.rag.ingest.allowlist reapply --database-url <DB>            # 정책만 다시 반영: 미리보기
    python -m app.rag.ingest.allowlist reapply --database-url <DB> --apply    # 쓰기 (공유 DB 는 --allow-remote)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from app.rag.chunker import SECTION_NO_RE, _units
from app.rag.ingest import GUIDES, load_manifest
from app.rag.parser import parse
from app.rag.parser.models import Element, ParsedDocument

FINGERPRINT_VERSION = 1                                    # 지문 계산법이 바뀌면 올린다 (목록의 값과 다르면 모두 차단)
CONTENT_VALUES = ('ALLOWED', 'BLOCKED')
ALLOWLIST = Path(__file__).with_name('transfer_allowlist.json')   # 일괄·업로드 적재 모두 이 파일. 백엔드 코드 옆에 둬야
#   서버 이미지에 들어간다 (backend/Dockerfile 은 dataset/guides 를 복사하지 않는다 — 없으면 매뉴얼 내용을 모두 차단)


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


# ── 적재 판정 (질문지 답 Q10·Q13) ─────────────────────────────

FP_RE = re.compile(r'^sha256:[0-9a-f]{64}$')
SECTION_KEY_RE = re.compile(r'^3\.\d+$')


def load(path: Path = ALLOWLIST) -> tuple[dict[tuple[str, str], tuple[str | None, str]], list[str]]:
    """목록 → {(문서 번호, 항목 번호): (content, 지문)}, 경고. 믿을 수 없으면 그 부분은 비운다 (= 차단), 예외로 멈추지 않는다:
    - 파일 없음·읽기 실패·JSON 문법 오류·최상위가 객체 아님·계산법 버전 다름·`items` 가 배열 아님(없음 포함) → 전부
    - 항목이 객체 아님·`doc_no` 가 글자 아님·`section` 이 '3.N' 아님 → 어느 항목인지 몰라 뺌 (경고)
    - 같은 키가 둘 이상 (지문이 틀린 행도 센다) → 그 키, 지문이 'sha256:' 64자 아님·모르는 content 값 → 그 항목
    (PR #364 검수 2·재검수 1)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return {}, [f'허용 목록을 읽지 못해 매뉴얼 내용을 모두 차단합니다 ({type(e).__name__})']
    if not isinstance(data, dict):
        return {}, [f'허용 목록의 모양이 틀려(맨 위가 {type(data).__name__}) 매뉴얼 내용을 모두 차단합니다']
    version = data.get('fingerprint_version')
    if type(version) is not int or version != FINGERPRINT_VERSION:
        return {}, [f'허용 목록의 지문 계산법 버전({version!r})이 지금({FINGERPRINT_VERSION})과 달라 '
                    '매뉴얼 내용을 모두 차단합니다. 목록을 다시 만들어 M4 가 확인해 주세요']
    rows = data.get('items')
    if not isinstance(rows, list):
        return {}, [f"허용 목록에 항목 배열(items)이 없어({type(rows).__name__}) 매뉴얼 내용을 모두 차단합니다"]
    # 1단계: 어느 항목인지 알 수 있는 행(객체·doc_no·section 이 맞음)을 모두 모아 겹침부터 센다 — 지문이 틀린 행도
    # 센다. 틀린 행을 먼저 빼면 같은 키의 다른 행이 혼자 남아 허용될 수 있다 (PR #364 재검수 1)
    warnings, keyed = [], []
    for n, r in enumerate(rows, 1):
        bad = ('객체가 아님' if not isinstance(r, dict)
               else 'doc_no 가 글자가 아님' if not isinstance(r.get('doc_no'), str) or not r['doc_no']
               else "section 이 '3.N' 이 아님" if not isinstance(r.get('section'), str) or not SECTION_KEY_RE.match(r['section'])
               else '')
        if bad:
            warnings.append(f'허용 목록 {n}번째 항목: {bad} → 어느 항목인지 몰라 뺌')
        else:
            keyed.append((n, (r['doc_no'], r['section']), r))
    keys = [k for _, k, _ in keyed]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        warnings.append(f"허용 목록에 같은 항목이 여럿이라 차단합니다: {', '.join(f'{d} {s}' for d, s in sorted(dup))}")
    # 2단계: 겹치지 않는 키만 지문·값 검사. 지문이 틀리거나 값을 모르면 그 키는 차단 (목록에서 뺀다)
    out = {}
    for n, k, r in keyed:
        if k in dup:
            continue
        if not isinstance(r.get('fingerprint'), str) or not FP_RE.match(r['fingerprint']):
            warnings.append(f"허용 목록 {k[0]} {k[1]}: fingerprint 가 'sha256:…' 가 아님 → 차단")
            continue
        content = r.get('content')
        if content not in (*CONTENT_VALUES, None):
            warnings.append(f'허용 목록 {k[0]} {k[1]}: 모르는 값 {content!r} → 차단')
            content = None
        out[k] = (content, r['fingerprint'])
    return out, warnings


def policies(doc_no: str, doc: ParsedDocument, chunks: list, allow: dict) -> tuple[dict[str, str], list[str]]:
    """매뉴얼 한 문서의 청크별 내용 전송 {unit_key: ALLOWED·BLOCKED} (모든 청크에 값, M4 Q10). 경고.

    3장 안 3.x 항목이 목록에 ALLOWED 로 있고 지금 내용의 지문이 목록 지문과 같을 때만 ALLOWED. 나머지(목록 밖 항목·
    목록 BLOCKED·빈 값·지문 다름·3장 밖 장·서문·FAQ·번호가 겹치는 항목)는 BLOCKED. 판정은 항목 하나 전체로 한 번
    (조각마다 다시 계산하지 않는다) — 같은 항목의 조각은 모두 같은 값이다."""
    found = items(doc)
    sections = [i['section'] for i in found]
    dup = {s for s in sections if sections.count(s) > 1}
    allowed, warnings = set(), []
    for i in found:
        content, fp = allow.get((doc_no, i['section']), (None, None))
        if content != 'ALLOWED' or i['section'] in dup:
            continue
        if fp != i['fingerprint']:
            warnings.append(f"{doc_no} {i['section']}: 허용 목록 이후 내용이 바뀌어 차단합니다 (M4 확인 뒤 목록을 고쳐 주세요)")
            continue
        allowed.add(i['section'])
    if dup:
        warnings.append(f"{doc_no}: 3장 항목 번호가 겹쳐 차단합니다 ({', '.join(sorted(dup))})")
    out = {}
    for c in chunks:
        chapter = SECTION_NO_RE.match(c.heading_path[0] if c.heading_path else '')
        in_ch3 = c.chunk_type == 'item' and chapter is not None and chapter.group(1) == '3'
        out[c.unit_key] = 'ALLOWED' if in_ch3 and c.section_no in allowed else 'BLOCKED'
    return out, warnings


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


# ── 정책만 다시 반영 (질문지 답 Q12) ───────────────────────────

def reapply(conn, allow: dict, files_root: Path | None = None) -> dict:
    """DB 의 모든 청크 버전에 지금 목록으로 내용 전송 값을 다시 매긴다. **content_transfer_policy 칸만 고친다** (청크 id·
    본문·임베딩 그대로). commit 하지 않는다 (부른 쪽이 --apply 면 commit, 아니면 rollback).

    문서 종류는 **등록된 문서 행** (MANUAL 이면 버전 파일을 다시 읽어 policies, 아니면 모두 빈칸). 파일을 못 읽거나 파일의
    청크 구성(unit_key)이 DB 와 다르면 추측하지 않고 그 버전은 건너뛰고 알린다 (값 그대로).
    결과 {'changes': [(문서 번호, 버전, unit_key, 예전, 새, 조각 수)], 'updated': 고친 청크 수, 'skipped': [...], 'warnings': [...]}."""
    from app.rag.chunker import chunk_document
    from app.rag.ingest import ROOT, _audit, _lock_document
    from app.rag.ingest.upload import resolve_file
    root = files_root or ROOT
    versions = conn.execute(
        'select d.id, d.doc_code, d.doc_type, v.id, v.version, v.file_path from knowledge_documents d '
        'join document_versions v on v.document_id = d.id '
        'where exists (select 1 from document_chunks c where c.version_id = v.id) order by d.id, v.id').fetchall()
    out = {'changes': [], 'updated': 0, 'skipped': [], 'warnings': []}
    locked = set()
    for doc_id, doc_no, doc_type, vid, version, path in versions:
        db: dict[str, list] = {}
        for cid, unit, policy in conn.execute('select id, unit_key, content_transfer_policy from document_chunks '
                                              'where version_id = %s order by seq', (vid,)):
            db.setdefault(unit, []).append((cid, policy))
        if doc_type == 'MANUAL':
            try:
                doc = parse(str(resolve_file(path, root)))
            except Exception as e:                         # 파일 없음·읽기 실패 — 값을 바꾸지 않는다
                out['skipped'].append(f'{doc_no} {version}: 파일을 읽지 못해 건너뜀 ({type(e).__name__})')
                continue
            doc.meta['doc_no'], doc.meta['version'] = doc_no, version   # 등록값으로 (업로드 적재와 같은 unit_key)
            chunks = chunk_document(doc)
            if {c.unit_key for c in chunks} != set(db):
                out['skipped'].append(f'{doc_no} {version}: 파일의 청크 구성이 DB 와 달라 건너뜀 (다시 적재 필요)')
                continue
            want, warns = policies(doc_no, doc, chunks, allow)
            out['warnings'] += [f'{w} ({version})' for w in warns]
        else:
            want = {u: None for u in db}                   # 매뉴얼이 아니면 빈칸 = 버전 정책
        for unit, rows in db.items():
            stale = [(cid, p) for cid, p in rows if p != want[unit]]
            if not stale:
                continue
            if doc_id not in locked:                       # 적재·현행 전환과 같은 순서 (문서 먼저)
                _lock_document(conn, doc_id)
                locked.add(doc_id)
            conn.execute('update document_chunks set content_transfer_policy = %s where id = any(%s)',
                         (want[unit], [cid for cid, _ in stale]))
            olds = sorted({str(p) for _, p in stale})
            out['changes'].append((doc_no, version, unit, '/'.join(olds), str(want[unit]), len(stale)))
            out['updated'] += len(stale)
            _audit(conn, 'DOCUMENT_POLICY_CHANGE', doc_id, None,
                   f"{version} {unit.split('/', 1)[-1]} 내용 전송 {'/'.join(olds)} → {want[unit]} (허용 목록 다시 반영)")
    mixed = conn.execute('select v.version, c.unit_key from document_chunks c join document_versions v on v.id = c.version_id '
                         'group by v.version, c.unit_key having count(distinct coalesce(c.content_transfer_policy, \'-\')) > 1'
                         ).fetchall()
    out['warnings'] += [f'같은 항목의 조각 값이 다릅니다: {u} ({v})' for v, u in mixed]
    return out


def _report(out: dict, applied: bool) -> str:
    """허용↔차단 바뀐 항목은 한 줄씩, 그 밖(빈칸 ↔ BLOCKED 등)은 개수만."""
    allow_flip = [c for c in out['changes'] if 'ALLOWED' in (c[3], c[4])]
    other = len(out['changes']) - len(allow_flip)
    lines = [f"{'반영함' if applied else '미리보기 (DB 에 쓰지 않음, 쓰려면 --apply)'}: 청크 {out['updated']}개"]
    lines += ['허용↔차단 바뀐 항목:'] + [f"  {d} {v} {u.split('/', 1)[-1]}: {a} → {b} (조각 {n})"
                                          for d, v, u, a, b, n in allow_flip] if allow_flip else ['허용↔차단 바뀐 항목: 없음']
    if other:
        lines.append(f'그 밖에 바뀐 단위 {other}개 (빈칸 ↔ BLOCKED 등, 전송 결과는 같음)')
    lines += [f'건너뜀: {s}' for s in out['skipped']] + [f'경고: {w}' for w in out['warnings']]
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m app.rag.ingest.allowlist', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sk = sub.add_parser('skeleton', help='매뉴얼 정리본에서 허용 목록 뼈대(JSON)를 만든다 (content 비움)')
    sk.add_argument('--guides', default=str(GUIDES))
    sk.add_argument('--out', help='쓸 파일 (없으면 화면). 이미 있으면 --force 없이는 덮어쓰지 않는다')
    sk.add_argument('--force', action='store_true')
    ra = sub.add_parser('reapply', help='정책만 다시 반영: 지금 목록으로 DB 청크의 내용 전송 값만 고친다 (청크·임베딩 그대로)')
    ra.add_argument('--database-url', required=True, help='고칠 DB (.env 는 읽지 않는다)')
    ra.add_argument('--allow-remote', action='store_true', help='localhost 가 아닌 DB(공유 DB)에 쓸 때 꼭 준다')
    ra.add_argument('--apply', action='store_true', help='DB 에 쓴다. 없으면 미리보기 (바뀔 것만 보이고 되돌린다)')
    ra.add_argument('--files-root', help='버전 file_path 의 기준 폴더 (기본 저장소 루트)')
    a = ap.parse_args(argv)
    if a.cmd == 'reapply':
        from app.rag.ingest import connect, is_local
        if not a.allow_remote and not is_local(a.database_url):
            print('localhost 가 아닌 DB 입니다. 공유 DB 에 쓰려면 --allow-remote 를 주세요.', file=sys.stderr)
            return 2
        allow, notes = load()
        with connect(a.database_url, a.allow_remote) as conn:
            out = reapply(conn, allow, Path(a.files_root) if a.files_root else None)
            out['warnings'] = notes + out['warnings']
            (conn.commit if a.apply else conn.rollback)()
        print(_report(out, a.apply))
        return 0
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
