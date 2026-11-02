"""판단 평가(M2-4-1) 테스트: 평가셋 읽기, 정답 Mock 으로 판단 흐름 끝까지, 서버 팀 규칙, 채점 제외 규칙, 기록.
DB·API 키 없이 가짜 기준 정보와 가짜 검색으로 돌린다."""
import csv
import json
from dataclasses import replace

import pytest

from app.agent.llm import CategoryInfo, Taxonomy, TypeInfo
from app.rag.evaluation.judgment import (GUIDED_COL, TEAM_ASSIGNED, TEAM_GUIDED, TEAM_SKIP, EvalItem, Judged,
                                         Reference, cause, judge_item, load_items, main, near_urgency, run, score,
                                         summary_md, team_of, write)
from app.rag.search import ChunkHit, DocumentResult, SearchResponse

REF = Reference(
    Taxonomy(categories=(CategoryInfo('ACC', '계정'), CategoryInfo('SEC', '보안')),
             types=(TypeInfo('ACC-01', 'ACC', '비밀번호 초기화', 'REQUEST', 'P3'),
                    TypeInfo('SEC-04', 'SEC', '피싱 메일', 'INCIDENT', 'P1'))),
    {'ACC-01': '서비스데스크', 'SEC-04': '정보보안팀'}, '서비스데스크', ('김민지',))
DOC = DocumentResult(unit_key='IT-ACC-002@v2.0/faq:FAQ-001', chunk_type='FAQ', doc_code='IT-ACC-002', title='계정 FAQ',
                     version='v2.0', location='FAQ-001', heading_path='FAQ', text='비밀번호는 포털에서 직접 바꿉니다.',
                     chunks=(ChunkHit(1, 1, 0.9),), unit_score=0.9, score_type='cosine:bge-m3', view_scope='ALL',
                     transfer_policy='ALLOWED', inquiry_type_codes=('ACC-01',))
OTHER = DocumentResult(unit_key='IT-NET-001@v2.0/item:3.1', chunk_type='ITEM', doc_code='IT-NET-001', title='VPN',
                       version='v2.0', location='3.1', heading_path='3.1', text='VPN 클라이언트를 다시 설치합니다.',
                       chunks=(ChunkHit(2, 1, 0.9),), unit_score=0.9, score_type='cosine:bge-m3', view_scope='ALL',
                       transfer_policy='ALLOWED')


class FakeSearch:
    """DbSearch 대신. 정해 둔 결과를 돌려주고 마지막 결과를 남긴다."""
    def __init__(self, *documents):
        self.documents, self.last, self.requests = documents, None, []

    def __call__(self, req):
        self.requests.append(req)
        self.last = SearchResponse(query=req.query, model='bge-m3', threshold=0.6, documents=self.documents)
        return self.last


def item(**kw) -> EvalItem:
    return EvalItem(**({'eval_id': 'EV-001', 'query': '비번 까먹었는데 어디서 바꿔요?', 'category': 'ACC',
                        'scenario': 'ACC-01', 'urgency': 'P3', 'action': 'ANSWER', 'additional': 'NONE',
                        'team': '서비스데스크', 'team_scoring': TEAM_GUIDED, 'split': '기존 평가 40건',
                        'answer_docs': frozenset({'IT-ACC-002'}),
                        'answer_units': frozenset({'IT-ACC-002/faq:FAQ-001'})} | kw))


def judged(it: EvalItem, round_=1, **pred) -> Judged:
    p = {'category': it.category, 'scenario': it.scenario, 'urgency': it.urgency, 'action': it.action,
         'team': it.team} | pred
    return Judged(it, round_, p)


def test_load_items_reads_whole_eval_set():
    items = {i.eval_id: i for i in load_items()}
    assert len(items) == 50
    assert sum(i.split == '기존 평가 40건' for i in items.values()) == 40
    scoring = [i.team_scoring for i in items.values()]
    assert (scoring.count(TEAM_ASSIGNED), scoring.count(TEAM_GUIDED), scoring.count(TEAM_SKIP)) == (26, 22, 2)
    oos = items['EV-038']                                    # 범위 밖: '-' 는 None
    assert (oos.category, oos.scenario, oos.urgency, oos.team, oos.action) == (None, None, None, None, 'OUT_OF_SCOPE')
    assert items['EV-001'].answer_docs and not items['EV-039'].answer_docs      # 시나리오 없는 문항은 정답 가이드 없음
    assert 'IT-ACC-002/faq:FAQ-001' in items['EV-001'].answer_units            # FAQ 코드 이어받기(#152) 뒤 정답 단위


