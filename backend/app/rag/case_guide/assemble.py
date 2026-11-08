"""묶음 등록용 조립 (해결 사례 가이드화 기획 v4, `작업대/가이드화/draft_basis_구조_초안_20261108.md` 6장 ①).

등록 API(박민경)가 묶음 하나의 등록 요청을 받으면, 그 문서에 이어 쓸 대기 버전이 있으면 [그 버전 묶음(거절 제외) + 이번 묶음],
없으면 [이번 묶음] 을 계산해 이 함수에 넘긴다. 이 함수는 **현행 md + 조각들** 로 문서를 처음부터 다시 조립한다.

    out = assemble(conn, document_id, clusters, draft_version_id, view_scope='ALL', transfer_policy='ALLOWED', actor_id=1)
    # API: 같은 트랜잭션에서 묶음 registered_version_id·section_no 저장, 운영 기록, commit → submit_ingest

- 묶음 하나 = {'id', 'judgment', 'draft_md', 'draft_basis', 'receipts'}. 판단은 ADD_ITEM·SEC_MANUAL(항목 하나 더함),
  CHANGE(항목 하나를 관리자가 고친 조각으로 바꿔 끼움). NEW_GUIDE 는 아직 (뼈대 함수와 함께 다음 작업).
- 항목 번호: 기준 md 의 3장 번호와 `draft_basis.section_no` 가 있는 조각의 번호를 먼저 잡고, 없는 조각에 다음 번호를 준다.
  돌려준 `sections` 를 API 가 각 묶음 `draft_basis.section_no` 에 저장한다 (같은 대기 버전을 다시 조립할 때 유지).
- **DB commit·rollback 을 하지 않는다** (트랜잭션은 API 것). 파일은 쓸 때마다 새 경로. 돌려주기 전에 실패하면 이번에
  만든 파일만 지우고 오류를 다시 던진다. 돌려준 뒤 API 쪽이 실패하면 API 가 file_path 를 지운다.
- 거부는 CaseGuideError(problems). 경고는 결과 warnings.
"""
from __future__ import annotations

import re
import secrets
from datetime import date
from pathlib import Path

from app.rag.chunker import validate
from app.rag.ingest import ROOT, _lock_document
from app.rag.ingest.upload import resolve_file

from . import (CASE_DIR, HANDLING, MARK, TRANSFER_POLICIES, VIEW_SCOPES, CaseGuideError, _add_history, _add_table_row,
               _add_toc, _added_lines, _append_item, _base_md, _chapter3, _chapter3_end, _item_heads, _item_numbers,
               _one_line, _parse_text, _set_table_row, _set_toc, _set_version, _staff_names, next_version, receipts,
               sensitive_warnings)

SCHEMA = 1                                                 # draft_basis.schema
ADD_KINDS = ('ADD_ITEM', 'SEC_MANUAL')                     # 3장 끝에 항목 하나 더함
SUPPORTED = (*ADD_KINDS, 'CHANGE')
HEAD_RE = re.compile(r'^### (3\.(?:\d+|N))[ \t]+(\S.*)$')   # 조각 첫 줄. 번호는 아무거나 (조립 때 바꾼다)
FENCE_RE = re.compile(r'^\s*(`{3,})')
PROP_RE = {k: re.compile(rf'\*\*{k}\*\*\s*([^·\n*]+)') for k in ('문의 유형', '처리 구분', '담당 부서')}
SECTION_RE = re.compile(r'^3\.\d+$')


