"""초안 만들 때의 기준 (해결 사례 가이드화 기획 v4, `작업대/가이드화/draft_basis_구조_초안_20261108.md` 6장 ③).

주간 분석 워커(M4)가 묶음 초안을 만들 때 부른다. 돌려준 `draft_basis`(와 새 가이드면 뼈대 `draft_md`)를 워커가 묶음 표에
그대로 저장한다. **DB 에 쓰지 않고 commit 도 하지 않는다** (워커가 묶음·티켓 상태를 한 트랜잭션으로 바꾸게).

    out = open_basis(conn, 'ADD_ITEM', document_id=7)                         # 항목 추가·SEC
    out = open_basis(conn, 'CHANGE', document_id=7, target_section='3.3')      # 변경
    out = open_basis(conn, 'NEW_GUIDE', category_code='NET', title='…', fragments=[조각, …],
                     overview='1장 본문', precheck='2장 본문')                         # 새 가이드 뼈대
    # out = {'draft_basis': {...}, 'draft_md': None | 뼈대, 'warnings': [...]}
    frag, warnings = ticket_fragment(conn, ticket_id)                          # SEC 직접 검토: 티켓 글 → 조각 (AI 없음)
    warnings = ticket_warnings(conn, [ticket_id, …])                           # 묶음 티켓의 짧은 처리·재처리 경고 (Q8)

`draft_basis` 의 키·뜻은 구조 초안 2장. 등록 때 `assemble()` 이 이 값으로 현행과 비교한다 (기준 버전·기준 원문·변경 항목 원문).
"""
from __future__ import annotations

import re
from pathlib import Path

from app.rag.ingest import ROOT
from app.rag.ingest.upload import resolve_file

from . import (HANDLING, MARK, SHORT_NOTE, CaseGuideError, _base_md, _find, _item, _one_line, _read_ticket, _reopened, josa,
               receipts)
from .assemble import FENCE_RE, REQUIRED as _REQUIRED, SCHEMA, TODO, _fragment_problems, _props, _renumber, item_text

REQUIRED = list(_REQUIRED)                                 # 새 가이드 등록 전에 꼭 채울 장 (김현나 Q9)
CONTACT_HEAD = re.compile(r'^## 6\. 문의처[ \t]*$', re.M)


def open_basis(conn, judgment: str, *, document_id: int | None = None, target_section: str | None = None,
               receipts_: list[str] | tuple = (), category_code: str | None = None, title: str | None = None,
               fragments: list[str] | tuple = (), files_root: Path = ROOT, overview: str | None = None,
               precheck: str | None = None) -> dict:
    """판단별 초안 기준. 결과 {'draft_basis', 'draft_md', 'warnings'}. 안 되면 CaseGuideError.
    새 가이드의 overview·precheck 는 AI 가 쓴 1장·2장 본문 (없으면 `(작성 필요)`, 형식이 틀리면 그 장만 자리 표시 + 경고)."""
    warnings: list[str] = []
    if judgment == 'MANUAL_CANDIDATE':
        return {'draft_basis': None, 'draft_md': None, 'warnings': []}          # 초안 없음 (관리자가 매뉴얼에 직접)
    if judgment == 'NEW_GUIDE':
        md = new_guide(conn, category_code, title, list(fragments), files_root, warnings,
                       overview=overview, precheck=precheck)
        return {'draft_basis': {'schema': SCHEMA, 'judgment': judgment, 'base_version_id': None, 'base_md': None,
                                'category_code': category_code, 'required': list(REQUIRED)},
                'draft_md': md, 'warnings': warnings}
    if judgment not in ('ADD_ITEM', 'SEC_MANUAL', 'CHANGE'):
        raise CaseGuideError([f'모르는 판단 {judgment}'])
    if document_id is None:
        raise CaseGuideError(['넣을 문서(document_id)가 없습니다'])
    doc = conn.execute('select doc_code, doc_type from knowledge_documents where id = %s', (document_id,)).fetchone()
    if doc is None or doc[1] != 'GUIDE':
        raise CaseGuideError([f'임직원용 가이드가 아닌 문서입니다 (id {document_id})'])
    cur = conn.execute('select id, file_path from document_versions where document_id = %s and is_current',
                       (document_id,)).fetchone()
    if cur is None:
        raise CaseGuideError([f'{doc[0]}에 현행 버전이 없습니다'])
    base_md = _base_md(resolve_file(cur[1], files_root), doc[0], warnings)
    if done := sorted(r for r in receipts_ if r in receipts(base_md)):
        warnings.append(f"이미 {doc[0]} 현행에 반영된 접수 번호입니다: {', '.join(done)}")
    basis = {'schema': SCHEMA, 'judgment': judgment, 'base_version_id': cur[0], 'base_md': base_md}
    if judgment == 'CHANGE':
        if not target_section:
            raise CaseGuideError(['바꿀 항목(target_section)이 없습니다'])
        target_md = item_text(base_md, target_section)
        if target_md is None:
            raise CaseGuideError([f'{doc[0]} 현행에 항목 {josa(target_section, '이/가')} 없습니다'])
        basis |= {'target_section': target_section, 'target_md': target_md}
    else:
        basis['section_no'] = None                         # 등록 때 assemble 이 정하고 API 가 저장
    return {'draft_basis': basis, 'draft_md': None, 'warnings': warnings}


