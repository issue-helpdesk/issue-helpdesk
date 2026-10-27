"""검색 평가 도구(M2-2-2) 테스트: 지표 계산, 같은 본문 인정, 묶음 분리, 역할 제한, 검색기."""
import math

import pytest

from app.rag.evaluation import (BM25Retriever, Hit, Question, Unit, VectorRetriever, corpus_units, evaluate,
                                load_eval_set, load_guide_questions, restrict_to_role, same_body, scores, summarize,
                                tokens)


class FakeRetriever:
    """질문마다 정해 둔 순서로 돌려준다."""
    name = 'fake'

    def __init__(self, table):
        self.table = table

    def search(self, query, k=10):
        return [Hit(r, r.split('/')[0], 1.0) for r in self.table[query][:k]]


def test_scores_by_hand():
    s = scores([1, 3, None, 6])                 # 4문항: 1위, 3위, 못 맞힘, 6위
    assert s['n'] == 4
    assert s['hit@1'] == 0.25 and s['hit@3'] == 0.5 and s['hit@5'] == 0.5
    assert math.isclose(s['mrr@10'], (1 + 1 / 3 + 1 / 6) / 4)


def test_evaluate_ranks_unit_and_doc():
    q = Question('guide', 'A#1', 'q1', {'A/item:3.2'}, {'A'}, ['전체'])
    r = evaluate(FakeRetriever({'q1': ['B/item:3.1', 'A/item:3.1', 'A/item:3.2']}), [q])[0]
    assert (r.unit_rank, r.doc_rank) == (3, 2)        # 문서는 2위에서, 단위는 3위에서 맞힘


def test_multiple_answers_any_counts():
    q = Question('guide', 'A#1', 'q1', {'A/item:3.1', 'A/item:3.3'}, {'A'}, ['전체'])
    assert evaluate(FakeRetriever({'q1': ['A/item:3.3']}), [q])[0].unit_rank == 1


def test_same_body_units_are_equivalent():
    units = [Unit('X/faq:FAQ-007', 'X', 't', 'h1', 'ALL'), Unit('Y/faq:FAQ-007', 'Y', 't', 'h1', 'ALL'),
             Unit('Y/item:3.1', 'Y', 't', 'h2', 'ALL')]
    eq = same_body(units)
    assert eq['X/faq:FAQ-007'] == {'X/faq:FAQ-007', 'Y/faq:FAQ-007'} and eq['Y/item:3.1'] == {'Y/item:3.1'}


@pytest.fixture(scope='module')
def units():
    return corpus_units()


def test_corpus_units_match_baseline(units):
    assert len(units) == len({u.ref for u in units}) and {u.view_scope for u in units} == {'ALL', 'AGENT'}
    assert len({u.doc for u in units}) == 56


def test_guide_questions_groups_and_equivalence(units):
    qs = load_guide_questions(units)
    assert len(qs) == 228
    g = lambda name: sum(name in q.groups for q in qs)
    assert (g('반말·무례'), g('쉬움'), g('분기 질문')) == (56, 36, 8)
    faq7 = next(q for q in qs if q.qid == 'IT-NET-003#3')                 # 같은 FAQ-007 이 NET-001 에도 있다
    assert {'IT-NET-001/faq:FAQ-007', 'IT-NET-003/faq:FAQ-007'} <= faq7.answers


def test_eval_set_maps_scenario_to_guides():
    qs, skipped = load_eval_set()
    assert skipped == ['EV-037', 'EV-038', 'EV-039', 'EV-040'] and len(qs) == 46
    assert all(q.answer_docs and all(d.startswith('IT-') for d in q.answer_docs) for q in qs)
    assert {q.groups[1] for q in qs} == {'기존 평가 40건', '확장 평가 10건'}


def test_employee_role_drops_manual_only_questions(units):
    qs = load_guide_questions(units)
    keep, dropped = restrict_to_role(qs, units, 'EMPLOYEE')
    assert dropped and all(qid.split('#')[0].endswith('-M') for qid in dropped)
    assert len(keep) + len(dropped) == len(qs)


