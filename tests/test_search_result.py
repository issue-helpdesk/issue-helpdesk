"""검색 요청·결과 형식(M3-1-1) 테스트. DB·모델 없이 형식 규칙만 본다."""
import json

import pytest

from app.rag.search import (ChunkHit, DocumentResult, LegacyResult, SearchRequest, SearchResponse,
                            message_source_rows, visible_scopes)

TEXT = ('업무용 SW 실행·오류 대응 가이드 > 3. 증상별 조치 방법 > 3.1 프로그램이 멈추거나 바로 꺼질 때 (기본 조치)\n'
        '프로그램을 완전히 종료한 뒤 다시 실행합니다.\nPC를 재부팅합니다.')


def doc(**kw):
    base = dict(unit_key='IT-SW-003@v2.0/item:3.1', chunk_type='ITEM', doc_code='IT-SW-003',
                title='업무용 SW 실행·오류 대응 가이드', version='v2.0', location='3.1',
                heading_path='3. 증상별 조치 방법 > 3.1 프로그램이 멈추거나 바로 꺼질 때 (기본 조치)', text=TEXT,
                chunks=(ChunkHit(104, 1), ChunkHit(105, 2, 0.71)), unit_score=0.71,
                score_type='cosine:kure-v1@test/v1', view_scope='ALL', transfer_policy='ALLOWED',
                evidence=('프로그램을 완전히 종료한 뒤 다시 실행합니다.',), inquiry_type_codes=('SW-03',),
                handling='사용자 직접 조치')
    base.update(kw)
    return DocumentResult(**base)


def legacy(**kw):
    base = dict(legacy_inquiry_id=245, legacy_no='INQ-2026-00245', inquiry_type_code='HW-02', title='노트북이 안 켜져요',
                text='노트북이 안 켜져요 / 메인보드 펌웨어 업데이트 후 디스크 암호화 복구 모드 진입 / 관리 콘솔에서 복구 키 확인·전달 후 정상 부팅',
                root_cause='메인보드 펌웨어 업데이트 후 디스크 암호화 복구 모드 진입',
                resolution='관리 콘솔에서 복구 키 확인·전달 후 정상 부팅', resolved_at='2026-07-09 13:51', score=0.64,
                score_type='cosine:kure-v1@test/v1', view_scope='AGENT', transfer_policy='MASKED')
    base.update(kw)
    return LegacyResult(**base)


@pytest.mark.parametrize('role, scopes', [('EMPLOYEE', ('ALL',)), ('AGENT', ('ALL', 'AGENT')),
                                          ('ADMIN', ('ALL', 'AGENT', 'ADMIN')), ('GUEST', ())])
def test_visible_scopes(role, scopes):
    """역할별 열람 범위 (청크_메타데이터.md 4장). 모르는 역할은 아무것도 못 본다."""
    assert visible_scopes(role) == scopes


@pytest.mark.parametrize('kw', [dict(query='  '), dict(service_role='USER'), dict(sources=('WEB',)), dict(top_k=0),
                                dict(top_k=21)])
def test_request_rejects_bad_values(kw):
    args = dict(query='프로그램이 꺼져요', service_role='EMPLOYEE') | kw
    with pytest.raises(ValueError):
        SearchRequest(**args)


def test_request_defaults():
    r = SearchRequest(query='프로그램이 꺼져요', service_role='EMPLOYEE')
    assert r.sources == ('DOCUMENT', 'LEGACY') and r.top_k == 5 and r.category_code is None


def test_evidence_must_be_in_text():
    """근거 문장은 본문에 그대로 있는 문장만 (지어낸 문장 차단)."""
    with pytest.raises(ValueError):
        doc(evidence=('관리자 권한으로 다시 설치합니다.',))
    with pytest.raises(ValueError):
        doc(evidence=('PC를 재부팅합니다.',) * 4)


def test_document_needs_matched_chunk():
    with pytest.raises(ValueError):
        doc(chunks=(ChunkHit(104, 1), ChunkHit(105, 2)))


@pytest.mark.parametrize('kw', [dict(view_scope='PUBLIC'), dict(transfer_policy='OK'), dict(chunk_type='TABLE')])
def test_document_rejects_unknown_codes(kw):
    with pytest.raises(ValueError):
        doc(**kw)


def test_citations():
    assert doc().citation == 'IT-SW-003 3.1'
    assert legacy().citation == '과거 처리 사례 참고 · INQ-2026-00245 (2026-07)'          # PRD 4.2 문구
    assert legacy(resolved_at=None).citation == '과거 처리 사례 참고 · INQ-2026-00245'


def test_legacy_has_no_person_fields():
    """과거 사례 결과에는 요청자·담당자를 가리키는 칸이 없다."""
    fields = set(legacy().__dataclass_fields__)
    assert not fields & {'requester_id', 'requester_department_id', 'assignee', 'assignee_id', 'requester_dept'}


@pytest.mark.parametrize('scores, threshold, sufficient', [((0.71, 0.64), 0.5, True), ((0.42, 0.31), 0.5, False),
                                                           ((), 0.5, False), ((0.5,), 0.5, True)])
def test_sufficient(scores, threshold, sufficient):
    docs = tuple(doc(unit_score=s, chunks=(ChunkHit(1, 1, s),)) for s in scores)
    assert SearchResponse(query='q', model='m', threshold=threshold, documents=docs).sufficient is sufficient


def test_legacy_alone_is_not_sufficient():
    """과거 사례 점수가 높아도 문서 근거가 없으면 충분하지 않다."""
    resp = SearchResponse(query='q', model='m', threshold=0.5, legacy=(legacy(score=0.9),))
    assert resp.best_score is None and resp.sufficient is False


def test_response_to_dict_is_json():
    """API 응답으로 그대로 나갈 수 있다. 계산 값(citation·sufficient·best_score)도 들어 있다."""
    resp = SearchResponse(query='프로그램이 꺼져요', model='kure-v1@test/v1', threshold=0.5, documents=(doc(),),
                          legacy=(legacy(),), took_ms=84)
    d = json.loads(json.dumps(resp.to_dict(), ensure_ascii=False))
    assert d['sufficient'] is True and d['best_score'] == 0.71
    assert d['documents'][0]['citation'] == 'IT-SW-003 3.1' and d['documents'][0]['source_kind'] == 'DOCUMENT'
    assert d['legacy'][0]['source_kind'] == 'LEGACY'


def test_message_source_rows():
    """문서는 조각마다 한 행, 과거 사례는 한 행. 두 종류의 칸이 섞이지 않는다 (청크_메타데이터.md 6장)."""
    rows = message_source_rows([doc(), legacy()])
    assert [(r['source_kind'], r['rank']) for r in rows] == [('DOCUMENT', 1), ('DOCUMENT', 1), ('LEGACY', 2)]
    assert [r['chunk_id'] for r in rows[:2]] == [104, 105]
    for r in rows:
        if r['source_kind'] == 'DOCUMENT':
            assert r['legacy_inquiry_id'] is None and r['doc_code'] and r['version']
        else:
            assert r['chunk_id'] is None and r['legacy_inquiry_id'] == 245
        assert r['excerpt']
