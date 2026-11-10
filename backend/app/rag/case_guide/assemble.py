"""묶음 등록용 조립 (해결 사례 가이드화 기획 v4). 입력·조립·거부 조건은 같은 폴더 README.md 의 "묶음 등록 조립" 절.

등록 API 가 묶음 하나의 등록 요청을 받으면, 그 문서에 이어 쓸 대기 버전이 있으면 [그 버전 묶음(거절 제외) + 이번 묶음],
없으면 [이번 묶음] 을 계산해 이 함수에 넘긴다. 이 함수는 **현행 md + 조각들** 로 문서를 처음부터 다시 조립한다.

    out = assemble(conn, document_id, clusters, draft_version_id, view_scope='ALL', transfer_policy='ALLOWED', actor_id=1)
    # API: 같은 트랜잭션에서 묶음 registered_version_id·section_no 저장, 운영 기록, commit → submit_ingest

- 묶음 하나 = {'id', 'judgment', 'draft_md', 'draft_basis', 'receipts'}. 판단은 ADD_ITEM·SEC_MANUAL(항목 하나 더함),
  CHANGE(항목 하나를 관리자가 고친 조각으로 바꿔 끼움), NEW_GUIDE(현행이 없는 문서의 첫 버전 — 관리자가 채운 뼈대 전체,
  묶음 하나만. 새 가이드 등록 조건: 1~3장 필수·`(작성 필요)` 남으면 거부, 빈 4·5장·부록은 장째 뺌, 문서 번호·v1.0 채움).
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
from app.rag.parser.md_parser import FRONT_RE

from . import (CASE_DIR, HANDLING, MARK, TRANSFER_POLICIES, VIEW_SCOPES, CaseGuideError, _add_history, _add_table_row, josa,
               _add_toc, _added_lines, _append_item, _base_md, _chapter3, _chapter3_end, _find, _item_heads, _item_numbers,
               _one_line, _parse_text, _set_table_row, _set_toc, _set_version, _staff_names, next_version, receipts,
               sensitive_warnings)

SCHEMA = 1                                                 # draft_basis.schema
ADD_KINDS = ('ADD_ITEM', 'SEC_MANUAL')                     # 3장 끝에 항목 하나 더함
SUPPORTED = (*ADD_KINDS, 'CHANGE', 'NEW_GUIDE')
TODO = '(작성 필요)'                                        # 새 가이드 뼈대의 자리 표시 (줄 하나가 정확히 이것)
REQUIRED = ('1', '2', '3')                                 # 새 가이드 등록 전에 꼭 채울 장
OPTIONAL = ('4', '5', '부록')                               # 비어 있으면 장째 뺀다 (빈 장이 검색 조각이 되지 않게)
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
    warnings: list[str] = []
    if clusters[0]['judgment'] == 'NEW_GUIDE':
        if cur is not None:                                # 새 가이드는 첫 버전만 (그새 현행이 생겼으면 항목 추가로)
            raise CaseGuideError([f'{doc_code}에 이미 현행 버전이 있습니다. 새 가이드 묶음은 거절하고 항목 추가로 만들어 주세요'])
        version = _first_version(conn, document_id, draft_version_id)
        category =conn.execute('select category_code from knowledge_documents where id = %s', (document_id,)).fetchone()[0]
        if category != clusters[0]['draft_basis'].get('category_code'):
            warnings.append(f"새 가이드 분류({clusters[0]['draft_basis'].get('category_code')})와 등록한 문서 분류({category})가 다릅니다")
        base_md, sections = '', {}
        md = _build_new_guide(clusters[0], doc_code, version, today, warnings)
        return _write(conn, document_id, doc_code, version, base_md, md, clusters, sections, draft_version_id, warnings,
                      view_scope=view_scope, transfer_policy=transfer_policy, actor_id=actor_id, files_root=files_root,
                      staff_names=staff_names)
    if cur is None:
        raise CaseGuideError([f'{doc_code}에 현행 버전이 없습니다'])
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
    return _write(conn, document_id, doc_code, version, base_md, md, clusters, sections, draft_version_id, warnings,
                  view_scope=view_scope, transfer_policy=transfer_policy, actor_id=actor_id, files_root=files_root,
                  staff_names=staff_names)


def _write(conn, document_id, doc_code, version, base_md, md, clusters, sections, draft_version_id, warnings, *,
           view_scope, transfer_policy, actor_id, files_root, staff_names) -> dict:
    """조립한 md 검사 → 새 경로에 파일 → 버전 행 (PENDING·비현행). commit 하지 않는다."""
    _check_result(base_md, md, doc_code, version, clusters, sections)
    warnings += sensitive_warnings(md, _added_lines(base_md, md),           # 새 가이드는 기준이 없어 문서 전체
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
    if any(c.get('judgment') == 'NEW_GUIDE' for c in clusters) and len(clusters) != 1:
        problems.append('새 가이드 묶음은 혼자 등록합니다 (한 문서의 첫 버전에 하나만, 다른 묶음과 섞지 않음)')
    for c in clusters:
        b, cid = c.get('draft_basis') or {}, c.get('id')
        if c.get('judgment') not in SUPPORTED:
            problems.append(f"묶음 {cid}: {c.get('judgment')} 판단은 조립하지 않습니다 (매뉴얼 후보는 초안 없음)")
            continue
        if b.get('schema') != SCHEMA:
            problems.append(f"묶음 {cid}: draft_basis.schema 가 {b.get('schema')} 입니다 ({SCHEMA} 이어야 합니다)")
        if b.get('judgment') != c['judgment']:
            problems.append(f"묶음 {cid}: draft_basis 의 판단({b.get('judgment')})이 묶음 판단({c['judgment']})과 다릅니다")
        if not c.get('receipts'):
            problems.append(f'묶음 {cid}: 접수 번호가 없습니다')
        if c['judgment'] == 'CHANGE' and not b.get('target_section'):
            problems.append(f'묶음 {cid}: 바꿀 항목(target_section)이 없습니다')
        if c['judgment'] != 'NEW_GUIDE':                   # 새 가이드는 조각이 아니라 문서 전체 (_build_new_guide 가 검사)
            problems += [f'묶음 {cid}: {p}' for p in _fragment_problems(c.get('draft_md') or '')]
        elif not (c.get('draft_md') or '').strip():
            problems.append(f'묶음 {cid}: 새 가이드 초안 글이 없습니다')
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
    problems += [f"같은 항목 {josa(t, '을/를')} 바꾸는 묶음이 여럿입니다 ({', '.join(map(str, ids))}). 하나로 합치거나 거절해 주세요"
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
        return next_version(versions) if versions else 'v1.0'           # 버전이 하나도 없는 새 문서는 v1.0
    row = conn.execute('select document_id, version, file_path, is_current, activated_at from document_versions '
                       'where id = %s', (draft_version_id,)).fetchone()
    if row is None or row[0] != document_id:
        raise CaseGuideError([f'이어 쓸 버전 {josa(draft_version_id, '이/가')} 이 문서의 버전이 아닙니다'])
    if row[3] or row[4] is not None:
        raise CaseGuideError([f'이어 쓸 버전 {josa(row[1], '은/는')} 현행이 된 적이 있어 다시 쓸 수 없습니다'])
    if not (row[2] or '').startswith(CASE_DIR.as_posix() + '/'):
        raise CaseGuideError([f'이어 쓸 버전 {josa(row[1], '은/는')} 사례 초안이 아닙니다'])
    return row[1]


def _first_version(conn, document_id: int, draft_version_id: int | None) -> str:
    """새 가이드의 버전: 문서에 버전이 하나도 없으면 v1.0, 이 사례의 대기 버전을 다시 조립하면 그 버전. 다른 버전(업로드
    초안·실패한 버전 등)이 있으면 거부 — 다음 번호로 넘어가 '첫 버전 v1.0' 이 조용히 바뀌지 않게 (PR #370 검수 3)."""
    others = [v for (vid, v) in conn.execute('select id, version from document_versions where document_id = %s order by id',
                                             (document_id,)) if vid != draft_version_id]
    if others:
        raise CaseGuideError([f"이 문서에 이미 다른 버전이 있습니다 ({', '.join(others)}). 새 가이드는 버전이 없는 문서의 "
                              '첫 버전만 만듭니다. 그 버전을 정리하거나 새 가이드 묶음은 거절해 주세요'])
    return 'v1.0' if draft_version_id is None else _version(conn, document_id, draft_version_id)


def _assign(base_md: str, clusters: list[dict]) -> dict:
    """더하는 조각의 항목 번호. 있는 번호(기준 md·draft_basis.section_no)를 먼저 잡고 없는 조각에 다음 번호."""
    taken = {f'3.{n}' for n in _item_numbers(base_md)}
    fixed: dict = {}
    problems = []
    for c in clusters:
        if c['judgment'] in ADD_KINDS and (s := c['draft_basis'].get('section_no')):
            if s in taken:
                problems.append(f"묶음 {c['id']}: 번호 {josa(s, '이/가')} 이미 현행 또는 다른 조각에 있습니다")
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
            raise CaseGuideError([f"묶음 {c['id']}: 바꿀 항목 {josa(target, '이/가')} 현행에 없습니다. 이 묶음은 거절하고 필요하면 새 묶음으로"])
        if now.rstrip() != (c['draft_basis'].get('target_md') or '').strip('\n').rstrip():
            raise CaseGuideError([f"묶음 {c['id']}: 바꿀 항목 {josa(target, '이/가')} 초안을 만든 뒤 바뀌었습니다. 다시 맞춰 주세요"])
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
    if not meta.get('doc_no'):
        problems.append('머리말에 문서 번호(doc_no)가 없습니다')
    if meta.get('doc_no') and meta['doc_no'] != doc_code:
        problems.append(f"문서 번호가 {meta['doc_no']}입니다 ({doc_code}이어야 합니다)")
    if not meta.get('version'):                            # 없으면 통과시키지 않는다 (PR #370 검수 4)
        problems.append('머리말에 버전(version)이 없습니다')
    elif meta['version'] != version:
        problems.append(f"버전이 {meta['version']}입니다 ({version}이어야 합니다)")
    problems += validate(chunks)
    base = {c.section_no for c in _parse_text(base_md)[1] if c.chunk_type == 'item'} if base_md.strip() else set()
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


# ── 새 가이드 (NEW_GUIDE) ──────────────────────────────────────

CHAPTER_HEAD = re.compile(r'^## (.+?)[ \t]*$', re.M)


def _chapter_key(title: str) -> str:
    m = re.match(r'^(\d+)\.', title)
    return m.group(1) if m else ('부록' if title.startswith('부록') else title)


def _chapters(md: str) -> list[tuple[str, str, int, int, int]]:
    """코드 블록 밖 '## ' 장들: (키 '1'·'부록'…, 제목, 제목 시작, 본문 시작, 끝)."""
    heads = _find(CHAPTER_HEAD, md)
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(md)
        out.append((_chapter_key(m.group(1)), m.group(1), m.start(), m.end(), end))
    return out


def _build_new_guide(c: dict, doc_code: str, version: str, today: date, warnings: list[str]) -> str:
    """관리자가 채운 새 가이드 뼈대 → 등록할 v1.0 md. 문서 번호·버전 채움, 빈 4·5장·부록 장째 빼기(목차 줄도),
    필수 1~3장·자리 표시·3장 항목 검사, 개정 이력 표식 (접수 번호마다). 안 되면 CaseGuideError."""
    md = c['draft_md'].replace('\r\n', '\n')
    problems = []
    if receipts(md) or f'{MARK} (' in md:
        problems.append(f"초안에 반영 표식 '{MARK} (…)' 을 쓰지 않습니다 (등록 때 개정 이력에 자동으로 들어갑니다)")
    front = FRONT_RE.match(md)                             # md 파서와 같은 머리말 규칙. 고치는 건 이 안에서만 (PR #370 검수 4)
    if front is None:
        problems.append('문서 맨 앞에 머리말(--- … ---)이 없습니다 (뼈대 머리말을 지우지 마세요)')
    else:
        problems += [f'머리말에 {k} 줄이 없습니다 (뼈대 머리말을 지우지 마세요)' for k in ('doc_no', 'version')
                     if not re.search(rf'^{k}:', front.group(1), re.M)]
    if problems:
        raise CaseGuideError(problems)
    head = re.sub(r'^doc_no:.*$', f'doc_no: "{doc_code}"', front.group(1), count=1, flags=re.M)
    head = re.sub(r'^version:.*$', f'version: "{version}"', head, count=1, flags=re.M)
    md = md[:front.start(1)] + head + md[front.end(1):]

    dropped = []
    for key, title, start, body, end in reversed(_chapters(md)):          # 뒤에서부터 지워야 앞 위치가 안 바뀐다
        if key in OPTIONAL and not md[body:end].strip():
            md = md[:start] + md[end:]
            dropped.append(title)
    for title in dropped:                                  # 목차 줄은 장을 다 지운 뒤에 (목차가 앞에 있어 위치가 밀린다)
        toc = next(iter(_find(re.compile(rf'^\s*- {re.escape(title)}[ \t]*$', re.M), md)), None)
        if toc is not None:
            md = md[:toc.start()] + md[toc.end() + 1:]

    found = [(key, md[body:end]) for key, _t, _s, body, end in _chapters(md)]
    keys = [k for k, _ in found]
    if dup := sorted({k for k in keys if keys.count(k) > 1}):   # 같은 장이 둘이면 앞 장 검사를 놓친다 (PR #370 검수 2)
        problems.append(f"같은 장이 두 번 이상 있습니다: {', '.join(f'{k}장' if k[0].isdigit() else k for k in dup)}")
    chapters = dict(found)
    for key in REQUIRED:
        body = chapters.get(key)
        content = [ln for ln in (body or '').splitlines() if ln.strip() and not ln.lstrip().startswith('#')]
        if body is None:
            problems.append(f'{key}장이 없습니다')
        elif not content:
            problems.append(f'{key}장에 내용이 없습니다')
    todo = list(dict.fromkeys(key for key, body in found if any(ln.strip() == TODO for ln in body.splitlines())))
    if todo:
        problems.append(f"'{TODO}' 자리가 남아 있습니다: {', '.join(f'{k}장' if k[0].isdigit() else k for k in todo)}")
    if '3' in chapters and not dup:
        heads = [m.group(1) for m in _item_heads(md)]
        bodies = {ch.section_no for ch in _parse_text(md)[1] if ch.chunk_type == 'item' and (ch.body or '').strip()}
        if not heads:
            problems.append('3장에 항목(### 3.N)이 없습니다')
        elif dup_items := sorted({s for s in heads if heads.count(s) > 1}, key=lambda s: int(s.split('.')[1])):
            # 번호가 겹치면 어느 제목의 본문인지 모른다 — 빈 항목이 숨는다 (PR #370 재검수 1)
            problems.append(f"같은 항목 번호가 두 번 이상 있습니다: {', '.join(dup_items)}")
        elif empty := [s for s in heads if s not in bodies]:        # 제목만 있는 항목은 검색되지 않는다 (PR #370 검수 1)
            problems.append(f"본문이 없는 항목이 있습니다: {', '.join(empty)}")
    if problems:
        raise CaseGuideError(problems)
    group = next((g for g in (_props(md[h.start():])['담당 부서'] for h in _item_heads(md)) if g), '서비스데스크')
    return _add_history(md, version, today, group, [f'{MARK} ({r}): 새 가이드' for r in c['receipts']], warnings)