def test_oracle_runs_flow_to_the_end_and_cites_matching_result():
    search = FakeSearch(OTHER, DOC)
    j = judge_item(item(), 'mock:oracle', REF, search)
    assert (j.next_step, j.failure, j.calls) == ('answered', None, 2)            # 1차 → 검색 → 2차
    assert j.predicted == {'category': 'ACC', 'scenario': 'ACC-01', 'urgency': 'P3', 'action': 'ANSWER',
                           'team': '서비스데스크'}
    assert j.evidence == [DOC.unit_key]                     # 1위가 아니라 정답 세부 유형이 붙은 결과
    assert j.searched and j.found_doc is True and j.found_unit is True
    assert j.top_units == [OTHER.unit_key, DOC.unit_key]
    assert search.requests[0].service_role == 'EMPLOYEE'
    assert cause(j) == ''


def test_flow_corrections_show_up_as_wrong_answers():
    """정답 Mock 이라도 근거가 없으면 흐름이 ANSWER 를 담당자 연결로 바꾼다 → 검색 쪽 원인."""
    j = judge_item(item(), 'mock:oracle', REF, FakeSearch())
    assert j.predicted['action'] == 'ESCALATE' and 'NO_EVIDENCE' in j.overrides
    assert j.found_doc is False and cause(j) == '검색: 가이드'


def test_grouped_result_counts_as_found():
    """같은 본문이라 대표 결과에 묶인 정답(also_in)도 찾은 것으로 본다 (검색 평가 Hit.refs 와 같다)."""
    grouped = replace(OTHER, also_in=(DOC.unit_key,))
    j = judge_item(item(action='ESCALATE', team_scoring=TEAM_ASSIGNED), 'mock:safe', REF, FakeSearch(grouped))
    assert (j.found_doc, j.found_unit, cause(j)) == (True, True, '판단')


def test_right_guide_wrong_item_is_search_side():
    other_item = replace(DOC, unit_key='IT-ACC-002@v2.0/item:3.9', inquiry_type_codes=())
    j = judge_item(item(action='ESCALATE', team_scoring=TEAM_ASSIGNED), 'mock:safe', REF, FakeSearch(other_item))
    assert (j.found_doc, j.found_unit, cause(j)) == (True, False, '검색: 항목')


def test_equivalent_unit_in_other_guide_is_not_search_side():
    """같은 본문이라 정답으로 넓힌 다른 문서의 항목을 찾았으면 가이드 적중과 상관없이 '판단'."""
    it = item(action='ESCALATE', team_scoring=TEAM_ASSIGNED,
              answer_units=frozenset({'IT-ACC-002/faq:FAQ-001', 'IT-NET-001/item:3.1'}))
    j = judge_item(it, 'mock:safe', REF, FakeSearch(OTHER))
    assert (j.found_doc, j.found_unit, cause(j)) == (False, True, '판단')


def test_interrupt_in_progress_output_keeps_finished_items():
    def progress(_):
        raise KeyboardInterrupt
    js, stopped = run('mock:oracle', [item(), item(eval_id='EV-002')], REF, FakeSearch(DOC), progress=progress)
    assert len(js) == 1 and stopped == '1회 EV-001 에서 멈춤 (KeyboardInterrupt)'


def test_repeat_range_uses_only_finished_rounds():
    a, b = item(), item(eval_id='EV-002')
    md = summary_md({'meta': {'판단기': 'x'}, '점수': {1: score([judged(a), judged(b)]), 2: score([judged(a)]),
                                                       3: score([judged(a, action='ESCALATE'), judged(b)])},
                     '처리 방향 혼동표': {}, '추가 처리': [], '틀린 문항': []})
    assert '반복 2회 범위 (전체, 끝까지 돈 회차만)' in md and '| 처리 방향 | 50% | 100% |' in md


def test_run_keeps_finished_items_when_search_fails():
    class Broken(FakeSearch):
        def __call__(self, req):
            if len(self.requests) == 1:
                raise RuntimeError('DB 연결 실패')
            return super().__call__(req)
    js, stopped = run('mock:oracle', [item(), item(eval_id='EV-002')], REF, Broken(DOC))
    assert [j.item.eval_id for j in js] == ['EV-001'] and stopped == '1회 EV-002 에서 멈춤 (RuntimeError)'
    assert summary_md({'meta': {'판단기': 'x'}, '점수': {}}).endswith('끝낸 문항이 없습니다.\n')


def test_cli_rejects_bad_selection_before_opening_db(capsys):
    assert main(['--database-url', 'postgresql://nowhere/x', '--ids', 'EV-001,EV-999']) == 2
    assert 'EV-999' in capsys.readouterr().out
    for bad in (['--limit', '0'], ['--repeat', '-1']):
        with pytest.raises(SystemExit):
            main(['--database-url', 'postgresql://nowhere/x', *bad])


