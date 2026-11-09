"""다시 맞추기 (해결 사례 가이드화 기획 v4, `작업대/가이드화/draft_basis_구조_초안_20261108.md` 6장 ②, 박민경 Q5).

묶음 초안을 만든 뒤 현행 가이드가 바뀌면 등록·현행 전환이 막힌다 (DC-09·`assemble`). 관리자가 "다시 맞추기"를 누르면
API(`POST /guide-clusters/{id}/rebase`)가 이 함수를 불러 **새 현행 기준의 `draft_basis`** 를 받는다.
**DB 쓰기·commit·파일 없음.** 저장·`draft_revision` 올리기·`conflicts.revision` 채우기·등록 연결 풀기는 API 가 한다.

    out = rebase(conn, document_id, {'judgment': …, 'draft_md': …, 'draft_basis': …, 'receipts': [...],
                                     'draft_revision': 지금 묶음의 draft_revision})
    # out = {'draft_basis': 새 기준, 'conflicts': [...], 'warnings': [...]}

- **아직 안 풀린 충돌** (예전 `conflicts.revision` == 지금 `draft_revision` — 관리자가 조각을 저장하지 않음) 이 있으면
  비교 기준을 그 충돌의 `old_md` (관리자 조각이 만들어진 원문) 로 둔다. 다시 맞추기를 거듭해도 충돌이 사라지지 않게
  (rebase 검수 1). 풀린 뒤면 직전 기준(`target_md`)과 비교한다. 예전 충돌이 있는데 `draft_revision` 이 없으면 거부.

- 항목 추가·SEC: 새 현행의 버전 id·원문, `section_no` 는 비운다 (새 현행에 그 번호가 이미 있을 수 있어 다음 등록에서 새로).
- 변경: `target_md` 도 새 현행의 그 항목으로. 만들 때 원문과 다르면 **충돌** (TARGET_CHANGED, 예전·새 원문을 함께) —
  관리자가 조각을 고쳐 저장(GC-05)해야 등록된다. 바꿀 항목이 새 현행에 없으면 **거부** (이 묶음은 거절하고 필요하면 새 묶음).
- 같은 접수 번호 표식이 새 현행에 이미 있으면 경고 (충돌 아님, 등록 때는 `assemble` 이 거부).
"""
from __future__ import annotations

import copy
from pathlib import Path

from app.rag.ingest import ROOT
from app.rag.ingest.upload import resolve_file

from . import CaseGuideError, _base_md, receipts
from .assemble import SCHEMA, item_text

KINDS = ('ADD_ITEM', 'SEC_MANUAL', 'CHANGE')