def test_summarize_puts_total_first():
    qs = [Question('guide', 'A#1', 'q1', {'A/item:3.1'}, {'A'}, ['전체', '반말·무례']),
          Question('eval', 'EV-1', 'q2', set(), {'A'}, ['전체', '기존 평가 40건'])]
    s = summarize(evaluate(FakeRetriever({'q1': ['A/item:3.1'], 'q2': ['B/item:3.1']}), qs))
    assert list(s['guide']) == ['전체', '반말·무례'] and s['guide']['전체']['단위']['hit@1'] == 1.0
    assert s['eval']['전체']['문서']['hit@5'] == 0.0 and '단위' not in s['eval']['전체']


def test_tokens_overlap_korean_particles():
    assert set(tokens('로그인')) & set(tokens('로그인이 안 돼요'))


def test_bm25_finds_obvious_unit(units):
    hits = BM25Retriever(units).search('AUTH-101 아이디 또는 비밀번호가 일치하지 않습니다', 5)
    assert 'IT-ACC-001/item:3.1' in [h.ref for h in hits[:3]]     # 3장 항목 목록 표(chapter:3)도 같은 문구라 앞에 올 수 있다


def test_vector_retriever_groups_parts_by_unit():
    rows = [('A/item:3.1', 'A', [1.0, 0.0]), ('A/item:3.1', 'A', [0.6, 0.8]), ('B/item:3.1', 'B', [0.0, 1.0])]
    r = VectorRetriever('fake', rows, lambda q: [1.0, 0.0])
    hits = r.search('q', 5)
    assert [h.ref for h in hits] == ['A/item:3.1', 'B/item:3.1']     # 조각 둘인 단위는 한 번만, 가장 높은 점수로
    assert hits[0].score == pytest.approx(1.0)


# ── Codex 리뷰(작업대/검수/M2-2-2_리뷰.md) 회귀 시험 ──────────────────────

def _q(ans, docs=None):
    return Question('guide', 'X#1', 'q', set(ans), set(docs or {a.split('/')[0] for a in ans}), ['전체'])


def test_same_body_results_take_one_rank():
    """P1: 본문·정책이 같은 A·B는 한 순위로 묶인다. 정답 C는 3위가 아니라 2위 (리뷰 재현 ②)."""
    rows = [('A/faq:F', 'A', [1.0, 0.0]), ('B/faq:F', 'B', [1.0, 0.0]), ('C/item:3.1', 'C', [0.8, 0.6])]
    dup = {'A/faq:F': ('h', 'ALLOWED'), 'B/faq:F': ('h', 'ALLOWED'), 'C/item:3.1': ('c', 'ALLOWED')}
    r = VectorRetriever('fake', rows, lambda q: [1.0, 0.0], dup)
    assert evaluate(r, [_q({'C/item:3.1'})])[0].unit_rank == 2
    res = evaluate(r, [_q({'B/faq:F'}, {'B'})])[0]           # 묶여 들어간 B도 정답으로 센다 (단위·문서 모두)
    assert (res.unit_rank, res.doc_rank) == (1, 1) and res.hits[0].also == [('B/faq:F', 'B')]


def test_collapse_cuts_after_merging():
    from app.rag.evaluation import collapse
    hits = [Hit(f'D{i}/chapter:6', f'D{i}', 1.0) for i in range(5)] + [Hit('A/item:3.1', 'A', 0.5)]
    dup = {h.ref: ('same', 'ALLOWED') for h in hits[:5]}
    out = collapse(hits, dup, 2)
    assert [h.ref for h in out] == ['D0/chapter:6', 'A/item:3.1'] and len(out[0].also) == 4


def test_same_body_needs_same_transfer_policy():
    units = [Unit('X/chapter:6', 'X', 't', 'h', 'ALL', 'ALLOWED'), Unit('X-M/chapter:6', 'X-M', 't', 'h', 'AGENT', 'BLOCKED')]
    assert same_body(units)['X/chapter:6'] == {'X/chapter:6'}       # 8장: 전송 정책까지 같아야 묶는다


def test_run_dir_never_overwrites(tmp_path):
    """P2: 같은 이름으로 다시 실행해도 앞 결과를 덮어쓰지 않는다."""
    from app.rag.evaluation import new_run_dir
    a = new_run_dir(str(tmp_path), '20261026_170000_bm25_AGENT')
    open(f'{a}/요약.json', 'w').write('first')
    b = new_run_dir(str(tmp_path), '20261026_170000_bm25_AGENT')
    assert b != a and b.endswith('-2') and open(f'{a}/요약.json').read() == 'first'


