"""판단 평가 (WBS M2-4-1). 평가셋 문의를 실제 판단 흐름(M4-2-1 run_flow)에 넣고 분류·세부 유형·긴급도·처리 방향·팀을 채점한다.

    uv run python -m app.rag.evaluation.judgment --judge mock:oracle --database-url <로컬 DB>   # 키 없이 끝까지 (도구 확인)
    uv run python -m app.rag.evaluation.judgment --judge mock:safe --database-url <로컬 DB>     # 안전 기본값만 (바닥 점수)
    uv run python -m app.rag.evaluation.judgment --judge claude --database-url <로컬 DB> --limit 3   # 실제 Claude (LLM_API_KEY)
    uv run python -m app.rag.evaluation.judgment --judge claude --database-url <로컬 DB> --set guide # 질문시트 (참고)

시험지 (--set)
- eval  : 평가셋 50 (기본, 공식 점수)
- guide : 가이드 검색 질문(질문시트) 중 직원이 볼 수 있는 문서가 정답인 질문. 정답은 정답 항목에서 끌어낸 참고값
          (분류·세부 유형·팀만, 긴급도·처리 방향 없음). 평가셋 '전체' 점수와 섞지 않고 '질문시트' 묶음으로 따로 낸다
- extra : 보조 시험지 (dataset/eval_extra/extra_inquiries.csv). 평가셋이 거의 다루지 않는 문의(정보 부족·범위 밖·가이드 없음·
          없는 시스템·사칭·민감정보·긴급도 함정·지시 끼워 넣기)를 Claude·Codex 가 나눠 쓰고 서로 정답을 확인한 참고 시험지.
          정답은 사람이 정한 값이지만 공식 평가셋이 아니므로 '보조 전체'·종류별·작성자별 묶음으로 따로 낸다
- all   : 셋 다 한 번에

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
from . import (EVAL_CSV, OUT, QUESTIONS_DIR, REPO, TAXONOMY, corpus_units, file_hash, git_state, load_eval_set,
               load_guide_questions, new_run_dir, restrict_to_role, units_fingerprint)

FIELDS = ('category', 'scenario', 'urgency', 'action', 'team')
NAMES = {'category': '분류', 'scenario': '세부 유형', 'urgency': '긴급도', 'action': '처리 방향', 'team': '팀'}
CITED = '근거 일치'                         # ANSWER 의 문서 근거가 정답 항목인가 (참고, 판단 칸 아님)
SETS = {'eval': ('eval',), 'guide': ('guide',), 'extra': ('extra',), 'all': ('eval', 'guide', 'extra')}
GUIDE_GROUP = '질문시트'                    # 가이드 검색 질문 (정답 칸은 정답 항목에서 끌어낸 참고값)
EXTRA_CSV = os.path.join(REPO, 'dataset', 'eval_extra', 'extra_inquiries.csv')
EXTRA_GROUP = '보조 전체'                   # 보조 시험지 (평가셋 '전체'와 섞지 않는다)
CONFUSION = {'eval': '처리 방향 혼동표', 'extra': '처리 방향 혼동표 (보조)'}   # 시험지마다 따로 (질문시트는 정답 없음)
EVIDENCE_RULES = {'NO_EVIDENCE', 'GUIDE_INSUFFICIENT'}   # 흐름이 근거 부족으로 ANSWER 를 바꾸는 보정 규칙
URGENCY_ORDER = ('P1', 'P2', 'P3', 'P4')
TEAM_ASSIGNED, TEAM_GUIDED, TEAM_SKIP = '배정팀 비교', '안내 지원팀 비교', '팀 평가 제외'
GUIDED_COL = f'팀 ({TEAM_GUIDED})'
# 1차 판단이 가이드 상황만 되묻는 것 (M4-3-1, 11.05 흐름 변경). 평가는 첫 글 하나만 넣으므로 그 뒤 방향을 모른다.
# 정답이 ASK_MORE 가 아닌데 상황만 되물었으면 '틀림'과 따로 센다: 엄격 점수(처리 방향)는 그대로 두고 아래 두 칸을 더 낸다
SITUATION_ACTION = '처리 방향 (상황 되묻기 제외)'
SITUATION_ASKS = '상황 되묻기'
JUDGES = ('claude', 'mock:oracle', 'mock:safe')
NOT_CLASSIFIED = ('EV-038', 'EV-039')     # 범위 밖·모호: 분류·긴급도·담당팀 채점에서 뺀다 (dataset/README 채점 규칙)
GUIDED_NOTE = ('두 방식 모두 서버 추천 그룹과 비교. docs/08 설계상(4.3·5.1) AI 는 담당팀을 내지 않고, 최종 답변의 팀 이름도 '
               '서버가 추천 결과를 템플릿으로 넣는다 → "답변에서 안내한 팀" = 추천 그룹. 현재 서버는 그 템플릿과 예외 규칙'
               '(routing_rules)이 없어 추천 그룹 산출값만 검증하며, 답변 표시 통합은 별도. 정답은 시나리오 팀'
               '(taxonomy team = 세부 유형 기본 그룹), EV-037·EV-040 만 따로 정한 값')
# 점수에는 그대로 세고 틀린 문항 목록에 이유를 붙인다 (평가셋·서버 규칙을 평가 한 건 때문에 바꾸지 않는다)
KNOWN_MISSES = {('EV-040', 'team'): '알려진 틀림(팀): 분류 SEC 는 있지만 세부 유형이 없어 서버 규칙(세부 유형의 기본 그룹, '
                                    '없으면 서비스데스크)으로는 서비스데스크. 평가셋 정답은 분류의 담당 팀인 정보보안팀. '
                                    '정답·서버 규칙은 바꾸지 않기로 함 (11.02). 이 비고는 팀만 설명한다 (다른 칸의 틀림은 따로)'}


# ── 문항 ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvalItem:
    eval_id: str
    query: str
    category: str | None           # '-' 는 None (채점에서 뺀다)
    scenario: str | None
    urgency: str | None
    action: str | None             # 질문시트는 정답이 없어 None
    additional: str                # NONE · URGENT_HANDOFF · POLICY_GUIDANCE
    team: str | None
    team_scoring: str
    split: str                     # 기존 평가 40건 · 확장 평가 10건 · 질문시트 · 보조: <종류>
    answer_docs: frozenset = frozenset()    # 시나리오의 가이드 (검색이 찾았는가 → 틀린 원인 나누기)
    answer_units: frozenset = frozenset()   # 그 시나리오 코드가 붙은 단위 (같은 본문 포함, 검색 평가와 같은 정의)
    set: str = 'eval'              # eval (평가셋) · guide (질문시트) · extra (보조 시험지)
    author: str = ''               # 보조 시험지 작성자 (Claude · Codex)


def load_items(path: str = EVAL_CSV, units=None, set_: str = 'eval') -> list[EvalItem]:
    """평가셋 모양의 CSV → 문항. units: 청커 단위 (없으면 정리본을 청커로 나눈다).
    정답 가이드·단위는 검색 평가 load_eval_set 과 같다. 보조 시험지(set_='extra')는 같은 칸에 author 가 더 있고,
    처리 방향도 '-' 면 채점에서 뺀다 (평가셋은 처리 방향이 모두 있다)."""
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for r in rows:                                   # 칸이 헤더보다 많거나 적은 줄 (따옴표 없는 쉼표 등). 정답 가이드를 읽기 전에
        if None in r or None in r.values():
            raise ValueError(f'{r.get("eval_id") or "?"} 줄의 칸 수가 헤더와 다름')
    qs = {q.qid: q for q in load_eval_set(path, units=units if units is not None else corpus_units())[0]}
    out = []
    for r in rows:
        v = {k: (r[k].strip() if r[k].strip() not in ('', '-') else None) for k in r}
        out.append(EvalItem(r['eval_id'], r['query'].strip(), v['expected_category'], v['expected_scenario'],
                            v['expected_urgency'], v['expected_action'], r['additional_action'].strip() or 'NONE',
                            v['expected_team'], r['team_scoring'].strip(), r['dataset_split'].strip(),
                            *((frozenset(q.answer_docs), frozenset(q.answers)) if (q := qs.get(r['eval_id']))
                              else (frozenset(), frozenset())),
                            set_, (r.get('author') or '').strip()))
    return out


def load_extra_items(path: str = EXTRA_CSV, units=None, taxonomy: str = TAXONOMY) -> list[EvalItem]:
    """보조 시험지. 정답 칸이 분류 체계와 맞지 않으면 ValueError (유료 실행 전에 라벨 실수를 잡는다)."""
    items = load_items(path, units, 'extra')
    problems = check_extra(items, taxonomy)
    if problems:
        raise ValueError('보조 시험지 정답 칸 오류: ' + '; '.join(problems))
    return items


ACTIONS = ('ANSWER', 'ASK_MORE', 'ESCALATE', 'OUT_OF_SCOPE')
ADDITIONAL = ('NONE', 'URGENT_HANDOFF', 'POLICY_GUIDANCE')


def check_extra(items: list[EvalItem], taxonomy: str = TAXONOMY) -> list[str]:
    """보조 시험지 정답 칸 검사. 문항 번호는 EX- (평가셋 EV- 와 섞이면 --ids·정답 목록이 섞인다), 코드는 분류 체계 안,
    세부 유형이 있으면 분류는 그 앞부분이고 팀은 그 유형의 팀 (서버 규칙). 세부 유형 없이 팀만 있는 것은 허용한다
    (예: 정보보안 세부 유형 중 무엇이든 정보보안팀)."""
    with open(taxonomy, encoding='utf-8') as f:
        t = json.load(f)
    cats = set(t['categories'])
    teams = set(t['teams'])
    team = {s['id']: s['team'] for s in t['scenarios']}
    out = []
    for k, n in Counter(i.eval_id for i in items).items():
        if n > 1:
            out.append(f'{k} 번호 겹침')
    for i in items:
        bad = []
        if not i.eval_id.startswith('EX-'):
            bad.append('번호는 EX- 로 시작')
        if not i.query:
            bad.append('문의 글 없음')
        if i.category and i.category not in cats:
            bad.append(f'없는 분류 {i.category}')
        if i.scenario and i.scenario not in team:
            bad.append(f'없는 세부 유형 {i.scenario}')
        if i.scenario and i.category and i.scenario.split('-', 1)[0] != i.category:
            bad.append(f'분류 {i.category} 와 세부 유형 {i.scenario} 가 다름')
        if i.urgency and i.urgency not in URGENCY_ORDER:
            bad.append(f'긴급도 {i.urgency}')
        if i.action and i.action not in ACTIONS:
            bad.append(f'처리 방향 {i.action}')
        if i.additional not in ADDITIONAL:
            bad.append(f'추가 처리 {i.additional}')
        elif i.additional == 'URGENT_HANDOFF' and i.action and i.action != 'ESCALATE':
            bad.append(f'긴급 인계인데 처리 방향 {i.action} (긴급 징후는 ESCALATE)')
        if i.team and i.team not in teams:
            bad.append(f'없는 팀 {i.team}')
        if i.team_scoring not in (TEAM_ASSIGNED, TEAM_GUIDED, TEAM_SKIP):
            bad.append(f'팀 채점 {i.team_scoring}')
        elif i.team_scoring != TEAM_SKIP and not i.team:
            bad.append('팀 채점인데 팀 없음')
        if i.scenario in team and i.team and i.team != team[i.scenario]:
            bad.append(f'팀 {i.team} ≠ {i.scenario} 의 팀 {team[i.scenario]}')
        if not i.split.startswith('보조: '):
            bad.append(f'종류(dataset_split) {i.split!r} 는 "보조: " 로 시작')
        if not i.author:
            bad.append('작성자(author) 없음')
        out += [f'{i.eval_id} {b}' for b in bad]
    return out


def load_guide_items(path: str = QUESTIONS_DIR, taxonomy: str = TAXONOMY, units=None) -> list[EvalItem]:
    """가이드 검색 질문(질문시트) → 문항. 공식 평가셋이 아니라 판단을 더 많은 질문으로 보는 참고 시험지.

    정답은 사람이 단 값이 아니라 정답 항목에서 끌어낸다: 세부 유형 = 정답 항목(같은 본문 포함)의 문의 유형 코드가
    하나일 때 그 코드, 분류 = 그 코드의 분류, 팀 = taxonomy 의 그 유형 팀. 코드가 없거나 둘 이상이면 세 칸 모두 뺀다.
    긴급도·처리 방향은 정답이 없어 채점하지 않는다. 직원이 볼 수 없는 문서(매뉴얼)만 정답인 질문은 뺀다
    (판단 흐름의 사용자가 직원이므로, 검색 평가 --role EMPLOYEE 와 같다)."""
    units = units if units is not None else corpus_units()
    codes = {u.ref: u.codes for u in units}
    with open(taxonomy, encoding='utf-8') as f:
        team = {s['id']: s['team'] for s in json.load(f)['scenarios']}
    qs, _ = restrict_to_role(load_guide_questions(units, path), units, 'EMPLOYEE')
    out = []
    for q in qs:
        found = set().union(*(codes.get(a, frozenset()) for a in q.answers)) if q.answers else set()
        scen = next(iter(found)) if len(found) == 1 else None
        out.append(EvalItem(q.qid, q.text, scen.split('-', 1)[0] if scen else None, scen, None, None, 'NONE',
                            team.get(scen) if scen else None, TEAM_GUIDED, GUIDE_GROUP,
                            frozenset(q.answer_docs), frozenset(q.answers), 'guide'))
    return out


# ── 기준 정보 (DB) ─────────────────────────────────────────────

@dataclass(frozen=True)
class Reference:
    taxonomy: object                 # app.agent.llm.Taxonomy
    type_group: dict[str, str]       # 세부 유형 → 기본 그룹 이름
    triage: str | None               # 서비스데스크 (is_triage)
    staff: tuple[str, ...]           # 직원 이름 (AI 에 보내기 전 치환)
    data: str = ''                   # 검색 후보 자료의 부분 지문 (실행 시작 때 한 번). 현행 청크·벡터 입력 글·과거 사례 벡터.
                                     # 벡터 값, 역할별 열람 범위, 과거 사례의 열람·전송 정책 변화는 구분하지 못한다


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
            "c.meta::text, v.view_scope, coalesce(c.content_transfer_policy, v.transfer_policy)), '#' "
            "order by c.unit_key, c.part)) from document_chunks c "
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

def oracle_reply(item: EvalItem, ref: Reference, found: Callable[[], object] = lambda: None) -> Callable[[str, str], str]:
    """정답을 AI 출력 모양으로. 2차(검색 결과가 온 호출)의 ANSWER 는 정답 세부 유형이 붙은 결과(없으면 1위)를 근거로 든다.
    질문시트는 처리 방향·긴급도 정답이 없어 ANSWER · 유형 기본 긴급도로 두고, 정답 항목인 결과를 근거로 든다.
    found: 원래 검색 결과 (DbSearch.last). AI 입력에는 묶인 결과(also_in)가 없으므로, 정답이 묶인 대표 결과는
    여기서 고른다 (평가 정답을 실제 Claude 입력에 넣지 않는다)."""
    kinds = {t.code: t.request_kind for t in ref.taxonomy.types}
    default_urgency = {t.code: t.default_urgency for t in ref.taxonomy.types}
    urgent = item.additional == 'URGENT_HANDOFF'
    action = item.action or 'ANSWER'

    def ok(d, answers: set[str]) -> bool:
        return d['unit_key'] in answers if item.set == 'guide' else item.scenario in d['inquiry_type_codes']

    def reply(system: str, user: str) -> str:
        res = found()
        answers = {x.unit_key for x in res.documents
                   if {unit_ref(k) for k in (x.unit_key, *x.also_in)} & item.answer_units} if res else set()
        docs = (json.loads(user).get('search') or {}).get('documents') or []
        cite = next((d for d in docs if ok(d, answers)), docs[0] if docs else None)
        evidence = ([{'kind': 'DOCUMENT', 'source_id': cite['unit_key'], 'quote': cite['text'][:40]}]
                    if action == 'ANSWER' and cite and cite['text'] else [])
        return json.dumps({
            'schema_version': '1.0', 'action': action, 'urgent_signal': urgent, 'title': item.query[:60],
            'category_code': item.category, 'inquiry_type_code': item.scenario,
            'request_kind': kinds.get(item.scenario),
            'urgency_suggested': item.urgency or default_urgency.get(item.scenario) or 'P3',
            'facts': {'summary': item.query, 'target_system': None, 'symptom': None, 'occurred_at': None,
                      'impact_scope': None, 'work_stopped': 'unknown', 'has_workaround': None, 'time_constraint': None,
                      'business_impact': None, 'security_suspected': False, 'tried_actions': []},
            'rationale': {'category': '', 'urgency_reasons': [], 'action': '평가 정답'},
            'reply': '안내드립니다.', 'evidence': evidence,
            'missing_items': ['symptom'] if action == 'ASK_MORE' else [],
            'escalation_reason': ('긴급대응' if urgent else '전문판단') if action == 'ESCALATE' else None,
            'confidence': 1.0}, ensure_ascii=False)
    return reply


def make_port(judge: str, item: EvalItem, ref: Reference, search=None):
    """문항마다 새 포트 (Mock 은 받은 요청을 쌓으므로). claude 는 서버와 같은 어댑터 하나를 다시 쓴다."""
    from app.agent.llm import MockAdapter, get_llm_adapter
    if judge == 'claude':
        return get_llm_adapter()
    if judge == 'mock:oracle':
        return MockAdapter([oracle_reply(item, ref, (lambda: search.last) if search else (lambda: None))])
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
    cited_unit: bool | None = None       # ANSWER 의 문서 근거에 정답 항목이 있나 (묶인 결과 포함). ANSWER·근거가 아니면 None
    overrides: list[str] = field(default_factory=list)
    calls: int = 0
    tokens: tuple[int, int] = (0, 0)
    missing: tuple[str, ...] = ()       # AI 가 되물은 항목 (missing_items, 보정 후)


def judge_item(item: EvalItem, judge: str, ref: Reference, search: DbSearch, round_: int = 1) -> Judged:
    from app.agent.flow import run_flow
    from app.agent.llm import AIInput, UserContext
    from app.agent.sensitive import mask_secrets
    # 서버는 사용자 글을 비밀번호·인증번호를 가려 저장한 뒤 그 글을 판단 흐름에 넘긴다 (InquiryService.add_user_message
    # → AiResponder). 평가도 같은 글을 넣는다. 연락처·사번·이름 치환은 판단 흐름 안(호출부)에서 서버와 같이 일어난다
    message = mask_secrets(item.query).text
    inp = AIInput(session_id=f'eval-{item.eval_id}-{round_}', inquiry_id=item.eval_id, message=message, history=[],
                  ask_more_count=0, user_context=UserContext(employee_no='EVAL', service_role='EMPLOYEE'), search=None)
    search.last = None
    r = run_flow(inp, make_port(judge, item, ref, search), ref.taxonomy, ref.staff, search)
    out, found = r.output, search.last
    # 검색 평가 Hit.refs·docs 와 같이 대표 결과와 묶인 결과(also_in)를 함께 본다
    refs = {unit_ref(k) for d in found.documents for k in (d.unit_key, *d.also_in)} if found else set()
    docs = {x.split('/', 1)[0] for x in refs}
    group = {d.unit_key: {unit_ref(k) for k in (d.unit_key, *d.also_in)} for d in found.documents} if found else {}
    cited = [group.get(e.source_id, {unit_ref(e.source_id)}) for e in out.evidence if e.kind == 'DOCUMENT']
    cited_unit = (any(c & item.answer_units for c in cited)
                  if out.action == 'ANSWER' and cited and item.answer_units else None)
    return Judged(
        item, round_,
        {'category': out.category_code, 'scenario': out.inquiry_type_code, 'urgency': r.urgency,
         'action': out.action, 'team': team_of(out.action, out.inquiry_type_code, ref)},
        out.urgent_signal, r.next_step, r.failure, r.error_code, found is not None,
        bool(docs & item.answer_docs) if found is not None and item.answer_docs else None,
        bool(refs & item.answer_units) if found is not None and item.answer_units else None,
        [d.unit_key for d in found.documents[:3]] if found else [], [e.source_id for e in out.evidence], cited_unit,
        [o['rule'] for o in r.override_reasons], len(r.llm_calls),
        (sum(c.input_tokens or 0 for c in r.llm_calls), sum(c.output_tokens or 0 for c in r.llm_calls)),
        tuple(out.missing_items))


def run(judge: str, items: list[EvalItem], ref: Reference, search: DbSearch, repeat: int = 1,
        progress: Callable[[str], None] | None = None, max_calls: int | None = None) -> tuple[list[Judged], str | None]:
    """(끝낸 문항들, 멈춘 이유). 검색·DB 오류나 Ctrl+C 로 멈춰도 그때까지 결과는 돌려준다 (유료 호출을 버리지 않게).
    LLM 오류는 run_flow 가 안전 기본값으로 처리하므로 여기까지 오지 않는다. 이유에는 오류 종류만 (원문·주소 없음).
    max_calls: 쓴 LLM 호출이 이 수에 이르면 다음 문항을 시작하지 않는다 (예산 보호. 문항 중간에는 끊지 않으므로
    한 문항의 호출 수만큼 넘을 수 있다)."""
    out = []
    for n in range(1, repeat + 1):
        for i, item in enumerate(items, 1):
            if max_calls is not None and (spent := sum(j.calls for j in out)) >= max_calls:
                return out, f'{n}회 {item.eval_id} 앞에서 멈춤 (호출 상한 {max_calls}, 쓴 호출 {spent})'
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


def situation_ask(j: Judged) -> bool:
    """정답은 ASK_MORE 가 아닌데 1차 판단이 가이드 상황만 되물음 (missing_items 가 situation 하나). 설계대로인 첫 반응이라
    엄격 점수에서는 틀림이지만 '상황 되묻기 제외' 칸에서는 뺀다. 상황 말고 다른 것도 물었으면 여기 들지 않는다."""
    want = expected(j.item, 'action')
    return want not in (None, 'ASK_MORE') and j.predicted['action'] == 'ASK_MORE' and set(j.missing) == {'situation'}


def cause(j: Judged) -> str:
    """틀린 문항의 원인 쪽 (조사 후보). 정답 항목(같은 본문 포함)을 찾았으면 '판단' (D, M4-4-1).
    못 찾았으면 정답 가이드도 못 찾음 → '검색: 가이드', 가이드는 찾음 → '검색: 항목' (C, M3-4-1).
    정답 항목이 정의되지 않은 문항은 가이드 적중만 보고, 검색을 안 했으면 '판단'."""
    wrong = [f for f in FIELDS if is_correct(j, f) is False]
    if not wrong:
        return ''
    if situation_ask(j) and set(wrong) <= {'action', 'team'}:     # 되물으면 팀도 아직 정하지 않는다 (판단 결함 후보 아님)
        return SITUATION_ASKS
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


def cited_rate(js: list[Judged]) -> dict:
    marks = [j.cited_unit for j in js if j.cited_unit is not None]
    return {'n': len(marks), 'acc': sum(marks) / len(marks) if marks else None}


def score(js: list[Judged]) -> dict:
    """{묶음: {칸: {n, acc}}}. 묶음 = 전체 · 기존 40 · 확장 10 (평가셋), 질문시트, 보조 전체 · 보조: <종류> ·
    보조 작성: <작성자>. 질문시트·보조는 '전체'에 넣지 않는다 (참고 시험지라 공식 점수와 섞지 않는다).
    작성자별은 같은 모델이 쓴 질문을 같은 계열 모델이 더 잘 맞히는지 보려고 나눈다. 반복하면 회차별로 낸 뒤 범위를 따로 적는다."""
    groups: dict[str, list[Judged]] = defaultdict(list)
    for j in js:
        if j.item.set == 'eval':
            groups['전체'].append(j)
        if j.item.set == 'extra':
            groups[EXTRA_GROUP].append(j)
        groups[j.item.split].append(j)
    for j in js:                                       # 작성자별은 종류별 뒤에 (표에서 종류끼리 모이게)
        if j.item.set == 'extra' and j.item.author:
            groups[f'보조 작성: {j.item.author}'].append(j)
    out = {}
    for g, rs in groups.items():
        d = {'문항': {'n': len(rs), 'acc': None}} | {f: rate(rs, f) for f in FIELDS}
        d['긴급도 ±1'] = near_urgency(rs)
        d[f'팀 ({TEAM_ASSIGNED})'] = rate([j for j in rs if j.item.team_scoring == TEAM_ASSIGNED], 'team')
        d[GUIDED_COL] = rate([j for j in rs if j.item.team_scoring == TEAM_GUIDED], 'team')
        d[CITED] = cited_rate(rs)
        asks = [j for j in rs if situation_ask(j)]
        d[SITUATION_ACTION] = rate([j for j in rs if not situation_ask(j)], 'action')
        d[SITUATION_ASKS] = {'n': len(asks), 'acc': None, 'count': len(asks)}
        out[g] = d
    return out


def confusion(js: list[Judged], set_: str = 'eval') -> dict[str, dict[str, int]]:
    """처리 방향 혼동표 {정답: {예측: 수}}. 시험지(set_) 하나만. 정답이 없는 문항(질문시트, 보조의 '-')은 뺀다."""
    c: dict[str, Counter] = defaultdict(Counter)
    for j in js:
        if j.item.set == set_ and j.item.action:
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
                    '정답 항목 찾음', '검색 상위 3', '근거', CITED, '보정 규칙', '호출 수', '되물은 항목', SITUATION_ASKS,
                    '틀린 원인', '비고'])
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
                        '; '.join(j.top_units), '; '.join(j.evidence), yn[j.cited_unit], '; '.join(j.overrides),
                        j.calls, '; '.join(j.missing), 'Y' if situation_ask(j) else '', cause(j),
                        known_note(j)])
    rounds = by_round(js)
    # 혼동표·추가 처리·틀린 문항은 모든 회차 (반복하면 한 번이라도 틀린 문항이 빠지지 않게)
    summary = {'meta': meta, '점수': {n: score(rs) for n, rs in rounds.items()},
               **{name: confusion(js, s) for s, name in CONFUSION.items() if any(j.item.set == s for j in js)},
               '추가 처리': [{'회차': j.round, '문항': j.item.eval_id, '정답': j.item.additional, '긴급 징후': j.urgent,
                          '처리 방향': j.predicted['action']} for j in js if j.item.additional != 'NONE'],
               '틀린 문항': [{'회차': j.round, '문항': j.item.eval_id, '원인': cause(j),
                          '틀린 칸': [NAMES[x] for x in FIELDS if is_correct(j, x) is False], '비고': known_note(j)}
                         for j in js if cause(j)],
               SITUATION_ASKS: [{'회차': j.round, '문항': j.item.eval_id, '정답 처리 방향': j.item.action}
                                for j in js if situation_ask(j)],
               # 근거는 판단 칸이 아니라 틀린 문항에 안 나오므로 따로. 흐름이 근거 부족으로 ANSWER 를 바꿔 분모에서 빠진 것도
               '근거 불일치': [{'회차': j.round, '문항': j.item.eval_id, '정답 항목 찾음': j.found_unit, '근거': j.evidence}
                          for j in js if j.cited_unit is False],
               '근거 부족으로 빠짐': [{'회차': j.round, '문항': j.item.eval_id, '보정 규칙': j.overrides,
                                '정답 항목 찾음': j.found_unit}
                               for j in js if j.cited_unit is None and set(j.overrides) & EVIDENCE_RULES]}
    with open(os.path.join(out_dir, '요약.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, '요약.md'), 'w', encoding='utf-8') as f:
        f.write(summary_md(summary))
    return summary


def known_note(j: Judged) -> str:
    return '; '.join(note for (eid, f), note in KNOWN_MISSES.items() if eid == j.item.eval_id and is_correct(j, f) is False)


def _pct(d: dict) -> str:
    if 'count' in d:
        return f"{d['count']}건"
    return '—' if d['acc'] is None else f"{d['acc']:.0%} ({d['n']})"


def summary_md(summary: dict) -> str:
    m = summary['meta']
    out = [f"# 판단 평가 — {m['판단기']}", '', '| 항목 | 값 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in m.items()]
    rounds = summary['점수']
    if not rounds:
        return '\n'.join(out + ['', '끝낸 문항이 없습니다.']) + '\n'
    cols = [*FIELDS, SITUATION_ACTION, SITUATION_ASKS, '긴급도 ±1', f'팀 ({TEAM_ASSIGNED})', GUIDED_COL, CITED]
    head = [NAMES.get(c, c) for c in cols]
    for n, sc in rounds.items():
        out += ['', f'## 정확도 ({n}회차, 괄호는 채점한 문항 수)', '', '| 묶음 | ' + ' | '.join(head) + ' |',
                '|---|' + '---|' * len(cols)]
        out += [f'| {g} | ' + ' | '.join(_pct(d[c]) for c in cols) + ' |' for g, d in sc.items()]
    tops = [g for g in ('전체', GUIDE_GROUP, EXTRA_GROUP) if any(g in r for r in rounds.values())]
    if GUIDE_GROUP in tops:
        out += ['', f'{GUIDE_GROUP}: 정답을 정답 항목에서 끌어낸 참고 점수 (사람이 단 정답 아님, 긴급도·처리 방향 정답 없음). '
                '공식 점수인 평가셋 전체와 섞지 않는다']
    if EXTRA_GROUP in tops:
        out += ['', f'{EXTRA_GROUP}: 보조 시험지 참고 점수 (평가셋이 거의 다루지 않는 문의). 종류마다 몇 건뿐이라 점수보다 '
                '틀린 문항을 본다. 작성자별(Claude·Codex)은 같은 계열 모델이 쓴 질문에 유리한지 보는 값. 평가셋 전체와 섞지 않는다']
    out += ['', f'{SITUATION_ACTION}: 정답이 ASK_MORE 가 아닌데 첫 판단이 가이드 상황만 되물은 문항({SITUATION_ASKS})을 '
            '빼고 낸 처리 방향 정확도. 평가는 첫 글 하나만 넣어 되물은 뒤의 방향은 모른다 (M4-3-1 상황 되묻기). '
            '엄격 점수는 처리 방향 칸']
    out += ['', f'{CITED}: ANSWER 로 답한 문항 중 문서 근거에 정답 항목(같은 본문 포함)이 있는 비율 (참고). '
            '평가셋의 정답 항목은 그 세부 유형 코드가 붙은 모든 항목이라 넓다']
    # 범위는 끝까지 돈 회차만 (중간에 멈춘 회차는 문항이 적어 같은 시험지가 아니다)
    size = {n: sum(r[g]['문항']['n'] for g in tops if g in r) for n, r in rounds.items()}
    done = [rounds[n] for n in rounds if size[n] == max(size.values())]
    if len(done) > 1:
        for g in tops:
            out += ['', f'## 반복 {len(done)}회 범위 ({g}, 끝까지 돈 회차만)', '', '| 칸 | 최소 | 최대 |', '|---|---|---|']
            for c in cols:
                accs = [r[g][c]['acc'] for r in done if r[g][c]['acc'] is not None]
                if accs:
                    out.append(f'| {NAMES.get(c, c)} | {min(accs):.0%} | {max(accs):.0%} |')
    for name in CONFUSION.values():
        if name not in summary:
            continue
        table = summary[name]
        acts = sorted({a for row in table.values() for a in row} | set(table))
        out += ['', f'## {name} (행 = 정답, 열 = 예측, {len(rounds)}회 합)', '',
                '| 정답 \\ 예측 | ' + ' | '.join(acts) + ' |', '|---|' + '---|' * len(acts)]
        out += [f'| {a} | ' + ' | '.join(str(row.get(b, '')) for b in acts) + ' |' for a, row in table.items()]
    out += ['', f"## 추가 처리 ({len(summary['추가 처리'])}건, 적어서 점수 대신 목록으로)", ''] + \
        [f"- {x['회차']}회 {x['문항']} {x['정답']}: 긴급 징후 {'있음' if x['긴급 징후'] else '없음'}, 처리 방향 {x['처리 방향']}"
         for x in summary['추가 처리']]
    wrong = summary['틀린 문항']
    out += ['', f'## 틀린 문항 {len(wrong)}개 (모든 회차. 원인은 조사 후보: 검색 → C, 판단 → D)', '',
            '| 회차 | 문항 | 원인 | 틀린 칸 | 비고 |', '|---|---|---|---|---|'] + \
        [f"| {x['회차']} | {x['문항']} | {x['원인']} | {', '.join(x['틀린 칸'])} | {x['비고']} |" for x in wrong]
    yn = {True: 'Y', False: 'N', None: ''}
    miss = summary.get('근거 불일치', [])
    out += ['', f'## {CITED} 틀림 {len(miss)}개 (ANSWER 근거에 정답 항목 없음. 정답 항목 찾음 N → 검색, Y → 판단)', '',
            '| 회차 | 문항 | 정답 항목 찾음 | 근거 |', '|---|---|---|---|'] + \
        [f"| {x['회차']} | {x['문항']} | {yn[x['정답 항목 찾음']]} | {'; '.join(x['근거'])} |" for x in miss]
    asks = summary.get(SITUATION_ASKS, [])
    out += ['', f'## {SITUATION_ASKS} {len(asks)}개 (첫 판단이 상황만 되물음. 처리 방향 엄격 점수에서는 틀림)', '',
            '| 회차 | 문항 | 정답 처리 방향 |', '|---|---|---|'] +         [f"| {x['회차']} | {x['문항']} | {x['정답 처리 방향']} |" for x in asks]
    gone = summary.get('근거 부족으로 빠짐', [])
    out += ['', f'## 근거 부족으로 {CITED}에서 빠짐 {len(gone)}개 (흐름이 ANSWER 를 담당자 연결로 바꿈)', '',
            '| 회차 | 문항 | 보정 규칙 | 정답 항목 찾음 |', '|---|---|---|---|'] + \
        [f"| {x['회차']} | {x['문항']} | {', '.join(x['보정 규칙'])} | {yn[x['정답 항목 찾음']]} |" for x in gone]
    return '\n'.join(out) + '\n'


def describe(judge: str, ref: Reference, args) -> dict:
    port = None
    if judge == 'claude':
        from app.agent.llm import get_llm_adapter
        port = get_llm_adapter()
    return {'판단기': judge, '모델': port.model if port else 'mock', '실행': args.stamp, 'git': git_state(),
            '판단 코드 지문': flow_fingerprint(), '프롬프트 지문': prompt_fingerprint(ref), '시험지': args.set,
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
    ap.add_argument('--set', default='eval', choices=tuple(SETS),
                    help='eval (평가셋 50, 공식) · guide (질문시트, 참고) · extra (보조 시험지, 참고) · all (셋 다 한 번에)')
    ap.add_argument('--extra-csv', default=EXTRA_CSV, help='보조 시험지 파일 (초안을 돌려 볼 때)')
    ap.add_argument('--max-calls', type=positive, help='LLM 호출이 이 수에 이르면 다음 문항을 시작하지 않는다 (예산 보호)')
    ap.add_argument('--model', default='bge-m3', help='검색 임베딩 모델')
    ap.add_argument('--limit', type=positive, help='앞에서 몇 문항만 (실제 호출 전에 적게 돌려 볼 때)')
    ap.add_argument('--ids', help='쉼표로 문항 id (예: EV-001,EV-040)')
    ap.add_argument('--repeat', type=positive, default=1, help='같은 문항을 몇 번 (LLM 결과가 매번 다를 수 있어 범위를 본다)')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    units = corpus_units()
    try:
        items = (load_items(units=units) if 'eval' in SETS[a.set] else []) + \
            (load_guide_items(units=units) if 'guide' in SETS[a.set] else []) + \
            (load_extra_items(a.extra_csv, units=units) if 'extra' in SETS[a.set] else [])
    except (OSError, ValueError, KeyError) as ex:      # 보조 시험지가 없거나 칸 수·번호·정답이 잘못됨. DB·모델을 열기 전에 멈춘다
        print(f'시험지를 읽지 못했습니다: {type(ex).__name__} {ex}')
        return 2
    if a.ids:                                          # DB·모델을 열기 전에 고른 문항을 확인한다
        want = {x.strip() for x in a.ids.split(',') if x.strip()}
        if not want:
            print('--ids 에 문항이 없습니다')
            return 2
        if unknown := want - {i.eval_id for i in items}:
            print(f'시험지({a.set})에 없는 문항: {", ".join(sorted(unknown))}')
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
    if 'guide' in SETS[a.set]:                         # 질문시트 정답은 질문 파일과 정리본 단위에서 끌어낸다
        import glob
        meta['질문시트 파일'] = file_hash(sorted(glob.glob(os.path.join(QUESTIONS_DIR, '*_질문.csv'))))
        meta['단위 지문'] = units_fingerprint(units)        # 본문·범위·정책. 유형 코드는 아래 끌어낸 정답 지문으로
        labels = sorted((i.eval_id, i.scenario or '', '|'.join(sorted(i.answer_units))) for i in items if i.set == 'guide')
        meta['질문시트 정답 지문'] = hashlib.sha1(json.dumps(labels, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]
    if 'extra' in SETS[a.set]:
        meta['보조 시험지 파일'] = file_hash([a.extra_csv])
    if a.max_calls:
        meta['호출 상한'] = a.max_calls
    from ..embedding import Embedder
    emb = Embedder(a.model)
    meta['검색 모델'] = emb.model_id
    search = DbSearch(a.database_url, emb)
    if a.judge == 'claude':
        print(f'실제 Claude 호출: 문항 {len(items)} × 반복 {a.repeat} × 기본 1~2회 (모델 {meta["모델"]})')
    js, stopped = run(a.judge, items, ref, search, a.repeat, progress=lambda s: print(f'  {s}', end='\r'),
                      max_calls=a.max_calls)
    try:
        search.close()
    except Exception:                                  # 정리 실패가 결과 기록을 가리지 않게
        pass
    calls, tin, tout = sum(j.calls for j in js), sum(j.tokens[0] for j in js), sum(j.tokens[1] for j in js)
    meta |= {'끝낸 문항': f'{len(js)} / {len(items) * a.repeat}', '중단': stopped or '없음', '호출': calls,
             '토큰 (입력/출력)': f'{tin}/{tout}', '실패': dict(Counter(j.error_code for j in js if j.failure)) or '없음'}
    out_dir = new_run_dir(a.out, f"{a.stamp}_판단_{a.judge.replace(':', '-')}" + ('' if a.set == 'eval' else f'_{a.set}'))
    summary = write(out_dir, js, meta)
    print(summary_md(summary))
    print(f'→ {out_dir}')
    if stopped:
        print(f'[중단] {stopped}. 끝낸 문항까지만 기록했습니다.')
    return 1 if stopped else 0


if __name__ == '__main__':
    raise SystemExit(main())
