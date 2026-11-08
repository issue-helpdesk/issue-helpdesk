"""다시 맞추기 (해결 사례 가이드화 기획 v4, `작업대/가이드화/draft_basis_구조_초안_20261108.md` 6장 ②, 박민경 Q5).

묶음 초안을 만든 뒤 현행 가이드가 바뀌면 등록·현행 전환이 막힌다 (DC-09·`assemble`). 관리자가 "다시 맞추기"를 누르면
API(`POST /guide-clusters/{id}/rebase`)가 이 함수를 불러 **새 현행 기준의 `draft_basis`** 를 받는다.
**DB 쓰기·commit·파일 없음.** 저장·`draft_revision` 올리기·`conflicts.revision` 채우기·등록 연결 풀기는 API 가 한다.

    out = rebase(conn, document_id, {'judgment': …, 'draft_md': …, 'draft_basis': …, 'receipts': [...]})
    # out = {'draft_basis': 새 기준, 'conflicts': [...], 'warnings': [...]}

- 항목 추가·SEC: 새 현행의 버전 id·원문, `section_no` 는 비운다 (새 현행에 그 번호가 이미 있을 수 있어 다음 등록에서 새로).
- 변경: `target_md` 도 새 현행의 그 항목으로. 만들 때 원문과 다르면 **충돌** (TARGET_CHANGED, 예전·새 원문을 함께) —
  관리자가 조각을 고쳐 저장(GC-05)해야 등록된다. 바꿀 항목이 새 현행에 없으면 **거부** (이 묶음은 거절하고 필요하면 새 묶음).
- 같은 접수 번호 표식이 새 현행에 이미 있으면 경고 (충돌 아님, 등록 때는 `assemble` 이 거부).
"""
from __future__ import annotations

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
        old_md = (old.get('target_md') or '').strip('\n')
        if new_md.rstrip() != old_md.rstrip():
            conflicts.append({'section': target, 'kind': 'TARGET_CHANGED',
                              'message': f'{target} 이 새 현행에서 바뀌었습니다. 조각을 새 내용과 비교해 다시 저장해 주세요',
                              'old_md': old_md, 'new_md': new_md})
        basis |= {'target_section': target, 'target_md': new_md}
    else:
        basis['section_no'] = None                         # 새 현행에서 다음 등록 때 다시 정한다 (구조 초안 2장)
    if conflicts:
        basis['conflicts'] = {'revision': None, 'items': conflicts}   # revision: API 가 올린 draft_revision 으로 채움
    return {'draft_basis': basis, 'conflicts': conflicts, 'warnings': warnings}
