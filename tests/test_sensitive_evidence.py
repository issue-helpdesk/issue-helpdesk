"""검색 근거의 외부 전송 검사 (M4-2-3) 테스트. 기준은 docs/10 4장 ④, docs/08 1.4 외부 전송 규칙."""
import app.agent.sensitive.evidence as evidence_module
from app.agent.sensitive import Pseudonymizer, filter_evidence
from app.rag.search import ChunkHit, DocumentResult, LegacyResult


def doc(code: str, policy: str, text: str = '프로그램을 완전히 종료한 뒤 다시 실행합니다.', evidence=()) -> DocumentResult:
    return DocumentResult(unit_key=f'{code}@v1.0/item:3.1', chunk_type='ITEM', doc_code=code, title='가이드',
                          version='v1.0', location='3.1', heading_path='3. 조치 > 3.1', text=text,
                          chunks=(ChunkHit(1, 1, 0.7),), unit_score=0.7, score_type='cosine:bge-m3',
                          view_scope='ALL', transfer_policy=policy, evidence=evidence)


def case(no: str, policy: str, **kw) -> LegacyResult:
    fields = dict(legacy_inquiry_id=1, legacy_no=no, inquiry_type_code='ACC-01', title='계정 잠김',
                  text='계정 잠김 / 비밀번호 오류 / 잠금 해제', root_cause='비밀번호 오류', resolution='잠금 해제',
                  resolved_at='2026-07-09 13:51', score=0.6, score_type='cosine:bge-m3', view_scope='ALL',
                  transfer_policy=policy)
    return LegacyResult(**(fields | kw))


def test_allowed_goes_as_is():
    d = doc('IT-SW-003', 'ALLOWED', '김민지 담당자에게 010-1234-5678로 연락합니다.')
    f = filter_evidence([d], [], Pseudonymizer(['김민지']))
    assert f.documents == (d,)
    assert (f.blocked, f.all_blocked) == ((), False)


def test_masked_case_is_masked_and_pseudonymized():
    c = case('INQ-2026-00245', 'MASKED', title='김민지 계정 잠김',
             text='김민지 계정 잠김 / 비밀번호는 Abc123! 오류 / 010-1234-5678로 안내',
             root_cause='비밀번호는 Abc123! 오류', resolution='010-1234-5678로 안내',
             evidence=('010-1234-5678로 안내',))
    f = filter_evidence([], [c], Pseudonymizer(['김민지']))
    (r,) = f.legacy
    assert r.title == '[직원1] 계정 잠김'
    assert r.text == '[직원1] 계정 잠김 / 비밀번호는 ●●●●●● 오류 / [전화번호1]로 안내'
    assert (r.root_cause, r.resolution) == ('비밀번호는 ●●●●●● 오류', '[전화번호1]로 안내')
    assert r.evidence == ('[전화번호1]로 안내',)
    assert r.legacy_no == 'INQ-2026-00245'                       # 인용 키는 그대로


def test_masked_document_is_masked():
    text = '김민지 담당자에게 비밀번호는 Abc123! 라고 안내합니다.'
    (r,) = filter_evidence([doc('IT-X-001', 'MASKED', text, evidence=(text,))], [], Pseudonymizer(['김민지'])).documents
    assert r.text == '[직원1] 담당자에게 비밀번호는 ●●●●●● 라고 안내합니다.'
    assert r.evidence == (r.text,)
    assert r.doc_code == 'IT-X-001'


def test_numbering_continues_from_message():
    """이전 대화·이번 글에서 [직원1] 이었던 사람은 근거에서도 [직원1] (docs/10 3.1)"""
    p = Pseudonymizer(['김민지', '박서준'])
    assert p.apply('박서준 님이 잠겼어요') == '[직원1] 님이 잠겼어요'
    f = filter_evidence([], [case('INQ-1', 'MASKED', text='김민지 처리, 박서준 확인')], p)
    assert f.legacy[0].text == '[직원2] 처리, [직원1] 확인'