def rebase(conn, document_id: int, cluster: dict, files_root: Path = ROOT) -> dict:
    """묶음 하나의 기준을 지금 현행으로 다시 만든다. 결과 {'draft_basis', 'conflicts', 'warnings'}. 안 되면 CaseGuideError."""
    judgment, old = cluster.get('judgment'), cluster.get('draft_basis') or {}
    if judgment not in KINDS:
        raise CaseGuideError([f'{judgment} 묶음은 다시 맞추지 않습니다 (새 가이드는 기준 현행이 없고, 매뉴얼 후보는 초안이 없음)'])
    if old.get('schema') != SCHEMA or old.get('judgment') != judgment:
        raise CaseGuideError([f"draft_basis 가 이 묶음과 맞지 않습니다 (schema {old.get('schema')}, 판단 {old.get('judgment')})"])
    doc = conn.execute('select doc_code, doc_type from knowledge_documents where id = %s', (document_id,)).fetchone()
    if doc is None or doc[1] != 'GUIDE':
        raise CaseGuideError([f'임직원용 가이드가 아닌 문서입니다 (id {document_id})'])
    cur = conn.execute('select id, file_path from document_versions where document_id = %s and is_current',
                       (document_id,)).fetchone()
    if cur is None:
        raise CaseGuideError([f'{doc[0]}에 현행 버전이 없습니다'])
    if cur[0] == old.get('base_version_id'):
        raise CaseGuideError(['기준 버전이 지금 현행과 같아 다시 맞출 것이 없습니다'])
    warnings: list[str] = []
    base_md = _base_md(resolve_file(cur[1], files_root), doc[0], warnings)
    if done := sorted(r for r in cluster.get('receipts') or [] if r in receipts(base_md)):
        warnings.append(f"이미 {doc[0]} 새 현행에 반영된 접수 번호입니다: {', '.join(done)} (등록 때 거부됩니다)")

    basis = {'schema': SCHEMA, 'judgment': judgment, 'base_version_id': cur[0], 'base_md': base_md}
    conflicts = []
    if judgment == 'CHANGE':
        target = old.get('target_section')
        new_md = item_text(base_md, target) if target else None
        if new_md is None:
            raise CaseGuideError([f'바꿀 항목 {target}이 새 현행에 없습니다. 이 묶음은 거절하고 필요하면 새 묶음으로 만들어 주세요'])
        pending = _unresolved(old, cluster.get('draft_revision'), target)
        old_md = (pending if pending is not None else old.get('target_md') or '').strip('\n')   # 안 풀린 충돌이면 조각 원문
        if new_md.rstrip() != old_md.rstrip():
            conflicts.append({'section': target, 'kind': 'TARGET_CHANGED',
                              'message': f'{target} 이 새 현행에서 바뀌었습니다. 조각을 새 내용과 비교해 다시 저장해 주세요',
                              'old_md': old_md, 'new_md': new_md})
        basis |= {'target_section': target, 'target_md': new_md}
    else:
        basis['section_no'] = None                         # 새 현행에서 다음 등록 때 다시 정한다 (구조 초안 2장)
    if conflicts:                                          # revision: API 가 올린 draft_revision 으로 채움
        basis['conflicts'] = {'revision': None, 'items': copy.deepcopy(conflicts)}   # 결과 목록과 따로 (한쪽을 고쳐도 안 번지게)
    return {'draft_basis': basis, 'conflicts': conflicts, 'warnings': warnings}


def _unresolved(old: dict, draft_revision, target: str) -> str | None:
    """예전 기준의 아직 안 풀린 충돌이 있으면 조각이 만들어진 원문 old_md, 없거나 풀렸으면 None.
    풀림 = 충돌을 기록한 뒤 관리자가 조각을 저장해 draft_revision 이 올라감 (등록 API 의 차단 규칙과 같은 기준).
    충돌 데이터의 모양이 틀리거나 안 풀린 충돌에 필요한 값(대상 항목·old_md)이 없으면 풀렸다고 추정하지 않고 거부한다
    (#368 재검수 1)."""
    c = old.get('conflicts')
    if c is None:
        return None
    bad = lambda why: CaseGuideError([f'예전 충돌 기록의 모양이 틀립니다 ({why}). 묶음을 거절하고 새로 만들어 주세요'])  # noqa: E731
    if not isinstance(c, dict) or not isinstance(c.get('items'), list) or not c['items']:
        raise bad('conflicts·items')
    if draft_revision is None:
        raise CaseGuideError(['예전 충돌이 있어 지금 draft_revision 이 필요합니다 (풀렸는지 알아야 함)'])
    revision = c.get('revision')
    if revision is not None and (type(revision) is not int or type(draft_revision) is not int):
        raise bad('revision 이 정수가 아님')
    if revision is None or revision != draft_revision:
        return None                                        # 풀림 (번호를 채우지 않은 값은 등록 API 도 막지 않는다)
    item = next((i for i in c['items'] if isinstance(i, dict) and i.get('section') == target), None)
    if item is None or not isinstance(item.get('old_md'), str):
        raise bad(f'안 풀린 충돌에 항목 {target} 의 old_md 가 없음')   # 한 묶음 한 항목 (김현나 Q2)
    return item['old_md']