def test_fingerprints_change_with_units():
    from app.rag.evaluation import units_fingerprint
    u = [Unit('A/item:3.1', 'A', 't', 'h1', 'ALL', 'ALLOWED')]
    assert units_fingerprint(u) != units_fingerprint([Unit('A/item:3.1', 'A', 't', 'h2', 'ALL', 'ALLOWED')])


def test_eval_set_role_restriction(units):
    manual_only = Question('eval', 'EV-X', 'q', set(), {'IT-ACC-001-M'}, ['전체'])
    keep, dropped = restrict_to_role([manual_only], units, 'EMPLOYEE')
    assert keep == [] and dropped == ['EV-X']


def test_db_connect_error_hides_address():
    from app.rag.evaluation import db_vector_rows
    with pytest.raises(RuntimeError) as ex:
        db_vector_rows('postgresql://user:secret-pw@127.0.0.1:1/x', 'kure-v1@x/v1')
    assert 'secret-pw' not in str(ex.value) and '127.0.0.1' not in str(ex.value)


def test_many_same_body_units_still_fill_k(units):
    """같은 '문의처' 장이 27개 문서에 있어도 묶은 뒤 결과가 k개 찬다 (후보를 충분히 받음)."""
    r = BM25Retriever(units)
    q = next(x for x in load_guide_questions(units) if x.qid == 'IT-STD-001#4')
    res = evaluate(r, [q])[0]
    assert len(res.hits) == 10 and res.unit_rank == 9


# ── 평가셋 단위 정답 · 실제 search() 검색기 ──────────────────────────────

def test_eval_set_unit_answers_from_scenario_codes(units):
    qs, _ = load_eval_set(units=units)
    assert all(q.answers for q in qs)                         # 46문항 모두 그 시나리오가 붙은 단위가 있다
    by_ref = {u.ref: u for u in units}
    q = qs[0]
    scen = next(r for r in __import__('csv').DictReader(open(__import__('app.rag.evaluation', fromlist=['EVAL_CSV']).EVAL_CSV,
                encoding='utf-8-sig')) if r['eval_id'] == q.qid)['expected_scenario']
    assert any(scen in by_ref[a].codes for a in q.answers)


def test_summarize_scores_eval_units_when_answers_exist():
    qs = [Question('eval', 'EV-1', 'q', {'A/item:3.1'}, {'A'}, ['전체'])]
    s = summarize(evaluate(FakeRetriever({'q': ['A/item:3.2', 'A/item:3.1']}), qs))
    assert s['eval']['전체']['문서']['hit@1'] == 1.0 and s['eval']['전체']['단위']['hit@1'] == 0.0
    assert s['eval']['전체']['단위']['hit@3'] == 1.0


def test_hits_from_search_response_keeps_also_in():
    from types import SimpleNamespace as NS
    from app.rag.evaluation import hits_from_response
    resp = NS(documents=(NS(unit_key='IT-NET-003@v2.0/faq:FAQ-007', doc_code='IT-NET-003', unit_score=0.81,
                            also_in=('IT-NET-001@v2.0/faq:FAQ-007',)),))
    h = hits_from_response(resp)[0]
    assert h.ref == 'IT-NET-003/faq:FAQ-007' and h.refs == {'IT-NET-003/faq:FAQ-007', 'IT-NET-001/faq:FAQ-007'}
    assert h.docs == {'IT-NET-003', 'IT-NET-001'}


def test_final_k_retriever_gets_exact_k():
    seen = []

    class Api:
        final_k, dup_key, name = True, None, 'api'

        def search(self, q, k):
            seen.append(k)
            return []
    evaluate(Api(), [Question('guide', 'A#1', 'q', {'A/item:3.1'}, {'A'}, ['전체'])])
    assert seen == [10]                                       # search() 의 k × 3 · k × 6 규칙을 그대로 쓰게 k 그대로


def test_code_fingerprint_covers_search_and_embedding(monkeypatch):
    """재검수 P3: search()·Embedder 코드가 바뀌어도 지문이 달라진다."""
    import app.rag.evaluation as ev
    seen = []
    monkeypatch.setattr(ev, 'file_hash', lambda files: seen.extend(files) or 'x')
    ev.code_fingerprint()
    assert any('search' in f and f.endswith('service.py') for f in seen)
    assert any('embedding' in f and f.endswith('embedder.py') for f in seen)
