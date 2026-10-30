"""모델 비교(compare.py)의 'FAQ 시나리오 코드 이어받기' 테스트 (M3-4-1). 모델·DB 없이 작은 가짜 청크로 본다."""
from types import SimpleNamespace

from app.rag.search.compare import Unit, inherit_faq_codes, load_eval


def item(doc, faq_ids, codes):
    return SimpleNamespace(chunk_type='item', doc_no=doc, faq_ids=faq_ids, inquiry_type_codes=codes)


def faq_unit(doc, number):
    return Unit(f'{doc}@v2.0/faq:{number}', doc, 'faq')


def test_faq_inherits_codes_of_items_that_point_to_it():
    chunks = [item('IT-ACC-002', ['FAQ-001'], ['ACC-01'])]
    units = {'IT-ACC-002@v2.0/faq:FAQ-001': faq_unit('IT-ACC-002', 'FAQ-001')}
    assert inherit_faq_codes(chunks, units)['IT-ACC-002@v2.0/faq:FAQ-001'].codes == {'ACC-01'}


def test_faq_takes_all_codes_when_several_items_point_to_it():
    chunks = [item('IT-NET-001', ['FAQ-007'], ['NET-02']), item('IT-NET-001', ['FAQ-007'], ['NET-01'])]
    units = {'IT-NET-001@v2.0/faq:FAQ-007': faq_unit('IT-NET-001', 'FAQ-007')}
    assert inherit_faq_codes(chunks, units)['IT-NET-001@v2.0/faq:FAQ-007'].codes == {'NET-01', 'NET-02'}


def test_same_faq_number_in_another_document_is_not_mixed():
    """FAQ 번호는 문서마다 따로 센다. 다른 문서의 같은 번호에서 코드를 가져오면 안 된다."""
    chunks = [item('IT-HW-001', ['FAQ-001'], ['HW-01'])]
    units = {'IT-ACC-002@v2.0/faq:FAQ-001': faq_unit('IT-ACC-002', 'FAQ-001')}
    assert inherit_faq_codes(chunks, units)['IT-ACC-002@v2.0/faq:FAQ-001'].codes == set()


def test_faq_nobody_points_to_stays_empty():
    units = {'IT-SW-003@v2.0/faq:FAQ-099': faq_unit('IT-SW-003', 'FAQ-099')}
    assert inherit_faq_codes([], units)['IT-SW-003@v2.0/faq:FAQ-099'].codes == set()


def test_items_keep_their_codes_and_the_original_is_not_changed():
    own = Unit('IT-ACC-002@v2.0/item:3.4', 'IT-ACC-002', 'item', {'ACC-01'})
    faq = faq_unit('IT-ACC-002', 'FAQ-001')
    units = {own.key: own, faq.key: faq}
    out = inherit_faq_codes([item('IT-ACC-002', ['FAQ-001'], ['ACC-01'])], units)
    assert out[own.key].codes == {'ACC-01'}
    assert faq.codes == set()                                   # 원본은 그대로


def test_inherited_faq_becomes_a_correct_answer(tmp_path, monkeypatch):
    """이어받은 뒤에는 그 시나리오의 정답 항목에 FAQ 단위가 들어간다."""
    import app.rag.search.compare as compare

    csv_path = tmp_path / 'eval.csv'
    csv_path.write_text('eval_id,query,expected_scenario,expected_action\nEV-X,질문,ACC-01,ANSWER\n', encoding='utf-8-sig')
    monkeypatch.setattr(compare, 'EVAL', str(csv_path))
    units = {'IT-ACC-002@v2.0/item:3.4': Unit('IT-ACC-002@v2.0/item:3.4', 'IT-ACC-002', 'item', {'ACC-01'}),
             'IT-ACC-002@v2.0/faq:FAQ-001': faq_unit('IT-ACC-002', 'FAQ-001')}
    items, _ = load_eval(units, {'IT-ACC-002': {'ACC-01'}})
    assert items[0]['gold_units'] == {'IT-ACC-002@v2.0/item:3.4'}              # 지금: FAQ 는 정답이 아님
    inherited = inherit_faq_codes([item('IT-ACC-002', ['FAQ-001'], ['ACC-01'])], units)
    gold = {k for k, u in inherited.items() if 'ACC-01' in u.codes}
    assert gold == {'IT-ACC-002@v2.0/item:3.4', 'IT-ACC-002@v2.0/faq:FAQ-001'}