def ticket_warnings(conn, ticket_ids: list[int] | tuple) -> list[str]:
    """묶음의 티켓별 검토 경고 (M4 Q8: 재처리·짧은 처리는 티켓별로 검사해 묶음 경고로 모은다). 워커가 묶음을 만들 때
    불러 `review_info.warnings` 에 넣는다 (프론트가 이 배열을 보여 준다). 1건 가이드화·SEC 조각과 같은 기준
    (`SHORT_NOTE`, FIN→WIP 횟수). 앞선 처리 결과·남은 증상 원문은 넣지 않는다 (TK-08 이력 위치만).
    티켓 순서대로, 같은 id 는 한 번. 없는 티켓 id 는 CaseGuideError. DB 읽기만, commit 하지 않는다."""
    out, missing = [], []
    for tid in dict.fromkeys(ticket_ids):
        try:
            t = _read_ticket(conn, tid)
        except ValueError:
            missing.append(str(tid))
            continue
        out += _ticket_warnings(conn, tid, t)
    if missing:
        raise CaseGuideError([f"없는 티켓 id: {', '.join(missing)}"])
    return out


def _ticket_warnings(conn, ticket_id: int, t: dict) -> list[str]:
    note = (t['resolution_note'] or '').strip()
    warnings = []
    if len(note) < SHORT_NOTE:
        warnings.append(f"{t['receipt_no']}: 해결 내용이 짧습니다 ({len(note)}자). 초안의 조치 방법이 충분한지 확인하세요")
    if reopened := _reopened(conn, ticket_id):
        warnings.append(f"{t['receipt_no']}: 다시 처리된 접수입니다 (재처리 {reopened}회). 앞선 처리는 TK-08 이력에서 확인하세요")
    return warnings


def ticket_fragment(conn, ticket_id: int) -> tuple[str, list[str]]:
    """SEC 직접 검토: 티켓 글을 틀에 옮긴 항목 조각 (`### 3.N 제목`, AI 없음). 1건 가이드화와 같은 틀·경고 기준."""
    t = _read_ticket(conn, ticket_id)
    problems = []
    if t['work_status'] != 'CLS':
        problems.append(f"해결 확인(CLS)된 티켓만 가이드로 만듭니다: {josa(t['receipt_no'], '은/는')} {t['work_status']}")
    if not (t['resolution_note'] or '').strip():
        problems.append(f"{t['receipt_no']}에 해결 내용(resolution_note)이 없습니다")
    if problems:
        raise CaseGuideError(problems)
    warnings = [f"{t['receipt_no']}: 티켓 글을 그대로 옮겼습니다. 임직원이 따라 할 수 있게 다듬어 주세요",
                *_ticket_warnings(conn, ticket_id, t)]
    title = _one_line(t['summary']) or _one_line(t['symptom']) or '해결 사례'
    fragment = _item('3.N', title, t)
    # 티켓 글을 그대로 옮기므로 등록 때의 조각 약속에 걸릴 수 있다 (예: 처리 글에 '해결 사례 반영 (' 문구). 내용을 조용히
    # 지우지 않고, 등록 전에 관리자가 고칠 것으로 경고한다 — 고치지 않으면 assemble 이 거부한다 (#363 재검수 3)
    warnings += [f"{t['receipt_no']}: 등록 전에 고쳐 주세요 — {p}" for p in _fragment_problems(fragment)]
    return fragment, warnings


# ── 새 가이드 뼈대 ─────────────────────────────────────────────

