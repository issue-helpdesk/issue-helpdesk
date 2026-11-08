"""해결 사례 가이드화 (WBS M2-3-2, SRS GUIDE-03). 사용법은 README.md.

해결된 티켓(CLS, 문의자가 해결을 확인함) 하나를 그 문의 유형을 다루는 **기존 가이드의 다음 버전 초안**으로 만든다.
현행 md 를 복사해 3장 끝에 새 항목 3.N, 목차 한 줄, 개정 이력 한 줄을 더하고 버전을 올린다 (v2.0 → v2.1).
현행이 docx·pptx·pdf 면 파싱 결과를 가이드 md 로 바꿔 기준으로 쓴다 (parser/to_md.py). 새 버전은 늘 md 다.
관리자가 고친 가이드를 새 버전으로 업로드한 것과 같은 모양이라, 그 뒤는 업로드 적재(M2-3-1)와 같다.

    d = draft(conn, ticket_id)                      # 초안 md + 경고. DB 에 쓰지 않는다
    problems, warnings = check(d, md, staff_names)  # 관리자가 고친 md 다시 검사
    vid = register(conn, d, md, admin_id, view_scope='ALL', transfer_policy='ALLOWED')
                                                    # 파일 쓰기 + 버전 행(PENDING·비현행, 관리자가 고른 정책) + 감사 로그, commit
    ingest_version(conn, vid, embedder)             # M2-3-1 → DONE = 초안 (검색에 안 나온다)
    activate(conn, vid, admin_id); conn.commit()    # 관리자 승인 (DC-09) → 현행 = 검색됨

Draft 는 만들 때의 기준(현행·이어 쓰던 초안·기준 md)을 담는다. 관리자가 md 를 고치는 동안 보관했다가 register 에
그대로 준다 (d.save / Draft.load). 등록 때 새로 만들면 그새 들어간 사례를 오래된 md 가 지워도 못 잡는다.
개정 이력의 '해결 사례 반영 (<접수 번호>)' 표식으로 반영 여부를 정확히 가린다 (기준에 있던 표식이 빠지면 거부).

같은 가이드에 아직 승인 안 된 사례 초안이 있으면 새 버전을 또 만들지 않고 그 초안에 이어 쓴다 (v2.1 이 둘 생기지 않게).
민감정보는 지우거나 막지 않고 경고만 한다: 새로 더한 줄만, D 의 탐지 규칙(docs/10 2장 목록 전부: 전화·이메일·사번·
직원 이름, 비밀·고유식별)으로. 해결 사례 검토에 쓸 목록은 2장 목록이다 (docs/10 1.3).
초안은 비현행이라 검색·외부 전송에 나가지 않고, 승인 전 검토(정확성·정보 보호·공개 범위)는 관리자 몫이다 (GUIDE-03).
열람 범위·외부 전송 정책은 관리자가 등록할 때 고른다 (docs/10 1.3).
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.rag.chunker import chunk_document, validate
from app.rag.ingest import ROOT, _audit, _lock_document
from app.rag.ingest.upload import read_guide_md, resolve_file
from app.rag.parser import ParseError, parse

CASE_DIR = Path('storage') / 'case_guides'                 # files_root 아래. file_path 에는 이 상대 경로만 넣는다
EVENT = 'CASE_GUIDE_REGISTER'                              # 감사 로그. result 에 '<접수 번호> → <버전>'
HANDLING = '🔵 IT 담당자 처리'                              # 담당자가 해결한 사례. 사용자 조치로 바꿀지는 관리자가
SHORT_NOTE = 20                                            # 해결 내용이 이보다 짧으면 경고
VIEW_SCOPES = ('ALL', 'AGENT', 'ADMIN')                     # document_versions 제약과 같다
TRANSFER_POLICIES = ('ALLOWED', 'MASKED', 'BLOCKED')
MARK = '해결 사례 반영'                                     # 개정 이력 표식: '해결 사례 반영 (<접수 번호>)'
MARK_RE = re.compile(re.escape(MARK) + r' \(([^()\s|]+)\)')


class CaseGuideError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__('; '.join(problems))
        self.problems = problems


@dataclass
class Draft:
    ticket_id: int
    receipt_no: str
    document_id: int
    doc_code: str
    version: str                                           # 새 버전 (이어 쓰기면 그 초안의 버전)
    section_no: str                                        # 새 항목 번호 (3.8)
    base_md: str                                           # 기준 md (현행, 또는 이어 쓰는 초안)
    md: str
    current_version_id: int                                # 만들 때의 현행. 등록 때 바뀌었으면 거부
    draft_version_id: int | None = None                    # 이어 쓰는 초안 버전 행
    base_file_path: str | None = None                      # 이어 쓰는 초안의 file_path. 등록 때 바뀌었으면 거부
    warnings: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        """초안 정보(만들 때의 기준)를 JSON 으로. 관리자가 md 를 고치는 동안 보관했다가 register 에 그대로 준다."""
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False), encoding='utf-8')

    @classmethod
    def load(cls, path: Path) -> Draft:
        return cls(**json.loads(Path(path).read_text(encoding='utf-8')))


def receipts(md: str) -> set[str]:
    """개정 이력 표식에 적힌 접수 번호들 (정확히. 'TK-1' 과 'TK-10' 은 다르다)."""
    return set(MARK_RE.findall(md))


# ── 고르기 ────────────────────────────────────────────────────

def candidates(conn, category: str | None = None) -> list[dict]:
    """가이드화할 수 있는 CLS 티켓 (이미 등록한 접수 번호는 빼고). [{'ticket_id', 'receipt_no', 'summary', 'code', 'doc_code'}]"""
    rows = conn.execute(
        "select t.id, t.receipt_no, t.summary, it.code from tickets t left join inquiry_types it on it.id = t.inquiry_type_id "
        "where t.work_status = 'CLS' and (%s::text is null or t.category_code = %s) "
        "and not exists (select 1 from audit_logs a where a.event_type = %s and a.result like t.receipt_no || ' → %%') "
        'order by t.closed_at nulls last, t.id', (category, category, EVENT)).fetchall()
    out = []
    for tid, receipt, summary, code in rows:
        guides = _guides_for(conn, code) if code else []
        out.append({'ticket_id': tid, 'receipt_no': receipt, 'summary': summary, 'code': code,
                    'doc_code': guides[0][1] if guides else None})
    return out


def _guides_for(conn, code: str) -> list[tuple[int, str, int]]:
    """문의 유형 코드를 다루는 현행 가이드 (임직원용 GUIDE, 매뉴얼 제외). (문서 id, 문서 번호, 항목 수) 많은 순."""
    return conn.execute(
        'select d.id, d.doc_code, count(*) from document_chunks c '
        'join document_versions v on v.id = c.version_id and v.is_current '
        "join knowledge_documents d on d.id = v.document_id and d.doc_type = 'GUIDE' "
        "where c.chunk_type = 'ITEM' and c.part = 1 and c.meta->'inquiry_type_codes' ? %s "
        'group by d.id, d.doc_code order by count(*) desc, d.doc_code', (code,)).fetchall()


# ── 초안 ──────────────────────────────────────────────────────

def draft(conn, ticket_id: int, doc_code: str | None = None, files_root: Path = ROOT,
          staff_names: list[str] | None = None, today: date | None = None) -> Draft:
    """CLS 티켓 → 그 문의 유형 가이드의 다음 버전 md. DB 에 쓰지 않는다. 안 되면 CaseGuideError.

    doc_code: 넣을 가이드 (문의 유형이 없는 티켓, 여러 가이드가 다룰 때 관리자가 고른다).
    """
    t = _read_ticket(conn, ticket_id)
    problems = []
    if t['work_status'] != 'CLS':
        problems.append(f"해결 확인(CLS)된 티켓만 가이드로 만듭니다: {t['receipt_no']}는 {t['work_status']}")
    if not (t['resolution_note'] or '').strip():
        problems.append(f"{t['receipt_no']}에 해결 내용(resolution_note)이 없습니다")
    if problems:
        raise CaseGuideError(problems)
    warnings: list[str] = []
    doc_id, doc_code = _pick_guide(conn, t, doc_code, warnings)
    cur = conn.execute('select id, version, file_path from document_versions where document_id = %s and is_current',
                       (doc_id,)).fetchone()
    if cur is None:
        raise CaseGuideError([f'{doc_code}에 현행 버전이 없습니다'])
    drafts = conn.execute(
        'select id, version, file_path from document_versions where document_id = %s and not is_current '
        'and activated_at is null order by id desc', (doc_id,)).fetchall()
    ours = [r for r in drafts if (r[2] or '').startswith(CASE_DIR.as_posix() + '/')]
    if others := [r[1] for r in drafts if r not in ours]:
        warnings.append(f"{doc_code}에 다른 초안({', '.join(others)})이 있습니다. 둘 다 승인하면 나중 것만 현행이 됩니다")
    if ours:
        draft_id, version, base_path = ours[0]
        warnings.append(f'승인 전 사례 초안 {version}에 이어서 더합니다')
    else:
        draft_id, base_path = None, None
        versions = [v for (v,) in conn.execute('select version from document_versions where document_id = %s', (doc_id,))]
        version = next_version(versions)
    base_file = resolve_file(base_path or cur[2], files_root)
    base_md = _base_md(base_file, doc_code, warnings)
    if t['receipt_no'] in receipts(base_md):
        raise CaseGuideError([f"{t['receipt_no']}는 이미 {doc_code}에 반영되어 있습니다"])

    md, section_no = add_case(base_md, t, version, today or date.today(), warnings)
    added = _added_lines(base_md, md)
    warnings += sensitive_warnings(md, added, staff_names if staff_names is not None else _staff_names(conn))
    same = _sections_with(base_md, t['code']) if t['code'] else []
    warnings.append(f'새 항목 {section_no}은 티켓 글을 그대로 옮겼습니다. 임직원이 따라 할 수 있게 다듬고, '
                    + (f"같은 문의 유형 항목({', '.join(same)})에 합칠지 확인하세요" if same else '처리 구분을 확인하세요'))
    if len(t['resolution_note'].strip()) < SHORT_NOTE:
        warnings.append(f'해결 내용이 짧습니다 ({len(t["resolution_note"].strip())}자). 조치 방법을 채워 주세요')
    if reopened := _reopened(conn, ticket_id):
        warnings.append(f"다시 처리된 접수입니다 (재처리 {reopened}회). 앞선 처리 결과·남은 증상은 {t['receipt_no']}의 "
                        f'TK-08 이력(티켓 {ticket_id})에서 확인하세요. 본문에는 마지막 처리 결과만 넣었습니다')
    conn.commit()                                          # 읽기만 했다 (트랜잭션을 열어 두지 않게)
    return Draft(ticket_id=ticket_id, receipt_no=t['receipt_no'], document_id=doc_id, doc_code=doc_code,
                 version=version, section_no=section_no, base_md=base_md, md=md, current_version_id=cur[0],
                 draft_version_id=draft_id, base_file_path=base_path, warnings=warnings)


def _base_md(path: Path, doc_code: str, warnings: list[str]) -> str:
    """기준 md. 현행이 md 가 아니면(docx·pptx·pdf·txt) 파싱 결과를 가이드 md 로 바꿔 쓴다 (ingest/upload.py read_guide_md).
    새 버전은 늘 md 다. 바꾼 md 를 다시 읽으면 원래 파일과 청크가 같지만 쪽 번호·문서 안 그림 내용 해시는 빠진다.
    그림은 바꾸기 전에 배포 그림과 맞춰 보고, 없거나 내용이 다른 그림은 이름표 없이 본문 설명만 남긴다 (경고)."""
    try:
        md, image_warnings = read_guide_md(path)
    except ParseError as e:
        raise CaseGuideError([f'{doc_code}의 현행 파일({path.suffix})을 읽지 못했습니다: {e.message}']) from e
    if path.suffix.lower() != '.md':
        warnings.append(f'{doc_code}의 현행 파일이 {path.suffix.lstrip(".")} 라 md 로 바꿔 기준으로 썼습니다. '
                        '새 버전은 md 로 저장·적재되고, 쪽 번호와 문서 안 그림의 내용 확인 값은 넣지 않습니다')
    warnings += image_warnings
    return md


def _read_ticket(conn, ticket_id: int) -> dict:
    row = conn.execute(
        'select t.receipt_no, t.work_status, t.summary, t.symptom, t.target_system, t.resolution_note, '
        't.category_code, it.code, g.name from tickets t left join inquiry_types it on it.id = t.inquiry_type_id '
        'left join support_groups g on g.id = t.group_id where t.id = %s', (ticket_id,)).fetchone()
    if row is None:
        raise ValueError(f'없는 티켓 id {ticket_id}')
    keys = ('receipt_no', 'work_status', 'summary', 'symptom', 'target_system', 'resolution_note', 'category_code',
            'code', 'group')
    return dict(zip(keys, row))


def _reopened(conn, ticket_id: int) -> int:
    """미해결로 되돌린(FIN→WIP) 횟수. 앞선 처리 결과·남은 증상은 원문을 경고에 넣지 않는다 (민감정보 경고처럼 위치만)."""
    return conn.execute("select count(*) from ticket_status_history where ticket_id = %s "
                        "and from_status = 'FIN' and to_status = 'WIP'", (ticket_id,)).fetchone()[0]


def _pick_guide(conn, t: dict, doc_code: str | None, warnings: list[str]) -> tuple[int, str]:
    if doc_code:
        row = conn.execute("select id, doc_code from knowledge_documents where doc_code = %s and doc_type = 'GUIDE'",
                           (doc_code,)).fetchone()
        if row is None:
            raise CaseGuideError([f'없는 가이드 {doc_code} (임직원용 가이드만, 매뉴얼은 안 됨)'])
        return row
    if not t['code']:
        raise CaseGuideError([f"{t['receipt_no']}에 문의 유형이 없습니다. 넣을 가이드를 골라 주세요 (--doc)"])
    guides = _guides_for(conn, t['code'])
    if not guides:
        raise CaseGuideError([f"문의 유형 {t['code']}을 다루는 현행 가이드가 없습니다. 넣을 가이드를 골라 주세요 (--doc)"])
    if len(guides) > 1:
        warnings.append(f"{t['code']}을 다루는 가이드가 여럿입니다 ({', '.join(g[1] for g in guides)}). "
                        f'항목이 가장 많은 {guides[0][1]}에 넣었습니다. 다른 곳이면 --doc 으로')
    return guides[0][0], guides[0][1]


def _staff_names(conn) -> list[str]:
    return [n for (n,) in conn.execute('select name from users')]


def next_version(versions: list[str]) -> str:
    """가장 높은 vX.Y 의 다음 부 버전 (v2.0 → v2.1). 형식이 다른 버전만 있으면 CaseGuideError."""
    nums = [tuple(map(int, m.groups())) for v in versions if (m := re.fullmatch(r'v(\d+)\.(\d+)', v or ''))]
    if not nums:
        raise CaseGuideError([f"버전 형식(vX.Y)을 몰라 다음 버전을 정할 수 없습니다: {', '.join(versions)}"])
    major, minor = max(nums)
    return f'v{major}.{minor + 1}'


# ── md 고치기 ─────────────────────────────────────────────────

ITEM_HEAD = re.compile(r'^### (3\.(\d+)) ', re.M)
ITEM_TABLE_HEAD = ['번호', '제목', '문의 유형', '처리 구분', '담당 부서']   # 3장 앞 항목 표 (가이드 27종 모두 이 5열)


def add_case(md: str, t: dict, version: str, today: date, warnings: list[str]) -> tuple[str, str]:
    """기준 md 에 사례를 더한다: 버전 표기 → 새 항목 3.N (3장 끝) → 3장 항목 표 한 줄 → 목차 한 줄 → 개정 이력 한 줄.
    (md, 항목 번호)"""
    chapter = re.search(r'^## 3\. .*$', md, re.M)
    if chapter is None:
        raise CaseGuideError(['기준 가이드에 3장(항목별 안내)이 없어 항목을 넣을 수 없습니다'])
    old = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', md, re.M)
    if old and old.group(1) != version:
        md = md[:old.start()] + f'version: "{version}"' + md[old.end():]
        md = re.sub(rf'^(>.*\| ){re.escape(old.group(1))}( \|)', rf'\g<1>{version}\g<2>', md, count=1, flags=re.M)
    elif not old:
        warnings.append('머리말에 version 이 없습니다. 등록한 버전으로 적재됩니다')

    chapter = re.search(r'^## 3\. .*$', md, re.M)
    end = re.search(r'^## ', md[chapter.end():], re.M)
    end = chapter.end() + end.start() if end else len(md)
    numbers = [int(m.group(2)) for m in ITEM_HEAD.finditer(md, chapter.end(), end)]
    section_no = f'3.{max(numbers, default=0) + 1}'
    title = _one_line(t['summary']) or _one_line(t['symptom']) or '해결 사례'
    item = _item(section_no, title, t)
    md = md[:end].rstrip('\n') + '\n\n' + item + '\n\n' + md[end:]
    md = _add_table_row(md, chapter.end(), [section_no, title, t['code'] or '', HANDLING, t['group'] or ''], warnings)

    toc = list(re.finditer(r'^(\s*)- 3\.\d+ .*$', md[:chapter.start()], re.M))
    if toc:
        last = toc[-1]
        md = md[:last.end()] + f'\n{last.group(1)}- {section_no} {title}' + md[last.end():]
    else:
        warnings.append('목차에서 3장 항목 줄을 찾지 못해 목차는 고치지 않았습니다')

    note = _cell(f"{MARK} ({t['receipt_no']}): {section_no} {title}")
    group = _cell(t['group'] or '서비스데스크')
    history = re.search(r'^## 개정 이력\s*$', md, re.M)
    if history is None:
        warnings.append('개정 이력이 없어 끝에 새로 만들었습니다')
        md = md.rstrip('\n') + ('\n\n## 개정 이력\n\n| 버전 | 개정일 | 작성자 | 변경 내용 |\n| --- | --- | --- | --- |\n'
                                f'| {version} | {today.isoformat()} | {group} | {note} |\n')
        return md, section_no
    rows = list(re.finditer(r'^\|.*\|[ \t]*$', md[history.end():], re.M))
    same = next((r for r in rows if re.match(rf'^\|\s*{re.escape(version)}\s*\|', r.group(0))), None)
    if same:                                               # 이어 쓰는 초안: 그 버전 줄 변경 내용에 덧붙인다
        at = history.end() + same.end()
        line = same.group(0).rstrip()
        md = md[:history.end() + same.start()] + line[:-1].rstrip() + f'; {note} |' + md[at:]
    else:
        at = history.end() + rows[-1].end() if rows else history.end()
        md = md[:at] + f'\n| {version} | {today.isoformat()} | {group} | {note} |' + md[at:]
    return md, section_no


def _add_table_row(md: str, start: int, cells: list[str], warnings: list[str]) -> str:
    """3장 제목(start)과 첫 항목 사이의 **첫 표** 끝에 한 줄. 표는 빈 줄이나 표 아닌 줄에서 끝나고 (md 파서도 따로 읽는다),
    코드 블록(``` 울타리, md 파서와 같은 규칙) 안의 줄은 보지 않는다. 표가 없거나 머리줄이 ITEM_TABLE_HEAD 가 아니면
    고치지 않고 경고한다 (모르는 표를 조용히 고치지 않게). 새 항목 본문은 표와 상관없이 검색된다.
    지난 행을 채우지는 않는다: 표의 번호와 3장 항목 번호가 다르면 (예: 이 기능 전에 만든 초안에 이어 쓰기) 경고만."""
    first = ITEM_HEAD.search(md, start)
    stop = first.start() if first else len(md)
    block, fence, pos = [], '', start                     # block: 첫 표 줄들의 (시작, 줄 끝 문자 앞) 위치
    for line in md[start:stop].splitlines(keepends=True):
        s, at = line.strip(), pos
        pos += len(line)
        if fence:
            fence = '' if s.startswith(fence) else fence
        elif s.startswith('```'):
            fence = '`' * (len(s) - len(s.lstrip('`')))
        elif s.startswith('|') and s.endswith('|'):
            block.append((at, at + len(line.rstrip('\r\n'))))
            continue
        if block:                                          # 표 다음 줄이 표가 아니면 (빈 줄 포함) 첫 표 끝
            break
    if not block:
        warnings.append('3장 항목 표를 찾지 못해 표는 고치지 않았습니다')
        return md
    cut = lambda b: [c.strip() for c in re.split(r'(?<!\\)\|', md[b[0]:b[1]].strip())[1:-1]]   # noqa: E731
    head = cut(block[0])
    if head != ITEM_TABLE_HEAD:
        warnings.append(f"3장 항목 표 머리줄({' | '.join(head)})이 예상과 달라 표는 고치지 않았습니다")
        return md
    end = block[-1][1]
    newline = '\r\n' if md[end:end + 2] == '\r\n' else '\n'
    md = md[:end] + newline + '| ' + ' | '.join(_cell(c) for c in cells) + ' |' + md[end:]

    chapter_end = re.search(r'^## ', md[start:], re.M)
    chapter_end = start + chapter_end.start() if chapter_end else len(md)
    in_table = {cut(b)[0] for b in block[2:]} | {cells[0]}
    in_items = {m.group(1) for m in ITEM_HEAD.finditer(md, start, chapter_end)}
    if in_table != in_items:
        gaps = [f"표에 없음 {', '.join(sorted(in_items - in_table))}" if in_items - in_table else '',
                f"항목에 없음 {', '.join(sorted(in_table - in_items))}" if in_table - in_items else '']
        warnings.append(f"3장 항목 표와 항목 번호가 다릅니다 ({'; '.join(g for g in gaps if g)}). 표를 확인해 주세요")
    return md


def _item(section_no: str, title: str, t: dict) -> str:
    props = ' · '.join(x for x in (f"**문의 유형** {t['code']}" if t['code'] else '', f'**처리 구분** {HANDLING}',
                                   f"**담당 부서** {t['group']}" if t['group'] else '') if x)
    cases = _bullets(t['symptom'] or t['summary'])
    if t['target_system']:
        cases.append(f"- 대상: {_one_line(t['target_system'])}")
    steps = _bullets(t['resolution_note'])
    who = f"{t['group']}이 확인합니다" if t['group'] else '담당자가 확인합니다'
    return '\n'.join([f'### {section_no} {title}', '', props, '', '#### 이런 경우', '', *cases, '',
                      '#### 조치 방법', '', *steps, '', '**해결되지 않으면**', '',
                      f'- 위 조치로 해결되지 않으면 ITssue 챗봇에 알립니다. {who}.'])


def _bullets(text: str | None) -> list[str]:
    """여러 줄 글 → 목록 줄. 이미 목록·번호 줄이면 그대로, 제목(#)은 글로 바꾼다 (항목 구조가 깨지지 않게)."""
    out = []
    for line in (text or '').splitlines():
        line = line.strip().lstrip('#').strip()
        if not line:
            continue
        out.append(line if re.match(r'^([-*]|\d+[.)])\s', line) else f'- {line}')
    return out or ['- (관리자가 채워 주세요)']


def _cell(text: str) -> str:
    """표 칸에 넣을 글: 세로줄을 이스케이프한다 (칸이 늘어나지 않게. 파서는 '\\|' 를 칸 구분으로 보지 않는다)."""
    return text.replace('|', '\\|')


def _one_line(text: str | None) -> str:
    return ' '.join((text or '').lstrip('#').split())[:80]


def _sections_with(md: str, code: str) -> list[str]:
    """그 문의 유형이 머리 정보에 적힌 항목 번호들."""
    out, section = [], None
    for line in md.splitlines():
        if m := ITEM_HEAD.match(line + ' '):
            section = m.group(1)
        elif section and line.startswith('**문의 유형**') and code in line and section not in out:
            out.append(section)
    return out


def _added_lines(base: str, md: str) -> list[int]:
    """md 에서 기준에 없던 줄 번호 (1부터). 민감정보는 이 줄만 본다 (기존 문의처의 공식 연락처까지 경고하지 않게)."""
    have = set(base.splitlines())
    return [i for i, line in enumerate(md.splitlines(), 1) if line.strip() and line not in have]


# ── 민감정보 경고 ─────────────────────────────────────────────

def sensitive_warnings(md: str, lines: list[int], staff_names: list[str]) -> list[str]:
    """새로 더한 줄에서 개인정보·비밀정보로 보이는 것을 찾아 경고한다. 값은 경고에 넣지 않는다 (로그에 남으므로)."""
    from app.agent.sensitive import Pseudonymizer, mask_secrets
    from app.agent.sensitive.pseudonym import LABELS
    tag = re.compile(r'\[(' + '|'.join(LABELS.values()) + r')\d+\]')
    found: dict[str, list[int]] = {}
    text = md.splitlines()
    for n in lines:
        line = text[n - 1]
        kinds = tag.findall(Pseudonymizer(staff_names).apply(line))   # 줄마다 새로: 번호가 이어지지 않게 (값은 안 씀)
        kinds += [KINDS.get(k, k) for k in mask_secrets(line).counts]
        for k in dict.fromkeys(kinds):
            found.setdefault(k, []).append(n)
    return [f"개인정보·비밀정보로 보이는 부분: {k} ({', '.join(map(str, ns))}번 줄). 가이드는 사내에 공개되므로 "
            '지우거나 일반적인 말로 바꿔 주세요' for k, ns in found.items()]


KINDS = {'PASSWORD': '비밀번호', 'OTP': '인증번호', 'API_KEY': 'API 키', 'PRIVATE_KEY': '개인 키',
         'RRN': '주민등록번호', 'CARD': '카드번호', 'ACCOUNT': '계좌번호'}


# ── 검사·등록 ─────────────────────────────────────────────────

def check(d: Draft, md: str, staff_names: list[str]) -> tuple[list[str], list[str]]:
    """관리자가 고친 md 를 다시 본다. (문제: 등록 안 됨, 경고: 등록은 됨).

    문제: 파서·청커가 못 읽음, 문서 번호·버전이 초안과 다름, 기준 가이드의 항목이 빠짐, 이 티켓의 접수 번호 표식이
    없음, 기준에 있던 다른 사례의 표식이 빠짐 (오래된 기준에서 고친 md 가 그새 들어간 사례를 지우지 않게).
    새 항목 3.N 을 지우고 기존 항목에 합친 것은 괜찮다. 개정 이력 표식만 남기면 된다 (같은 티켓을 두 번 넣지 않게).
    """
    problems = []
    try:
        new = _parse_text(md)
    except ParseError as ex:
        return [ex.message], []
    meta = new[0]
    if meta.get('doc_no') and meta['doc_no'] != d.doc_code:
        problems.append(f"문서 번호가 {meta['doc_no']}입니다 ({d.doc_code}이어야 합니다)")
    if meta.get('version') and meta['version'] != d.version:
        problems.append(f"버전이 {meta['version']}입니다 ({d.version}이어야 합니다)")
    problems += validate(new[1])
    base_sections = {c.section_no for c in _parse_text(d.base_md)[1] if c.chunk_type == 'item'}
    if missing := sorted(base_sections - {c.section_no for c in new[1] if c.chunk_type == 'item'}):
        problems.append(f"기준 가이드의 항목이 빠졌습니다: {', '.join(missing)}")
    have = receipts(md)
    if d.receipt_no not in have:
        problems.append(f'접수 번호 {d.receipt_no}가 없습니다 (개정 이력 줄 "{MARK} ({d.receipt_no})"을 남겨 주세요)')
    if lost := sorted(receipts(d.base_md) - have):
        problems.append(f"기준에 있던 사례가 빠졌습니다: {', '.join(lost)}")
    return problems, sensitive_warnings(md, _added_lines(d.base_md, md), staff_names)


def _parse_text(md: str):
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / 'case.md'
        f.write_text(md, encoding='utf-8')
        doc = parse(str(f))
    return doc.meta, chunk_document(doc)


def register(conn, d: Draft, md: str, admin_id: int | None, files_root: Path = ROOT, *,
             view_scope: str, transfer_policy: str) -> dict:
    """md 를 파일로 쓰고 버전 행을 PENDING·비현행으로 만든다 (이어 쓰기면 그 초안 행의 파일·정책을 바꾼다). commit 한다.

    결과 {'version_id', 'file_path', 'warnings'}. 이어서 ingest_version(conn, version_id, embedder) 을 부른다.
    열람 범위·전송 정책은 관리자가 고른 값을 받는다 (docs/10 1.3: 해결 사례를 Guide 로 쓸 때 반드시 고르게 한다).
    현행 값과 다르면 경고한다 (승인하면 가이드 전체에 적용되므로). 승인(현행 전환)은 하지 않는다.
    만든 뒤 현행이 바뀌었거나 이어 쓰던 초안이 바뀌었으면 거부한다 (다시 draft): 다른 사람의 변경을 덮지 않게.
    """
    bad = ([f'열람 범위 {view_scope}'] if view_scope not in VIEW_SCOPES else []) + \
          ([f'전송 정책 {transfer_policy}'] if transfer_policy not in TRANSFER_POLICIES else [])
    if bad:
        conn.rollback()
        raise CaseGuideError([f"없는 값입니다: {', '.join(bad)}"])
    problems, warnings = check(d, md, _staff_names(conn))
    if problems:
        conn.rollback()
        raise CaseGuideError(problems)
    _lock_document(conn, d.document_id)
    cur = conn.execute('select id, view_scope, transfer_policy from document_versions where document_id = %s '
                       'and is_current', (d.document_id,)).fetchone()
    stale = []
    if cur is None or cur[0] != d.current_version_id:
        stale.append('초안을 만든 뒤 현행 버전이 바뀌었습니다')
    if d.draft_version_id is not None:
        row = conn.execute('select file_path, is_current, activated_at from document_versions where id = %s',
                           (d.draft_version_id,)).fetchone()
        if row is None or row[0] != d.base_file_path or row[1] or row[2] is not None:
            stale.append(f'이어 쓰던 초안 {d.version}이 그새 바뀌었습니다')
    elif conn.execute('select 1 from document_versions where document_id = %s and version = %s',
                      (d.document_id, d.version)).fetchone():
        stale.append(f'{d.version} 버전이 그새 생겼습니다')
    if stale:
        conn.rollback()
        raise CaseGuideError([*stale, '초안을 다시 만드세요'])
    if (view_scope, transfer_policy) != (cur[1], cur[2]):
        warnings.append(f'열람 범위·전송 정책을 현행({cur[1]}·{cur[2]})과 다르게 {view_scope}·{transfer_policy}로 '
                        '등록합니다. 승인하면 가이드 전체에 이 값이 적용됩니다')

    rel = (CASE_DIR / d.doc_code / f'{d.version}_{d.receipt_no}.md').as_posix()   # 쓸 때마다 다른 경로
    path = Path(files_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding='utf-8')
    try:
        if d.draft_version_id is not None:
            vid = d.draft_version_id
            conn.execute("update document_versions set file_path = %s, view_scope = %s, transfer_policy = %s, "
                         "ingest_status = 'PENDING', ingest_error = null, registered_at = now() where id = %s",
                         (rel, view_scope, transfer_policy, vid))
        else:
            vid = conn.execute(
                'insert into document_versions (document_id, version, file_path, view_scope, transfer_policy, '
                "is_current, ingest_status, registered_at) values (%s, %s, %s, %s, %s, false, 'PENDING', now()) "
                'returning id', (d.document_id, d.version, rel, view_scope, transfer_policy)).fetchone()[0]
        _audit(conn, EVENT, d.document_id, admin_id, f'{d.receipt_no} → {d.version}')
        conn.commit()
    except Exception:
        conn.rollback()
        path.unlink(missing_ok=True)
        raise
    return {'version_id': vid, 'file_path': rel, 'warnings': warnings}
