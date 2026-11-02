"""판단 평가 (WBS M2-4-1). 평가셋 문의를 실제 판단 흐름(M4-2-1 run_flow)에 넣고 분류·세부 유형·긴급도·처리 방향·팀을 채점한다.

    uv run python -m app.rag.evaluation.judgment --judge mock:oracle --database-url <로컬 DB>   # 키 없이 끝까지 (도구 확인)
    uv run python -m app.rag.evaluation.judgment --judge mock:safe --database-url <로컬 DB>     # 안전 기본값만 (바닥 점수)
    uv run python -m app.rag.evaluation.judgment --judge claude --database-url <로컬 DB> --limit 3   # 실제 Claude (LLM_API_KEY)

판단기 (--judge)
- claude      : 서버와 같은 모델 설정 (get_llm_adapter: 루트 .env 의 LLM_API_KEY·LLM_MODEL). 문항당 기본 1~2회 호출
                (형식 오류·안전하지 않은 답이면 다시 부르고, SDK 재시도는 따로 있다)
- mock:oracle : 평가셋 정답 라벨을 AI 출력으로 넣었을 때 흐름이 끝까지 잇고 보정·서버 팀 규칙이 정답을 바꾸는 곳을 보인다.
                facts 는 비워 두므로(사고 사실 없음) 사실 기반 긴급도 규칙을 검증하지는 않는다
- mock:safe   : 모든 호출이 안전 기본값 (담당자 연결 제안)

- 한 문항 = 새 대화의 첫 글 하나 (이전 대화·모은 사실 없음). 사용자는 직원(EMPLOYEE).
- 검색은 실제 search() (C, M3-2-2) 를 로컬 DB 에 읽기 전용으로. 분류 체계·팀·직원 이름도 그 DB 에서 읽는다.
- 팀은 서버 규칙 그대로: 범위 밖이거나 세부 유형을 모르면 서비스데스크, 아니면 세부 유형의 기본 그룹 (services/inquiry.py).
- 프롬프트·응답 원문(reply 포함)은 저장하지 않는다 (docs/10 5.3). 정답·예측 값과 실패 사유만.
- 결과는 작업대/평가결과/<날짜시각>_판단_<판단기>/ 에 문항별.csv · 요약.md · 요약.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from ..chunker import unit_ref
from . import EVAL_CSV, OUT, TAXONOMY, corpus_units, file_hash, git_state, load_eval_set, new_run_dir

FIELDS = ('category', 'scenario', 'urgency', 'action', 'team')
NAMES = {'category': '분류', 'scenario': '세부 유형', 'urgency': '긴급도', 'action': '처리 방향', 'team': '팀'}
URGENCY_ORDER = ('P1', 'P2', 'P3', 'P4')
TEAM_ASSIGNED, TEAM_GUIDED, TEAM_SKIP = '배정팀 비교', '안내 지원팀 비교', '팀 평가 제외'
GUIDED_COL = f'팀 ({TEAM_GUIDED})'
JUDGES = ('claude', 'mock:oracle', 'mock:safe')
NOT_CLASSIFIED = ('EV-038', 'EV-039')     # 범위 밖·모호: 분류·긴급도·담당팀 채점에서 뺀다 (dataset/README 채점 규칙)
GUIDED_NOTE = ('두 방식 모두 서버 추천 그룹과 비교. AI 는 담당팀을 내지 않고 서버가 정하며, 답변에서 안내하는 팀 이름도 '
               '서버가 추천 결과를 템플릿으로 넣는다 (docs/08 4.3·5.1) → "답변에서 안내한 팀" = 추천 그룹. 정답은 시나리오 팀'
               '(taxonomy team = 세부 유형 기본 그룹), EV-037·EV-040 만 따로 정한 값')
# 점수에는 그대로 세고 틀린 문항 목록에 이유를 붙인다 (평가셋·서버 규칙을 평가 한 건 때문에 바꾸지 않는다)
KNOWN_MISSES = {('EV-040', 'team'): '알려진 틀림(팀): 시나리오 없는 정책 안내라 서버 추천 그룹은 서비스데스크, 정답은 정보보안팀. '
                                    '이 비고는 추천 그룹 불일치만 설명한다 (다른 칸의 틀림은 따로)'}


# ── 문항 ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvalItem:
    eval_id: str
    query: str
    category: str | None           # '-' 는 None (채점에서 뺀다)
    scenario: str | None
    urgency: str | None
    action: str
    additional: str                # NONE · URGENT_HANDOFF · POLICY_GUIDANCE
    team: str | None
    team_scoring: str
    split: str                     # 기존 평가 40건 · 확장 평가 10건
    answer_docs: frozenset = frozenset()    # 시나리오의 가이드 (검색이 찾았는가 → 틀린 원인 나누기)
    answer_units: frozenset = frozenset()   # 그 시나리오 코드가 붙은 단위 (같은 본문 포함, 검색 평가와 같은 정의)


def load_items(path: str = EVAL_CSV, units=None) -> list[EvalItem]:
    """units: 청커 단위 (없으면 정리본을 청커로 나눈다). 정답 가이드·단위는 검색 평가 load_eval_set 과 같다."""
    qs = {q.qid: q for q in load_eval_set(path, units=units if units is not None else corpus_units())[0]}
    out = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            v = {k: (r[k].strip() if r[k].strip() not in ('', '-') else None) for k in r}
            out.append(EvalItem(r['eval_id'], r['query'].strip(), v['expected_category'], v['expected_scenario'],
                                v['expected_urgency'], r['expected_action'].strip(), r['additional_action'].strip(),
                                v['expected_team'], r['team_scoring'].strip(), r['dataset_split'].strip(),
                                *((frozenset(q.answer_docs), frozenset(q.answers)) if (q := qs.get(r['eval_id']))
                                  else ())))
    return out


# ── 기준 정보 (DB) ─────────────────────────────────────────────

@dataclass(frozen=True)
class Reference:
    taxonomy: object                 # app.agent.llm.Taxonomy
    type_group: dict[str, str]       # 세부 유형 → 기본 그룹 이름
    triage: str | None               # 서비스데스크 (is_triage)
    staff: tuple[str, ...]           # 직원 이름 (AI 에 보내기 전 치환)
    data: str = ''                   # 검색 대상 지문 (실행 시작 때 한 번). 현행 청크·벡터 입력 글·과거 사례 벡터. 벡터 값 자체는 보지 않는다


def read_reference(database_url: str) -> Reference:
    """FlowAiResponder.taxonomy() 와 같은 값 (활성 세부 유형만). 연결 오류에 주소가 섞이지 않게 감싼다."""
    import psycopg
    from app.agent.llm import CategoryInfo, Taxonomy, TypeInfo
    try:
        conn = psycopg.connect(database_url, connect_timeout=15)
    except psycopg.Error as ex:
        raise RuntimeError(f'DB 연결 실패 ({type(ex).__name__}, 주소는 출력하지 않음)') from None
    with conn:
        conn.read_only = True
        cats = conn.execute('select code, name, description from categories order by code').fetchall()
        types = conn.execute(
            'select t.code, t.category_code, t.name, t.request_kind, t.default_urgency, g.name from inquiry_types t '
            'left join support_groups g on g.id = t.default_group_id where t.is_active order by t.code').fetchall()
        triage = conn.execute('select name from support_groups where is_triage and is_active order by id limit 1').fetchone()
        staff = [n for (n,) in conn.execute('select distinct name from users')]
        # 가이드 검색 대상 = 활성 문서 현행·DONE 버전 (검색 API 와 같은 조건). 벡터는 입력 글(source_text)로 본다
        current = ('join document_versions v on v.id = c.version_id join knowledge_documents d on d.id = v.document_id '
                   "where d.is_active and v.is_current and v.ingest_status = 'DONE'")
        data = conn.execute(
            "select md5(string_agg(concat_ws('|', c.unit_key, d.title, c.heading_path, c.location, md5(c.content), "
            "c.meta::text, v.view_scope, v.transfer_policy), '#' order by c.unit_key, c.part)) from document_chunks c "
            + current).fetchone()[0] or ''
        vectors = conn.execute(
            "select e.model, count(*), md5(string_agg(c.unit_key || md5(coalesce(e.source_text, '')), '#' "
            'order by c.unit_key, c.part)) from document_chunk_embeddings e join document_chunks c on c.id = e.chunk_id '
            + current + ' group by 1 order by 1').fetchall()
        legacy = conn.execute(
            "select count(*), md5(string_agg(le.model || md5(coalesce(le.source_text, '')), '#' "
            'order by le.legacy_inquiry_id, le.model)) from legacy_inquiry_embeddings le').fetchone()
    return Reference(
        Taxonomy(tuple(CategoryInfo(c, n, d or '') for c, n, d in cats),
                 tuple(TypeInfo(c, cat, n, rk, du) for c, cat, n, rk, du, _ in types)),
        {c: g for c, *_, g in types}, triage[0] if triage else None, tuple(staff),
        f"가이드 {data[:12]} · 벡터 {', '.join(f'{m} {n}개 {h[:8]}' for m, n, h in vectors) or '없음'}"
        f" · 과거 사례 벡터 {legacy[0]}개{f' {legacy[1][:8]}' if legacy[1] else ''}")


def team_of(action: str, scenario: str | None, ref: Reference) -> str | None:
    """서버가 정하는 추천 그룹 (services/inquiry.py 의 recommended_group_id 와 같은 규칙)."""
    if action == 'OUT_OF_SCOPE' or scenario is None or scenario not in ref.type_group:
        return ref.triage
    return ref.type_group[scenario]


# ── 판단기 ─────────────────────────────────────────────────────

def oracle_reply(item: EvalItem, ref: Reference) -> Callable[[str, str], str]:
    """정답을 AI 출력 모양으로. 2차(검색 결과가 온 호출)의 ANSWER 는 정답 세부 유형이 붙은 결과(없으면 1위)를 근거로 든다."""
    kinds = {t.code: t.request_kind for t in ref.taxonomy.types}
    urgent = item.additional == 'URGENT_HANDOFF'

    def reply(system: str, user: str) -> str:
        docs = (json.loads(user).get('search') or {}).get('documents') or []
        cite = next((d for d in docs if item.scenario in d['inquiry_type_codes']), docs[0] if docs else None)
        evidence = ([{'kind': 'DOCUMENT', 'source_id': cite['unit_key'], 'quote': cite['text'][:40]}]
                    if item.action == 'ANSWER' and cite and cite['text'] else [])
        return json.dumps({
            'schema_version': '1.0', 'action': item.action, 'urgent_signal': urgent, 'title': item.query[:60],
            'category_code': item.category, 'inquiry_type_code': item.scenario,
            'request_kind': kinds.get(item.scenario), 'urgency_suggested': item.urgency,
            'facts': {'summary': item.query, 'target_system': None, 'symptom': None, 'occurred_at': None,
                      'impact_scope': None, 'work_stopped': 'unknown', 'has_workaround': None, 'time_constraint': None,
                      'business_impact': None, 'security_suspected': False, 'tried_actions': []},
            'rationale': {'category': '', 'urgency_reasons': [], 'action': '평가 정답'},
            'reply': '안내드립니다.', 'evidence': evidence,
            'missing_items': ['symptom'] if item.action == 'ASK_MORE' else [],
            'escalation_reason': ('긴급대응' if urgent else '전문판단') if item.action == 'ESCALATE' else None,
            'confidence': 1.0}, ensure_ascii=False)
    return reply


def make_port(judge: str, item: EvalItem, ref: Reference):
    """문항마다 새 포트 (Mock 은 받은 요청을 쌓으므로). claude 는 서버와 같은 어댑터 하나를 다시 쓴다."""
    from app.agent.llm import MockAdapter, get_llm_adapter
    if judge == 'claude':
        return get_llm_adapter()
    if judge == 'mock:oracle':
        return MockAdapter([oracle_reply(item, ref)])
    if judge == 'mock:safe':
        return MockAdapter()
    raise ValueError(judge)


class DbSearch:
    """판단 흐름에 넘길 search_fn. 실제 search() 를 읽기 전용 트랜잭션에서 부르고, 마지막 결과를 남긴다."""

    def __init__(self, database_url: str, embedder):
        from sqlalchemy import create_engine
        self.engine = create_engine(database_url.replace('postgresql://', 'postgresql+psycopg://', 1), pool_pre_ping=True)
        self.emb, self.last = embedder, None

    def __call__(self, request):
        from sqlalchemy import exc, text
        from sqlalchemy.orm import Session
        from ..search.service import search
        try:
            with Session(self.engine) as s:
                s.execute(text('set transaction read only'))
                self.last = search(s, request, self.emb)
                s.rollback()
        except exc.OperationalError as ex:
            raise RuntimeError(f'DB 연결 실패 ({type(ex.orig).__name__}, 주소는 출력하지 않음)') from None
        return self.last

    def close(self):
        self.engine.dispose()


# ── 실행 ───────────────────────────────────────────────────────

@dataclass
class Judged:
    item: EvalItem
    round: int
    predicted: dict                      # FIELDS → 값 (확정값, 보정 후)
    urgent: bool = False
    next_step: str = ''
    failure: str | None = None
    error_code: str | None = None
    searched: bool = False
    found_doc: bool | None = None        # 검색 결과에 정답 가이드가 있었나 (검색 안 했거나 정답 가이드가 없으면 None)
    found_unit: bool | None = None       # 정답 단위가 있었나. 같은 본문이라 묶인 결과(also_in)도 센다
    top_units: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)
    calls: int = 0
    tokens: tuple[int, int] = (0, 0)


def judge_item(item: EvalItem, judge: str, ref: Reference, search: DbSearch, round_: int = 1) -> Judged:
    from app.agent.flow import run_flow
    from app.agent.llm import AIInput, UserContext
    inp = AIInput(session_id=f'eval-{item.eval_id}-{round_}', inquiry_id=item.eval_id, message=item.query, history=[],
                  ask_more_count=0, user_context=UserContext(employee_no='EVAL', service_role='EMPLOYEE'), search=None)
    search.last = None
    r = run_flow(inp, make_port(judge, item, ref), ref.taxonomy, ref.staff, search)
    out, found = r.output, search.last
    # 검색 평가 Hit.refs·docs 와 같이 대표 결과와 묶인 결과(also_in)를 함께 본다
    refs = {unit_ref(k) for d in found.documents for k in (d.unit_key, *d.also_in)} if found else set()
    docs = {x.split('/', 1)[0] for x in refs}
    return Judged(
        item, round_,
        {'category': out.category_code, 'scenario': out.inquiry_type_code, 'urgency': r.urgency,
         'action': out.action, 'team': team_of(out.action, out.inquiry_type_code, ref)},
        out.urgent_signal, r.next_step, r.failure, r.error_code, found is not None,
        bool(docs & item.answer_docs) if found is not None and item.answer_docs else None,
        bool(refs & item.answer_units) if found is not None and item.answer_units else None,
        [d.unit_key for d in found.documents[:3]] if found else [], [e.source_id for e in out.evidence],
        [o['rule'] for o in r.override_reasons], len(r.llm_calls),
        (sum(c.input_tokens or 0 for c in r.llm_calls), sum(c.output_tokens or 0 for c in r.llm_calls)))


def run(judge: str, items: list[EvalItem], ref: Reference, search: DbSearch, repeat: int = 1,
        progress: Callable[[str], None] | None = None) -> tuple[list[Judged], str | None]:
    """(끝낸 문항들, 멈춘 이유). 검색·DB 오류나 Ctrl+C 로 멈춰도 그때까지 결과는 돌려준다 (유료 호출을 버리지 않게).
    LLM 오류는 run_flow 가 안전 기본값으로 처리하므로 여기까지 오지 않는다. 이유에는 오류 종류만 (원문·주소 없음)."""
    out = []
    for n in range(1, repeat + 1):
        for i, item in enumerate(items, 1):
            try:
                out.append(judge_item(item, judge, ref, search, n))
                if progress:
                    progress(f'{n}회 {i}/{len(items)} {item.eval_id}')
            except (Exception, KeyboardInterrupt) as ex:
                return out, f'{n}회 {item.eval_id} 에서 멈춤 ({type(ex).__name__})'
    return out, None


# ── 채점 ───────────────────────────────────────────────────────

def expected(item: EvalItem, f: str) -> str | None:
    """채점할 정답. None 이면 이 칸은 채점에서 뺀다 (정답 '-' · 팀 평가 제외 · 범위 밖·모호 문항의 분류·긴급도·팀)."""
    if item.eval_id in NOT_CLASSIFIED and f != 'action':
        return None
    if f == 'team':
        return item.team if item.team_scoring in (TEAM_ASSIGNED, TEAM_GUIDED) else None
    return getattr(item, f)


def is_correct(j: Judged, f: str) -> bool | None:
    want = expected(j.item, f)
    return None if want is None else j.predicted[f] == want


def cause(j: Judged) -> str:
    """틀린 문항의 원인 쪽 (조사 후보). 정답 항목(같은 본문 포함)을 찾았으면 '판단' (D, M4-4-1).
    못 찾았으면 정답 가이드도 못 찾음 → '검색: 가이드', 가이드는 찾음 → '검색: 항목' (C, M3-4-1).
    정답 항목이 정의되지 않은 문항은 가이드 적중만 보고, 검색을 안 했으면 '판단'."""
    if all(is_correct(j, f) is not False for f in FIELDS):
        return ''
    if j.found_unit is True:
        return '판단'
    if j.found_doc is False:
        return '검색: 가이드'
    return '검색: 항목' if j.found_unit is False else '판단'


def rate(js: list[Judged], f: str) -> dict:
    marks = [m for j in js if (m := is_correct(j, f)) is not None]
    return {'n': len(marks), 'acc': sum(marks) / len(marks) if marks else None}


def near_urgency(js: list[Judged]) -> dict:
    """긴급도 ±1 (참고)."""
    scored = [j for j in js if expected(j.item, 'urgency')]
    pairs = [(j.item.urgency, j.predicted['urgency']) for j in scored if j.predicted['urgency']]
    n = len(scored)
    ok = sum(1 for a, b in pairs if abs(URGENCY_ORDER.index(a) - URGENCY_ORDER.index(b)) <= 1)
    return {'n': n, 'acc': ok / n if n else None}


def score(js: list[Judged]) -> dict:
    """{묶음: {칸: {n, acc}}}. 묶음 = 전체 · 기존 40 · 확장 10. 반복하면 회차별로 낸 뒤 범위를 따로 적는다."""
    groups: dict[str, list[Judged]] = defaultdict(list)
    for j in js:
        groups['전체'].append(j)
        groups[j.item.split].append(j)
    out = {}
    for g, rs in groups.items():
        d = {f: rate(rs, f) for f in FIELDS}
        d['긴급도 ±1'] = near_urgency(rs)
        d[f'팀 ({TEAM_ASSIGNED})'] = rate([j for j in rs if j.item.team_scoring == TEAM_ASSIGNED], 'team')
        d[GUIDED_COL] = rate([j for j in rs if j.item.team_scoring == TEAM_GUIDED], 'team')
        out[g] = d
    return out


def confusion(js: list[Judged]) -> dict[str, dict[str, int]]:
    """처리 방향 혼동표 {정답: {예측: 수}}."""
    c: dict[str, Counter] = defaultdict(Counter)
    for j in js:
        c[j.item.action][j.predicted['action']] += 1
    return {k: dict(v) for k, v in sorted(c.items())}


def by_round(js: list[Judged]) -> dict[int, list[Judged]]:
    rounds: dict[int, list[Judged]] = defaultdict(list)
    for j in js:
        rounds[j.round].append(j)
    return dict(sorted(rounds.items()))


# ── 기록 ───────────────────────────────────────────────────────

def prompt_fingerprint(ref: Reference) -> str:
    from app.agent.llm import build_system_prompt
    return hashlib.sha1(build_system_prompt(ref.taxonomy).encode('utf-8')).hexdigest()[:12]


def flow_fingerprint() -> str:
    """판단에 영향을 주는 코드(판단 흐름·호출부·정보 보호·검색·이 파일)의 지문."""
    import glob
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
    files = [os.path.abspath(__file__)]
    for sub in ('agent/flow', 'agent/llm', 'agent/sensitive', 'rag/search'):
        files += glob.glob(os.path.join(app, *sub.split('/'), '*.py'))
    return file_hash(files)


def write(out_dir: str, js: list[Judged], meta: dict) -> dict:
    with open(os.path.join(out_dir, '문항별.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['회차', '문항', '묶음', '문의'] + [f'{NAMES[x]} {s}' for x in FIELDS for s in ('정답', '예측', '맞음')] +
                   ['팀 채점', '추가 처리', '긴급 징후', '다음 단계', '실패', '실패 사유', '검색함', '정답 가이드 찾음',
                    '정답 항목 찾음', '검색 상위 3', '근거', '보정 규칙', '호출 수', '틀린 원인', '비고'])
        yn = {True: 'Y', False: 'N', None: ''}
        for j in js:
            it = j.item
            cells = []
            for x in FIELDS:
                m = is_correct(j, x)
                cells += [expected(it, x) or '-', j.predicted[x] or '', '' if m is None else ('O' if m else 'X')]
            w.writerow([j.round, it.eval_id, it.split, it.query] + cells +
                       [it.team_scoring, it.additional, 'Y' if j.urgent else '', j.next_step, j.failure or '',
                        j.error_code or '', 'Y' if j.searched else '', yn[j.found_doc], yn[j.found_unit],
                        '; '.join(j.top_units), '; '.join(j.evidence), '; '.join(j.overrides), j.calls, cause(j),
                        known_note(j)])
    rounds = by_round(js)
    # 혼동표·추가 처리·틀린 문항은 모든 회차 (반복하면 한 번이라도 틀린 문항이 빠지지 않게)
    summary = {'meta': meta, '점수': {n: score(rs) for n, rs in rounds.items()},
               '처리 방향 혼동표': confusion(js),
               '추가 처리': [{'회차': j.round, '문항': j.item.eval_id, '정답': j.item.additional, '긴급 징후': j.urgent,
                          '처리 방향': j.predicted['action']} for j in js if j.item.additional != 'NONE'],
               '틀린 문항': [{'회차': j.round, '문항': j.item.eval_id, '원인': cause(j),
                          '틀린 칸': [NAMES[x] for x in FIELDS if is_correct(j, x) is False], '비고': known_note(j)}
                         for j in js if cause(j)]}
    with open(os.path.join(out_dir, '요약.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, '요약.md'), 'w', encoding='utf-8') as f:
        f.write(summary_md(summary))
    return summary


def known_note(j: Judged) -> str:
    return '; '.join(note for (eid, f), note in KNOWN_MISSES.items() if eid == j.item.eval_id and is_correct(j, f) is False)


def _pct(d: dict) -> str:
    return '—' if d['acc'] is None else f"{d['acc']:.0%} ({d['n']})"


def summary_md(summary: dict) -> str:
    m = summary['meta']
    out = [f"# 판단 평가 — {m['판단기']}", '', '| 항목 | 값 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in m.items()]
    rounds = summary['점수']
    if not rounds:
        return '\n'.join(out + ['', '끝낸 문항이 없습니다.']) + '\n'
    cols = [*FIELDS, '긴급도 ±1', f'팀 ({TEAM_ASSIGNED})', GUIDED_COL]
    head = [NAMES.get(c, c) for c in cols]
    for n, sc in rounds.items():
        out += ['', f'## 정확도 ({n}회차, 괄호는 채점한 문항 수)', '', '| 묶음 | ' + ' | '.join(head) + ' |',
                '|---|' + '---|' * len(cols)]
        out += [f'| {g} | ' + ' | '.join(_pct(d[c]) for c in cols) + ' |' for g, d in sc.items()]
    # 범위는 끝까지 돈 회차만 (중간에 멈춘 회차는 문항이 적어 같은 시험지가 아니다). 처리 방향 n = 그 회차 문항 수
    full = max(r['전체']['action']['n'] for r in rounds.values())
    done = [r for r in rounds.values() if r['전체']['action']['n'] == full]
    if len(done) > 1:
        out += ['', f'## 반복 {len(done)}회 범위 (전체, 끝까지 돈 회차만)', '', '| 칸 | 최소 | 최대 |', '|---|---|---|']
        for c in cols:
            accs = [r['전체'][c]['acc'] for r in done if r['전체'][c]['acc'] is not None]
            if accs:
                out.append(f'| {NAMES.get(c, c)} | {min(accs):.0%} | {max(accs):.0%} |')
    acts = sorted({a for row in summary['처리 방향 혼동표'].values() for a in row} | set(summary['처리 방향 혼동표']))
    out += ['', f'## 처리 방향 혼동표 (행 = 정답, 열 = 예측, {len(rounds)}회 합)', '',
            '| 정답 \\ 예측 | ' + ' | '.join(acts) + ' |', '|---|' + '---|' * len(acts)]
    out += [f'| {a} | ' + ' | '.join(str(row.get(b, '')) for b in acts) + ' |'
            for a, row in summary['처리 방향 혼동표'].items()]
    out += ['', '## 추가 처리 (2건뿐이라 목록으로)', ''] + \
        [f"- {x['회차']}회 {x['문항']} {x['정답']}: 긴급 징후 {'있음' if x['긴급 징후'] else '없음'}, 처리 방향 {x['처리 방향']}"
         for x in summary['추가 처리']]
    wrong = summary['틀린 문항']
    out += ['', f'## 틀린 문항 {len(wrong)}개 (모든 회차. 원인은 조사 후보: 검색 → C, 판단 → D)', '',
            '| 회차 | 문항 | 원인 | 틀린 칸 | 비고 |', '|---|---|---|---|---|'] + \
        [f"| {x['회차']} | {x['문항']} | {x['원인']} | {', '.join(x['틀린 칸'])} | {x['비고']} |" for x in wrong]
    return '\n'.join(out) + '\n'


def describe(judge: str, ref: Reference, args) -> dict:
    port = None
    if judge == 'claude':
        from app.agent.llm import get_llm_adapter
        port = get_llm_adapter()
    return {'판단기': judge, '모델': port.model if port else 'mock', '실행': args.stamp, 'git': git_state(),
            '판단 코드 지문': flow_fingerprint(), '프롬프트 지문': prompt_fingerprint(ref),
            '평가셋 파일': file_hash([EVAL_CSV, TAXONOMY]), '검색 대상 지문': ref.data, '문항': args.n_items,
            '반복': args.repeat, '사용자 역할': 'EMPLOYEE', '팀 채점': GUIDED_NOTE}


def positive(text: str) -> int:
    import argparse
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError('1 이상')
    return n


def main(argv=None) -> int:
    import argparse
    import logging
    import sys
    from datetime import datetime
    ap = argparse.ArgumentParser(prog='python -m app.rag.evaluation.judgment')
    ap.add_argument('--judge', default='mock:oracle', choices=JUDGES)
    ap.add_argument('--database-url', required=True, help='검색·분류 체계를 읽을 DB (읽기 전용). 로컬 DB 를 쓴다')
    ap.add_argument('--model', default='bge-m3', help='검색 임베딩 모델')
    ap.add_argument('--limit', type=positive, help='앞에서 몇 문항만 (실제 호출 전에 적게 돌려 볼 때)')
    ap.add_argument('--ids', help='쉼표로 문항 id (예: EV-001,EV-040)')
    ap.add_argument('--repeat', type=positive, default=1, help='같은 문항을 몇 번 (LLM 결과가 매번 다를 수 있어 범위를 본다)')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    items = load_items()
    if a.ids:                                          # DB·모델을 열기 전에 고른 문항을 확인한다
        want = {x.strip() for x in a.ids.split(',') if x.strip()}
        if not want:
            print('--ids 에 문항이 없습니다')
            return 2
        if unknown := want - {i.eval_id for i in items}:
            print(f'평가셋에 없는 문항: {", ".join(sorted(unknown))}')
            return 2
        items = [i for i in items if i.eval_id in want]
    items = items[:a.limit] if a.limit else items
    ref = read_reference(a.database_url)
    a.stamp, a.n_items = datetime.now().strftime('%Y%m%d_%H%M%S'), len(items)
    try:
        meta = describe(a.judge, ref, a)               # claude 는 여기서 키를 확인한다 (모델을 열기 전에 멈춘다)
    except RuntimeError as ex:
        print(ex)
        return 2
    from ..embedding import Embedder
    emb = Embedder(a.model)
    meta['검색 모델'] = emb.model_id
    search = DbSearch(a.database_url, emb)
    if a.judge == 'claude':
        print(f'실제 Claude 호출: 문항 {len(items)} × 반복 {a.repeat} × 기본 1~2회 (모델 {meta["모델"]})')
    js, stopped = run(a.judge, items, ref, search, a.repeat, progress=lambda s: print(f'  {s}', end='\r'))
    try:
        search.close()
    except Exception:                                  # 정리 실패가 결과 기록을 가리지 않게
        pass
    calls, tin, tout = sum(j.calls for j in js), sum(j.tokens[0] for j in js), sum(j.tokens[1] for j in js)
    meta |= {'끝낸 문항': f'{len(js)} / {len(items) * a.repeat}', '중단': stopped or '없음', '호출': calls,
             '토큰 (입력/출력)': f'{tin}/{tout}', '실패': dict(Counter(j.error_code for j in js if j.failure)) or '없음'}
    out_dir = new_run_dir(a.out, f"{a.stamp}_판단_{a.judge.replace(':', '-')}")
    summary = write(out_dir, js, meta)
    print(summary_md(summary))
    print(f'→ {out_dir}')
    if stopped:
        print(f'[중단] {stopped}. 끝낸 문항까지만 기록했습니다.')
    return 1 if stopped else 0


if __name__ == '__main__':
    raise SystemExit(main())