def test_safe_mock_escalates_everything():
    j = judge_item(item(), 'mock:safe', REF, FakeSearch(DOC))
    assert j.predicted['action'] == 'ESCALATE' and j.predicted['category'] is None
    assert j.predicted['team'] == '서비스데스크' and cause(j) == '판단'


def test_team_follows_server_rule():
    assert team_of('ESCALATE', 'SEC-04', REF) == '정보보안팀'
    assert team_of('OUT_OF_SCOPE', 'SEC-04', REF) == '서비스데스크'     # 범위 밖은 서비스데스크
    assert team_of('ESCALATE', None, REF) == '서비스데스크'             # 세부 유형을 모르면
    assert team_of('ESCALATE', 'XXX-99', REF) == '서비스데스크'


def test_score_skips_dash_answers_and_team_exclusions():
    js = [judged(item()),
          judged(item(eval_id='EV-038', category=None, scenario=None, urgency=None, action='OUT_OF_SCOPE', team=None,
                      team_scoring=TEAM_SKIP), category='SEC', team='서비스데스크'),
          judged(item(eval_id='EV-050', category='SEC', scenario='SEC-04', urgency='P1', action='ESCALATE',
                      team='정보보안팀', team_scoring=TEAM_ASSIGNED, split='확장 평가 10건'), urgency='P2')]
    s = score(js)
    assert s['전체']['category'] == {'n': 2, 'acc': 1.0}            # EV-038 '-' 는 빼고
    assert s['전체']['action'] == {'n': 3, 'acc': 1.0}              # 처리 방향은 전부
    assert s['전체']['team']['n'] == 2                               # 팀 평가 제외는 빼고
    assert s['전체']['urgency']['acc'] == 0.5 and s['전체']['긴급도 ±1']['acc'] == 1.0
    assert s['전체'][f'팀 ({TEAM_ASSIGNED})']['n'] == 1 and s['전체'][GUIDED_COL]['n'] == 1
    assert s['확장 평가 10건']['urgency'] == {'n': 1, 'acc': 0.0}
    assert near_urgency([judged(item(), urgency=None)]) == {'n': 1, 'acc': 0.0}   # 확정 긴급도가 없으면 틀림
    vague = judged(item(eval_id='EV-039', category='HW', scenario=None, urgency='P3', action='ASK_MORE',
                        team='엔드포인트지원팀', team_scoring=TEAM_SKIP), category='SW', urgency='P2')
    assert [score([vague])['전체'][c]['n'] for c in ('category', 'urgency', '긴급도 ±1', 'team')] == [0, 0, 0, 0]  # 모호 문항
    assert score([vague])['전체']['action'] == {'n': 1, 'acc': 1.0}                                   # 처리 방향은 채점


def test_write_keeps_values_only_and_reports_repeat_range(tmp_path):
    a = judge_item(item(), 'mock:oracle', REF, FakeSearch(DOC))
    b = judged(item(), round_=2, scenario=None)
    summary = write(str(tmp_path), [a, b], {'판단기': 'mock:oracle'})
    rows = list(csv.reader(open(tmp_path / '문항별.csv', encoding='utf-8-sig')))
    assert len(rows) == 3 and rows[1][0] == '1' and rows[2][0] == '2'
    text = (tmp_path / '문항별.csv').read_text(encoding='utf-8-sig') + (tmp_path / '요약.json').read_text(encoding='utf-8')
    assert '안내드립니다' not in text and DOC.text not in text     # 응답·근거 원문은 저장하지 않는다
    assert set(json.loads((tmp_path / '요약.json').read_text(encoding='utf-8'))['점수']) == {'1', '2'}
    md = summary_md(summary)
    assert '반복 2회 범위' in md and '| 세부 유형 | 0% | 100% |' in md
    assert [(x['회차'], x['틀린 칸']) for x in summary['틀린 문항']] == [(2, ['세부 유형'])]   # 뒤 회차의 틀림도 남는다
    assert '## 정확도 (2회차' in md


def test_known_miss_is_counted_but_annotated(tmp_path):
    ev040 = item(eval_id='EV-040', category='SEC', scenario=None, urgency='P4', additional='POLICY_GUIDANCE',
                 team='정보보안팀')
    j = judged(ev040, team='서비스데스크')
    assert score([j])['전체']['team'] == {'n': 1, 'acc': 0.0}                  # 점수에는 그대로 센다
    assert '알려진 틀림' in summary_md(write(str(tmp_path), [j], {'판단기': 'x'}))