def assemble(conn, document_id: int, clusters: list[dict], draft_version_id: int | None, *, view_scope: str,
             transfer_policy: str, actor_id: int | None, files_root: Path = ROOT, today: date | None = None,
             staff_names: list[str] | None = None) -> dict:
    """묶음 목록 → 다음 버전 md 파일 + 버전 행(PENDING·비현행). 결과
    {'version_id', 'version', 'file_path', 'sections': {묶음 id: '3.4'}, 'warnings'}."""
    today = today or date.today()
    _check_inputs(clusters, view_scope, transfer_policy)
    _lock_document(conn, document_id)
    doc = conn.execute("select doc_code, doc_type from knowledge_documents where id = %s", (document_id,)).fetchone()
    if doc is None or doc[1] != 'GUIDE':
        raise CaseGuideError([f'임직원용 가이드가 아닌 문서입니다 (id {document_id})'])
    doc_code = doc[0]
    cur = conn.execute('select id, file_path from document_versions where document_id = %s and is_current',
                       (document_id,)).fetchone()
    if cur is None:
        raise CaseGuideError([f'{doc_code}에 현행 버전이 없습니다'])
    warnings: list[str] = []
    base_md = _base_md(resolve_file(cur[1], files_root), doc_code, warnings)
    version = _version(conn, document_id, draft_version_id)

    problems = []
    for c in clusters:
        b = c['draft_basis']
        if b.get('base_version_id') != cur[0]:
            problems.append(f"묶음 {c['id']}: 초안을 만든 뒤 현행 버전이 바뀌었습니다. 다시 맞춰 주세요")
        elif (b.get('base_md') or '').rstrip() != base_md.rstrip():
            problems.append(f"묶음 {c['id']}: 기준 원문이 지금 현행 파일과 다릅니다. 다시 맞춰 주세요")
    if already := sorted(r for c in clusters for r in c['receipts'] if r in receipts(base_md)):
        problems.append(f"이미 {doc_code} 현행에 반영된 접수 번호: {', '.join(already)}")
    if problems:
        raise CaseGuideError(problems)

    md, sections = _build(base_md, clusters, version, today, warnings)
    _check_result(base_md, md, doc_code, version, clusters, sections)
    warnings += sensitive_warnings(md, _added_lines(base_md, md),
                                   staff_names if staff_names is not None else _staff_names(conn))

    rel = (CASE_DIR / doc_code / f'{version}_{secrets.token_hex(3)}.md').as_posix()   # 쓸 때마다 다른 경로
    path = Path(files_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with open(path, 'x', encoding='utf-8', newline='') as f:     # 'x': 같은 이름이 있으면 덮어쓰지 않고 오류
            created = True
            f.write(md)
        if draft_version_id is not None:
            conn.execute("update document_versions set file_path = %s, file_format = 'MD', view_scope = %s, "
                         "transfer_policy = %s, ingest_status = 'PENDING', ingest_error = null, registered_by = %s, "
                         'registered_at = now() where id = %s',
                         (rel, view_scope, transfer_policy, actor_id, draft_version_id))
            vid = draft_version_id
        else:
            vid = conn.execute(
                'insert into document_versions (document_id, version, file_path, file_format, view_scope, '
                "transfer_policy, is_current, ingest_status, registered_by, registered_at) "
                "values (%s, %s, %s, 'MD', %s, %s, false, 'PENDING', %s, now()) returning id",
                (document_id, version, rel, view_scope, transfer_policy, actor_id)).fetchone()[0]
    except Exception:
        if created:                                        # 이번에 만든 파일만 (쓰다 실패한 것 포함). DB 는 API 가 되돌린다
            path.unlink(missing_ok=True)
        raise
    return {'version_id': vid, 'version': version, 'file_path': rel, 'sections': sections, 'warnings': warnings}


# ── 입력 검사 ─────────────────────────────────────────────────

def _check_inputs(clusters: list[dict], view_scope: str, transfer_policy: str) -> None:
    problems = []
    if view_scope not in VIEW_SCOPES:
        problems.append(f'없는 열람 범위 {view_scope}')
    if transfer_policy not in TRANSFER_POLICIES:
        problems.append(f'없는 전송 정책 {transfer_policy}')
    if not clusters:
        problems.append('조립할 묶음이 없습니다')
    for c in clusters:
        b, cid = c.get('draft_basis') or {}, c.get('id')
        if c.get('judgment') not in SUPPORTED:
            problems.append(f"묶음 {cid}: {c.get('judgment')} 판단은 조립하지 않습니다 "
                            '(새 가이드는 다음 작업, 매뉴얼 후보는 초안 없음)')
            continue
        if b.get('schema') != SCHEMA:
            problems.append(f"묶음 {cid}: draft_basis.schema 가 {b.get('schema')} 입니다 ({SCHEMA} 이어야 합니다)")
        if b.get('judgment') != c['judgment']:
            problems.append(f"묶음 {cid}: draft_basis 의 판단({b.get('judgment')})이 묶음 판단({c['judgment']})과 다릅니다")
        if not c.get('receipts'):
            problems.append(f'묶음 {cid}: 접수 번호가 없습니다')
        if c['judgment'] == 'CHANGE' and not b.get('target_section'):
            problems.append(f'묶음 {cid}: 바꿀 항목(target_section)이 없습니다')
        problems += [f'묶음 {cid}: {p}' for p in _fragment_problems(c.get('draft_md') or '')]
    ids = [c.get('id') for c in clusters]
    if dup := sorted({str(i) for i in ids if ids.count(i) > 1}):
        problems.append(f"묶음 id 가 겹칩니다: {', '.join(dup)}")
    every = [r for c in clusters for r in c.get('receipts') or []]
    if dup := sorted({r for r in every if every.count(r) > 1}):
        problems.append(f"접수 번호가 두 번 이상 들어 있습니다: {', '.join(dup)}")
    for c in clusters:
        s_no = (c.get('draft_basis') or {}).get('section_no')
        if c.get('judgment') in ADD_KINDS and s_no is not None and not (isinstance(s_no, str) and SECTION_RE.match(s_no)):
            problems.append(f"묶음 {c.get('id')}: section_no {s_no!r} 가 '3.N' 모양이 아닙니다")
    targets: dict[str, list] = {}
    for c in clusters:
        if c.get('judgment') == 'CHANGE' and (t := (c.get('draft_basis') or {}).get('target_section')):
            targets.setdefault(t, []).append(c.get('id'))
    problems += [f"같은 항목 {t}을 바꾸는 묶음이 여럿입니다 ({', '.join(map(str, ids))}). 하나로 합치거나 거절해 주세요"
                 for t, ids in targets.items() if len(ids) > 1]
    if problems:
        raise CaseGuideError(problems)


def _fragment_problems(md: str) -> list[str]:
    """조각 약속: 첫 줄이 '### 3.x 제목' (번호는 아무거나), 그 아래에 본문이 있고 (PR #357 검수 2), 다른 '###'·'##'·'#'
    제목 없음 (코드 블록 안은 괜찮음), 코드 울타리는 닫힘, 반영 표식 '해결 사례 반영 (' 은 쓰지 않음 (표식은 조립기가
    개정 이력에만 쓴다, 검수 4)."""
    lines = md.strip('\n').splitlines()
    if not lines or not HEAD_RE.match(lines[0].strip()):
        return ["조각 첫 줄이 '### 3.N 제목' 이 아닙니다"]
    problems, fence, body = [], '', False
    for line in lines[1:]:
        s = line.strip()
        if fence:
            fence = '' if s.startswith(fence) else fence
            body = True
        elif m := FENCE_RE.match(line):
            fence = m.group(1)
        elif re.match(r'^#{1,3}\s', s):
            problems.append(f'조각 안에 다른 제목 줄이 있습니다: {s[:40]}')
        elif s and not re.match(r'^#{4,}\s', s):
            body = True
    if fence:
        problems.append('조각의 코드 블록(```)이 닫히지 않았습니다')
    if not body:
        problems.append('조각에 본문이 없습니다 (제목·소제목만 있음)')
    if f'{MARK} (' in md:
        problems.append(f"조각에 반영 표식 '{MARK} (…)' 을 쓰지 않습니다 (등록 때 개정 이력에 자동으로 들어갑니다)")
    return problems


# ── 버전·번호 ─────────────────────────────────────────────────

def _version(conn, document_id: int, draft_version_id: int | None) -> str:
    if draft_version_id is None:
        versions = [v for (v,) in conn.execute('select version from document_versions where document_id = %s',
                                                (document_id,))]
        return next_version(versions)
    row = conn.execute('select document_id, version, file_path, is_current, activated_at from document_versions '
                       'where id = %s', (draft_version_id,)).fetchone()
    if row is None or row[0] != document_id:
        raise CaseGuideError([f'이어 쓸 버전 {draft_version_id}이 이 문서의 버전이 아닙니다'])
    if row[3] or row[4] is not None:
        raise CaseGuideError([f'이어 쓸 버전 {row[1]}은 현행이 된 적이 있어 다시 쓸 수 없습니다'])
    if not (row[2] or '').startswith(CASE_DIR.as_posix() + '/'):
        raise CaseGuideError([f'이어 쓸 버전 {row[1]}은 사례 초안이 아닙니다'])
    return row[1]


def _assign(base_md: str, clusters: list[dict]) -> dict:
    """더하는 조각의 항목 번호. 있는 번호(기준 md·draft_basis.section_no)를 먼저 잡고 없는 조각에 다음 번호."""
    taken = {f'3.{n}' for n in _item_numbers(base_md)}
    fixed: dict = {}
    problems = []
    for c in clusters:
        if c['judgment'] in ADD_KINDS and (s := c['draft_basis'].get('section_no')):
            if s in taken:
                problems.append(f"묶음 {c['id']}: 번호 {s}가 이미 현행 또는 다른 조각에 있습니다")
            taken.add(s)
            fixed[c['id']] = s
    if problems:
        raise CaseGuideError(problems)
    n = max((int(s.split('.')[1]) for s in taken), default=0)
    for c in clusters:
        if c['judgment'] in ADD_KINDS and c['id'] not in fixed:
            n += 1
            fixed[c['id']] = f'3.{n}'
    return fixed


# ── 조립 ──────────────────────────────────────────────────────

def _item_block(md: str, section_no: str) -> tuple[int, int] | None:
    """3장에서 '### <번호> ' 항목의 (시작, 끝). 끝 = 다음 '### 3.' 항목 또는 3장 끝."""
    end = _chapter3_end(md)
    heads = _item_heads(md)                                  # 코드 블록 안의 '### 3.' 은 항목이 아니다 (검수 1)
    for i, m in enumerate(heads):
        if m.group(1) == section_no:
            return m.start(), heads[i + 1].start() if i + 1 < len(heads) else end
    return None


def item_text(md: str, section_no: str) -> str | None:
    """3장 항목 하나의 원문 (draft_basis.target_md 와 비교하는 모양). 없으면 None."""
    span = _item_block(md, section_no)
    return md[span[0]:span[1]].strip('\n') if span else None


def _renumber(fragment: str, section_no: str) -> tuple[str, str]:
    """조각 첫 줄 번호를 바꾸고 (조각, 제목)."""
    lines = fragment.strip('\n').splitlines()
    m = HEAD_RE.match(lines[0].strip())
    title = m.group(2).strip()
    return '\n'.join([f'### {section_no} {title}', *lines[1:]]), title


def _props(fragment: str) -> dict:
    return {k: (m.group(1).strip() if (m := r.search(fragment)) else '') for k, r in PROP_RE.items()}


def _build(base_md: str, clusters: list[dict], version: str, today: date, warnings: list[str]) -> tuple[str, dict]:
    md = _set_version(base_md, version, warnings)
    notes, groups = [], []
    for c in (c for c in clusters if c['judgment'] == 'CHANGE'):          # 바꿔 끼우기 (번호가 그대로라 먼저)
        target = c['draft_basis']['target_section']
        now = item_text(md, target)
        if now is None:
            raise CaseGuideError([f"묶음 {c['id']}: 바꿀 항목 {target}이 현행에 없습니다. 이 묶음은 거절하고 필요하면 새 묶음으로"])
        if now.rstrip() != (c['draft_basis'].get('target_md') or '').strip('\n').rstrip():
            raise CaseGuideError([f"묶음 {c['id']}: 바꿀 항목 {target}이 초안을 만든 뒤 바뀌었습니다. 다시 맞춰 주세요"])
        fragment, title = _renumber(c['draft_md'], target)
        old_title, old_props = _renumber(now, target)[1], _props(now)
        start, end = _item_block(md, target)
        md = md[:start] + fragment.strip('\n') + '\n\n' + md[end:].lstrip('\n')
        p = _props(fragment)
        if _one_line(title) != _one_line(old_title):                    # 검수 3: 앞쪽 안내도 같은 값으로
            md = _set_toc(md, target, _one_line(title), warnings)
        if _one_line(title) != _one_line(old_title) or p != old_props:
            md = _set_table_row(md, _chapter3(md).end(),
                                [target, _one_line(title), p['문의 유형'], p['처리 구분'] or HANDLING, p['담당 부서']],
                                warnings)
        notes += [f'{MARK} ({r}): {target} {_one_line(title)} 변경' for r in c['receipts']]
        groups.append(_props(fragment)['담당 부서'])
    sections = _assign(base_md, clusters)
    added = sorted(((sections[c['id']], c) for c in clusters if c['judgment'] in ADD_KINDS),
                   key=lambda x: int(x[0].split('.')[1]))
    toc = []
    for section_no, c in added:
        fragment, title = _renumber(c['draft_md'], section_no)
        p = _props(fragment)
        md = _append_item(md, fragment)
        md = _add_table_row(md, _chapter3(md).end(),
                            [section_no, _one_line(title), p['문의 유형'], p['처리 구분'] or HANDLING, p['담당 부서']], warnings)
        toc.append((section_no, _one_line(title)))
        notes += [f'{MARK} ({r}): {section_no} {_one_line(title)}' for r in c['receipts']]
        groups.append(p['담당 부서'])
    md = _add_toc(md, toc, warnings)
    group = next((g for g in groups if g), '서비스데스크')
    md = _add_history(md, version, today, group, notes, warnings)
    return md, sections


def _check_result(base_md: str, md: str, doc_code: str, version: str, clusters: list[dict], sections: dict) -> None:
    """조립한 md 를 파서·청커로 다시 읽어 검사: 읽힘·문서 번호·버전·청크 검증·현행 항목 그대로·접수 번호 표식."""
    meta, chunks = _parse_text(md)
    problems = []
    if meta.get('doc_no') and meta['doc_no'] != doc_code:
        problems.append(f"문서 번호가 {meta['doc_no']}입니다 ({doc_code}이어야 합니다)")
    if meta.get('version') and meta['version'] != version:
        problems.append(f"버전이 {meta['version']}입니다 ({version}이어야 합니다)")
    problems += validate(chunks)
    base = {c.section_no for c in _parse_text(base_md)[1] if c.chunk_type == 'item'}
    if missing := sorted(base - {c.section_no for c in chunks if c.chunk_type == 'item'}):
        problems.append(f"현행 항목이 빠졌습니다: {', '.join(missing)}")
    have = receipts(md)
    want = {r for c in clusters for r in c['receipts']}
    if lost := sorted(want - have):
        problems.append(f"접수 번호 표식이 없습니다: {', '.join(lost)}")
    if extra := sorted(have - want - receipts(base_md)):
        problems.append(f"요청하지 않은 반영 표식이 생겼습니다: {', '.join(extra)}")
    bodies = {c.section_no: c.body for c in chunks if c.chunk_type == 'item'}
    if empty := sorted(s for s in sections.values() if not (bodies.get(s) or '').strip()):
        problems.append(f"새 항목이 항목으로 읽히지 않거나 본문이 없습니다: {', '.join(empty)}")
    if problems:
        raise CaseGuideError(problems)
