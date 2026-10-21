"""가이드 검증 도구(D1~D6) 테스트: 평가셋 겹침, 검증 시트, 검색 질문 점검."""
import pytest

from app.rag.chunker import unit_ref
from app.rag.review import (EvalSet, all_units, check_questions, doc_checks, load, load_manifest, question_template,
                            read_questions, sheet, write_questions)


@pytest.fixture(scope='module')
def manifest():
    return load_manifest()


@pytest.fixture(scope='module')
def evalset():
    return EvalSet()


@pytest.fixture(scope='module')
def acc001(manifest):
    return load('IT-ACC-001', manifest)


@pytest.fixture(scope='module')
def units(manifest, acc001):
    """IT-ACC-001 단위만 (전체 57종 파싱은 check 명령에서)."""
    out = {}
    for c in acc001.chunks:
        out.setdefault(unit_ref(c.unit_key), c)
    return out


def test_eval_overlap_exact_and_similar(evalset):
    eid, q = evalset.rows[0]
    assert [o.kind for o in evalset.overlaps(f'앞 문장. {q} 뒤 문장') if o.eval_id == eid] == ['exact']
    assert evalset.overlaps('프린터 토너를 교체하는 방법') == []


def test_doc_checks_all_match(acc001):
    rows = doc_checks(acc001, base=None)
    assert [r for r in rows if r[3].startswith('⚠')] == []
    assert any(r[0] == '외부 전송 (transfer_policy)' for r in rows)


def test_doc_checks_catch_manifest_mismatch(manifest, acc001):
    wrong = dict(acc001.entry, access_level='사내 제한', scenarios=['ACC-02', 'ACC-99'])
    bad = type(acc001)(acc001.doc_no, wrong, acc001.doc, acc001.chunks)
    flagged = {r[0] for r in doc_checks(bad) if r[3].startswith('⚠')}
    assert {'열람 등급', '포함 시나리오 ↔ 항목 문의 유형'} <= flagged


def test_check_questions_uses_sheet_docs_as_targets(manifest, evalset, units, acc001):
    """양식에서 어떤 문서의 행을 통째로 지워도 검증 시트에 있으면 0개로 잡는다."""
    from app.rag.review import sheet_docs
    import tempfile, os
    md = sheet([acc001], 'T', evalset)
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(md)
    try:
        assert sheet_docs(f.name) == ['IT-ACC-001']
    finally:
        os.remove(f.name)
    errors, _ = check_questions([], manifest, evalset, units, targets=['IT-ACC-001'])
    assert errors == ['IT-ACC-001: 질문 0개 (문서마다 3개 이상)']


def test_coverage_clean_on_real_doc(acc001):
    from app.rag.review import coverage
    cov = coverage(acc001.doc, acc001.chunks)
    assert cov.expected > 100 and cov.missing == [] and cov.out_of_order == []


def test_coverage_catches_dropped_text_and_swapped_units(acc001):
    """청커가 문장을 빠뜨리거나 단위 순서를 바꾸면 잡아야 한다 (헛검사가 아님을 확인)."""
    import dataclasses
    from app.rag.review import coverage
    chunks = [dataclasses.replace(c) for c in acc001.chunks]
    item = next(c for c in chunks if c.chunk_type == 'item')
    lines = item.body.splitlines()
    victim = max(lines, key=len)                                   # 가장 긴 줄 하나를 지운다
    item.body = '\n'.join(x for x in lines if x != victim)
    assert victim.removeprefix('- ') in coverage(acc001.doc, chunks).missing   # 본문 줄에는 목록 기호가 붙어 있다

    swapped = [dataclasses.replace(c) for c in acc001.chunks]
    i = next(k for k, c in enumerate(swapped) if c.chunk_type == 'item')
    swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]          # 항목 두 개의 순서를 바꾼다
    cov = coverage(acc001.doc, swapped)
    assert cov.out_of_order and not cov.missing


def test_doc_checks_shows_coverage_row(acc001):
    row = next(r for r in doc_checks(acc001) if r[0].startswith('단위 본문'))
    assert row[3] == '일치'


def _scenario_result(review):
    return next(r[3] for r in doc_checks(review) if r[0] == '포함 시나리오 ↔ 항목 문의 유형')


def test_doc_checks_catch_extra_and_unknown_codes(acc001):
    """항목에만 있는 코드·분류체계에 없는 코드도 '일치'가 아니어야 한다 (리뷰 P2)."""
    import dataclasses
    chunks = [dataclasses.replace(c, inquiry_type_codes=list(c.inquiry_type_codes)) for c in acc001.chunks]
    next(c for c in chunks if c.inquiry_type_codes).inquiry_type_codes.append('ACC-99')
    bad = type(acc001)(acc001.doc_no, acc001.entry, acc001.doc, chunks)
    result = _scenario_result(bad)
    assert result.startswith('⚠') and 'manifest 에 없음: ACC-99' in result and '분류체계에 없는 코드: ACC-99' in result

    extra = type(acc001)(acc001.doc_no, dict(acc001.entry, scenarios=['ACC-02', 'ACC-04', 'ACC-01']), acc001.doc, acc001.chunks)
    assert '항목에 없음: ACC-01' in _scenario_result(extra) and '분류체계' not in _scenario_result(extra)