def new_guide(conn, category_code: str | None, title: str | None, fragments: list[str], files_root: Path,
              warnings: list[str], *, overview: str | None = None, precheck: str | None = None) -> str:
    """새 가이드 뼈대 md (M4 Q9): v1.0, 문서 번호는 비워 둠(등록 때 DC-02 문서 번호로), 1장 개요·2장 먼저 확인할
    사항은 AI 초안(overview·precheck, 11.09 M4 요청) 또는 `(작성 필요)`, 2장 끝에 증상별 바로가기 표, 3장 조각들(3.1부터),
    4·5장·부록은 제목만(비면 등록 때 장째 뺌), 6장 문의처는 같은 분류 현행 가이드에서 복사."""
    problems = []
    name = conn.execute('select name from categories where code = %s', (category_code,)).fetchone() if category_code else None
    if name is None:
        problems.append(f'없는 분류 {category_code}')
    problems += title_problems(title)
    if name is not None:
        problems += title_problems(name[0], '분류 이름')                  # DB 값도 머리말·본문 한 줄 (#363 재검수)
    if not fragments:
        problems.append('3장 항목 조각이 없습니다')
    problems += [f'조각 {i}: {p}' for i, f in enumerate(fragments, 1) for p in _fragment_problems(f)]
    if problems:
        raise CaseGuideError(problems)
    return skeleton(title.strip(), category_code, name[0], fragments, _contact(conn, category_code, files_root, warnings),
                    overview=chapter_body(overview, '1장 개요', warnings),
                    precheck=chapter_body(precheck, '2장 먼저 확인할 사항', warnings, reserved=(JUMP_TITLE,)))


JUMP_TITLE = '증상별 바로가기'
JUMP_HEAD = f'#### {JUMP_TITLE}'                            # 2장 끝에 뼈대가 붙이는 표의 소제목
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
INLINE_MARK = re.compile(r'(\*\*|__|\*|_|`)')


def _heading_text(text: str) -> str:
    """제목 글을 비교용으로: 굵게·기울임·코드 표시를 빼고 공백(탭 포함)을 하나로."""
    return ' '.join(INLINE_MARK.sub('', text).split())


def chapter_body(text: str | None, name: str, warnings: list[str], reserved: tuple[str, ...] = ()) -> str | None:
    """AI 가 쓴 장 본문 → 뼈대에 넣을 글. 없거나 빈 글이면 None (자리 표시). 형식이 틀리면 None + 경고 — 장 경계가
    깨지지 않게: 코드 블록 밖 `#`·`##`·`###` 제목 금지(`####` 이하 소제목·굵은 글씨·목록·표는 됨), 코드 블록은 닫힘,
    반영 표식 문구 금지, reserved 제목 글 금지 (2장의 증상별 바로가기는 뼈대가 붙인다. 공백·굵게 표기를 정리해 비교).
    경고에는 원문을 넣지 않는다 — 장 이름·줄 번호·문제 종류만 (거부한 글의 민감값이 경고로 새지 않게, PR #384 검수 1)."""
    body = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n').rstrip()
    if not body.strip():
        return None
    reserved_titles = {_heading_text(r) for r in reserved}
    problems, fence = [], ''
    for n, line in enumerate(body.splitlines(), 1):
        s = line.strip()
        if fence:
            fence = '' if s.startswith(fence) else fence
        elif m := FENCE_RE.match(line):
            fence = m.group(1)
        elif h := HEADING_RE.match(s):
            if len(h.group(1)) <= 3:
                problems.append(f'{n}번째 줄에 쓸 수 없는 제목({h.group(1)})')
            elif _heading_text(h.group(2)) in reserved_titles:
                problems.append(f'{n}번째 줄에 뼈대가 붙이는 소제목')
    if fence:
        problems.append('닫히지 않은 코드 블록')
    if f'{MARK} (' in body:
        problems.append('반영 표식 문구')
    if problems:
        warnings.append(f"{name} 초안을 넣지 않고 '{TODO}' 로 두었습니다 ({', '.join(problems)}). 관리자가 채워 주세요")
        return None
    return body


def title_problems(title: str | None, what: str = '새 가이드 제목') -> list[str]:
    """머리말·본문에 넣을 한 줄 값: 줄바꿈·제어 문자 없음 (본문 '# 제목' 아래로 장이 끼어들지 않게, PR #361 검수 2).
    줄 나눔은 md 파서와 같은 str.splitlines 기준 (U+0085·U+2028·U+2029 포함, #363 재검수 1), 제어 문자는 C0·DEL·C1.
    머리말에는 바깥 따옴표만 붙여 그대로 쓴다 (md 파서가 바깥 따옴표만 벗기므로 다시 읽으면 같은 값, 검수 1)."""
    if not (title or '').strip():
        return [f"{josa(what, '이/가')} 없습니다"]
    if len(title.splitlines()) != 1 or re.search(r'[\x00-\x1f\x7f-\x9f  ]', title):
        return [f"{josa(what, '은/는')} 한 줄이어야 합니다 (줄바꿈·제어 문자 없이)"]
    return []


