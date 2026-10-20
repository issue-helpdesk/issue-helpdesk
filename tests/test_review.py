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


def test_sheet_lists_every_unit(acc001, evalset):
    md = sheet([acc001], 'T', evalset)
    for ref in {unit_ref(c.unit_key) for c in acc001.chunks}:
        assert f'`{ref}`' in md
    assert 'Q. 계정이 잠겼어요.' in md                       # FAQ 는 질문으로 구분


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


def test_check_questions_blank_template_rows_ignored(manifest, evalset, units):
    assert check_questions([_q('IT-ACC-001', '', '')], manifest, evalset, units) == ([], [])


def test_all_units_cover_rag_targets(manifest):
    refs = all_units(manifest)
    docs = {r.split('/', 1)[0] for r in refs}
    assert docs == {d for d, e in manifest.items() if e.get('rag_target', True)}