def test_blocked_and_unknown_are_removed():
    f = filter_evidence([doc('IT-SW-003', 'ALLOWED'), doc('IT-MAN-001', 'BLOCKED')],
                        [case('INQ-9', 'BLOCKED')], Pseudonymizer())
    assert [d.doc_code for d in f.documents] == ['IT-SW-003']
    assert f.legacy == ()
    assert f.blocked == ('IT-MAN-001', 'INQ-9')
    assert f.all_blocked is False


def test_all_blocked_only_when_results_existed():
    assert filter_evidence([doc('IT-MAN-001', 'BLOCKED')], [case('INQ-9', 'BLOCKED')], Pseudonymizer()).all_blocked
    assert filter_evidence([], [], Pseudonymizer()).all_blocked is False      # 처음부터 없음 = 근거부족


def test_masking_failure_blocks_only_that_result(monkeypatch):
    """MASKED 를 가리다 실패하면 그 근거만 BLOCKED 로 보고 뺀다 (docs/10 3.3)"""
    def broken(_text):
        raise RuntimeError('필터 오류')
    monkeypatch.setattr(evidence_module, 'mask_secrets', broken)
    f = filter_evidence([doc('IT-SW-003', 'ALLOWED')], [case('INQ-1', 'MASKED')], Pseudonymizer())
    assert [d.doc_code for d in f.documents] == ['IT-SW-003']
    assert (f.blocked, f.failed) == (('INQ-1',), ('INQ-1',))


def manual(policy: str, scope: str = 'AGENT', code: str = 'IT-ACC-001-M') -> DocumentResult:
    body = '계정 잠김 확인 질문\n본인 확인 L1 후 잠금을 푼다.'
    return DocumentResult(unit_key=f'{code}@v2.0/item:3.2', chunk_type='ITEM', doc_code=code,
                          title='김민지 SSO 매뉴얼', version='v2.0', location='3.2',
                          heading_path='3. 증상별 처리 절차 > 3.2 계정이 잠겼을 때', text=body,
                          chunks=(ChunkHit(1, 1, 0.7),), unit_score=0.7, score_type='cosine:bge-m3',
                          view_scope=scope, transfer_policy=policy, evidence=('본인 확인 L1 후 잠금을 푼다.',))


def test_blocked_manual_keeps_title_line_only():
    """매뉴얼 BLOCKED 는 제목 줄만 보낸다 (해결 사례 가이드화 기획, M4 결정 2026-11-08). 기록은 차단으로 남긴다."""
    f = filter_evidence([manual('BLOCKED')], [], Pseudonymizer(['김민지']))
    (r,) = f.documents
    assert r.text == '[직원1] SSO 매뉴얼 > 3. 증상별 처리 절차 > 3.2 계정이 잠겼을 때'    # 제목도 치환한다
    assert '본인 확인' not in r.text and r.evidence == ()
    assert (r.doc_code, r.location, r.unit_key) == ('IT-ACC-001-M', '3.2', 'IT-ACC-001-M@v2.0/item:3.2')
    assert f.title_only == ('IT-ACC-001-M@v2.0/item:3.2',)
    assert f.blocked == ('IT-ACC-001-M',) and f.all_blocked is False


def test_title_only_applies_to_manual_blocked_only():
    """열람 범위 ALL 인 BLOCKED(가이드)는 지금처럼 빼고, ALLOWED 매뉴얼은 그대로 보낸다."""
    f = filter_evidence([manual('BLOCKED', scope='ALL', code='IT-SEC-001'), manual('ALLOWED', code='IT-ACC-003-M')],
                        [], Pseudonymizer())
    assert [d.doc_code for d in f.documents] == ['IT-ACC-003-M']
    assert f.documents[0].text.startswith('계정 잠김')
    assert f.blocked == ('IT-SEC-001',) and f.title_only == ()


def test_title_line_failure_removes_that_result(monkeypatch):
    def broken(_text):
        raise RuntimeError('필터 오류')
    monkeypatch.setattr(evidence_module, 'mask_secrets', broken)
    f = filter_evidence([manual('BLOCKED')], [], Pseudonymizer())
    assert f.documents == () and f.title_only == ()
    assert (f.blocked, f.failed) == (('IT-ACC-001-M',), ('IT-ACC-001-M',)) and f.all_blocked