def skeleton(title: str, category_code: str, category_name: str, fragments: list[str], contact: str, *,
             overview: str | None = None, precheck: str | None = None) -> str:
    """뼈대 md (DB 없이). contact: 6장 본문 (비면 자리 표시). title 은 title_problems 를 통과한 한 줄.
    overview·precheck: 1장·2장 본문 (chapter_body 를 거친 글, None 이면 자리 표시). 2장은 본문 아래에 바로가기 표."""
    items, rows, jumps, toc = [], [], [], []
    for n, f in enumerate(fragments, 1):
        section = f'3.{n}'
        body, item_title = _renumber(f, section)
        p = _props(body)
        items.append(body.strip('\n'))
        rows.append([section, _one_line(item_title), p['문의 유형'], p['처리 구분'] or HANDLING, p['담당 부서']])
        jumps.append([_one_line(item_title), section, p['처리 구분'] or HANDLING])
        toc.append(f'  - {section} {_one_line(item_title)}')
    q = lambda s: f'"{s}"'                                 # noqa: E731  머리말 값: 바깥 따옴표만 (md 파서가 그것만 벗김)
    table = lambda head, rs: '\n'.join(                   # noqa: E731
        ['| ' + ' | '.join(head) + ' |', '| ' + ' | '.join('---' for _ in head) + ' |',
         *('| ' + ' | '.join(c.replace('|', r'\|') for c in r) + ' |' for r in rs)])
    return '\n'.join([
        '---', 'doc_no: ""', f'title: {q(title)}', f'category: {q(category_code)}', f'category_name: {q(category_name)}',
        'doc_type: "guide"', 'version: "v1.0"', '---', '',
        f'# {title}', '', f'> 가상 ICT 기업 임직원 IT 안내 · {category_name}', '',
        '## 목차', '', '- 1. 개요', '- 2. 먼저 확인할 사항', '- 3. 증상별 조치 방법', *toc, '- 4. 자주 묻는 질문',
        '- 5. 주의사항', '- 6. 문의처', '- 부록 · 관련 문서 · 용어', '- 개정 이력', '',
        '## 1. 개요', '', overview or TODO, '',
        '## 2. 먼저 확인할 사항', '', precheck or TODO, '', JUMP_HEAD, '',
        table(['겪고 있는 증상', '볼 곳', '처리 구분'], jumps), '',
        '## 3. 증상별 조치 방법', '', table(['번호', '제목', '문의 유형', '처리 구분', '담당 부서'], rows), '',
        '\n\n'.join(items), '',
        '## 4. 자주 묻는 질문', '', '## 5. 주의사항', '',
        '## 6. 문의처', '', contact.strip('\n') or TODO, '',
        '## 부록 · 관련 문서 · 용어', '',
        '## 개정 이력', '', table(['버전', '개정일', '작성자', '변경 내용'], []), ''])


def _contact(conn, category_code: str, files_root: Path, warnings: list[str]) -> str:
    """6장 문의처 본문: 같은 분류 현행 가이드 → 없으면 다른 분류 현행 가이드 (27종 모두 같은 공통 표). 없으면 경고·빈칸."""
    rows = conn.execute(
        "select d.doc_code, v.file_path from knowledge_documents d join document_versions v on v.document_id = d.id "
        "and v.is_current where d.doc_type = 'GUIDE' and d.is_active order by (d.category_code = %s) desc, d.doc_code",
        (category_code,)).fetchall()
    for doc_code, path in rows:
        try:
            md = _base_md(resolve_file(path, files_root), doc_code, [])
        except (CaseGuideError, OSError):
            continue
        body = contact_body(md)
        if body.strip() and body.strip() != TODO:          # 빈 장·공백·자리 표시뿐이면 다음 후보 (#361 검수 3, #363 재검수 2)
            return body
    warnings.append('6장 문의처를 복사할 현행 가이드를 찾지 못했습니다. 관리자가 채워 주세요')
    return ''


def contact_body(md: str) -> str:
    """'## 6. 문의처' 장 본문 (코드 블록 밖 제목만 경계로, PR #361 검수 4). 없으면 ''."""
    head = _find(CONTACT_HEAD, md)
    if not head:
        return ''
    after = _find(r'^## ', md, head[0].end())
    return md[head[0].end():after[0].start() if after else len(md)].strip('\n')