def test_sheet_command_keeps_filled_sheet(tmp_path):
    """다시 실행해도 사람이 채운 시트를 덮어쓰지 않는다. --force 일 때만 새로 만든다 (리뷰 P2)."""
    import runpy
    import sys

    def run(*args):
        old = sys.argv
        sys.argv = ['review', 'sheet', 'IT-ACC-001', '--name', 'T', '--out', str(tmp_path), *args]
        try:
            with pytest.raises(SystemExit) as ex:
                runpy.run_module('app.rag.review', run_name='__main__')
            assert ex.value.code == 0
        finally:
            sys.argv = old

    run()
    sheet_file, q_file = tmp_path / 'T_검증시트.md', tmp_path / 'T_질문.csv'
    sheet_file.write_text(sheet_file.read_text(encoding='utf-8').replace('| ☐ |', '| ☑ |', 1), encoding='utf-8')
    q_file.write_text('사람이 쓴 질문', encoding='utf-8-sig')
    run()
    assert '| ☑ |' in sheet_file.read_text(encoding='utf-8')
    run('--force')
    assert '| ☑ |' not in sheet_file.read_text(encoding='utf-8')
    assert q_file.read_text(encoding='utf-8-sig') == '사람이 쓴 질문'   # 질문은 --force 여도 그대로


def test_sheet_lists_every_unit(acc001, evalset):
    md = sheet([acc001], 'T', evalset)
    for ref in {unit_ref(c.unit_key) for c in acc001.chunks}:
        assert f'`{ref}`' in md
    assert 'Q. 계정이 잠겼어요.' in md                       # FAQ 는 질문으로 구분


def test_faq_title_strips_only_q_marker():
    from app.rag.review import _short
    assert _short('Q. 계정이 잠겼어요.', 40) == '계정이 잠겼어요.'
    assert _short('QR코드 인증이 안 돼요', 40) == 'QR코드 인증이 안 돼요'
    assert _short('Q: ' + '가' * 50, 40) == '가' * 40 + '…'


def test_question_template_roundtrip(tmp_path, acc001):
    path = tmp_path / 'q.csv'
    write_questions(path, question_template([acc001]))
    rows = read_questions(path)
    assert [(r['문서 번호'], r['번호']) for r in rows] == [('IT-ACC-001', str(n)) for n in (1, 2, 3)]


def _q(doc, q, a):
    return {'문서 번호': doc, '번호': '1', '질문': q, '정답 단위': a, '작성자': 't', '메모': ''}


def test_check_questions_ok(manifest, evalset, units):
    rows = [_q('IT-ACC-001', '통합 로그인 화면이 계속 처음으로 돌아가요', 'IT-ACC-001/item:3.3'),
            _q('IT-ACC-001', '로그인 실패를 몇 번 했더니 들어가지지가 않네요', 'IT-ACC-001/item:3.2'),
            _q('IT-ACC-001', '오래 안 쓴 계정이라 막혔다고 나와요', 'IT-ACC-001/item:3.4; IT-ACC-001/item:3.5')]
    assert check_questions(rows, manifest, evalset, units) == ([], [])


def test_check_questions_errors(manifest, evalset, units):
    eid, eq = evalset.rows[0]
    rows = [_q('IT-ACC-001', eq, 'IT-ACC-001/item:3.1'),                       # 평가셋 문장
            _q('IT-ACC-001', '비밀번호가 틀렸대요', 'IT-ACC-001/item:9.9'),          # 없는 단위
            _q('IT-ACC-001', '비밀번호가 틀렸대요', ''),                           # 같은 질문 · 정답 없음
            _q('IT-XXX-001', '아무 질문', 'IT-ACC-001/item:3.1')]                  # 없는 문서
    errors, _ = check_questions(rows, manifest, evalset, units)
    text = '\n'.join(errors)
    for part in (eid, 'item:9.9 가 없음', '같은 질문', '정답 단위가 비어', 'manifest 에 없는', 'IT-XXX-001: 질문 1개'):
        assert part in text


def test_check_questions_blank_template_fails(manifest, evalset, units, acc001):
    """질문을 하나도 안 쓴 양식은 통과하면 안 된다 (리뷰 P1)."""
    rows = [dict(r, 번호=str(r['번호'])) for r in question_template([acc001])]
    errors, _ = check_questions(rows, manifest, evalset, units)
    assert errors == ['IT-ACC-001: 질문 0개 (문서마다 3개 이상)']
    assert check_questions([], manifest, evalset, units)[0] == ['문서 번호가 있는 행이 없음 (sheet 명령이 만든 양식을 쓴다)']


def test_check_questions_partly_filled_catches_empty_doc(manifest, evalset, units):
    rows = [_q('IT-ACC-001', '통합 로그인 화면이 계속 처음으로 돌아가요', 'IT-ACC-001/item:3.3'),
            _q('IT-ACC-001', '로그인 실패를 몇 번 했더니 들어가지지가 않네요', 'IT-ACC-001/item:3.2'),
            _q('IT-ACC-001', '오래 안 쓴 계정이라 막혔다고 나와요', 'IT-ACC-001/item:3.4'),
            _q('IT-ACC-002', '', ''), _q('IT-ACC-002', '', '')]
    errors, _ = check_questions(rows, manifest, evalset, units)
    assert errors == ['IT-ACC-002: 질문 0개 (문서마다 3개 이상)']


def test_all_units_cover_rag_targets(manifest):
    refs = all_units(manifest)
    docs = {r.split('/', 1)[0] for r in refs}
    assert docs == {d for d, e in manifest.items() if e.get('rag_target', True)}
