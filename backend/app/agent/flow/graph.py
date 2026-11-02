"""판단 흐름 (WBS M4-2-1). docs/09 4.1 순서를 LangGraph 로 잇는다. 규칙은 correct.py·urgency.py 에 있다.

judge_first ─▶ correct_first ─┬─ 다시 생성 ─▶ judge_first
                              ├─ 끝 (긴급·추가 질문·상한·실패) ─▶ decide_urgency
                              └─ 검색 ─▶ search ─▶ judge_second ─▶ correct_second ─┬─ 다시 생성 ─▶ judge_second
                                                                                    └─▶ decide_urgency
decide_urgency ─▶ package ─▶ 끝

- 1차에서 Claude 가 실패하면(AI_FAILED) 검색·2차 없이 offer 로 끝낸다 (09 T11).
- 체크포인트는 쓰지 않는다. 메시지마다 처음부터 돌고, 대화 사이 값은 서버가 AIInput 으로 넘긴다 (09 4.2).
"""
from collections.abc import Callable, Iterable

from langgraph.graph import END, START, StateGraph

from app.agent.flow.correct import LIMIT_RULES, Limits, correct, override, unsafe_reply
from app.agent.flow.result import FlowResult, source_rows
from app.agent.flow.state import FlowState
from app.agent.flow.urgency import decide_urgency
from app.agent.llm import AIInput, AIOutput, LLMPort, Taxonomy, call_judge, safe_default
from app.rag.search import SearchRequest, SearchResponse, build_query

SearchFn = Callable[[SearchRequest], SearchResponse]     # 예: lambda req: search(session, req, embedder)
FAILURE_REASON = {'ALL_BLOCKED': '근거가 모두 외부 전송 제한'}


def build_flow(port: LLMPort, taxonomy: Taxonomy, staff_names: Iterable[str], search_fn: SearchFn,
               limits: Limits | None = None):
    """판단 흐름 그래프. DB 값(분류 체계·직원 이름)과 검색은 서버가 넘긴다. 결과는 run_flow 로 받는다."""
    staff = tuple(staff_names)
    limits = limits or Limits.from_env()

    def judge(state: FlowState, second: bool) -> dict:
        inp = state['inp'].model_copy(update={'search': state['search'] if second else None})
        r = call_judge(inp, port, taxonomy, staff, 'ANSWER' if second else 'CLASSIFY')
        return {'judge': r, 'second': second, 'calls': list(r.calls)}

    def check(state: FlowState) -> dict:
        r, second = state['judge'], state['second']

        def settle(out: AIOutput, failure: str | None, code: str | None):
            o = [override('action', None, 'ESCALATE', failure, code or FAILURE_REASON[failure])] if failure else []
            c = correct(out, state['inp'], second=second, sent=r.evidence, search=state.get('search'),
                        taxonomy=taxonomy, limits=limits)
            o += c.overrides
            return c.output, o, next_step(c.output, o, second, failure)

        ai_output, failure, code = r.ai_output, r.failure, r.error_code
        out, o, step = settle(r.output, failure, code)
        # 08 3.2 9단계. 1차 뒤 검색으로 가면 이 reply 는 보여 주지 않으므로 보지 않는다
        if failure is None and (second or step) and unsafe_reply(r.output.reply):
            if not state.get('retried'):
                return {'retry': True, 'retried': True}
            ai_output, failure, code = None, 'AI_FAILED', 'UNSAFE_REPLY'
            out, o, step = settle(safe_default(), failure, code)
        return {'retry': False, 'output': out, 'ai_output': ai_output, 'overrides': o, 'failure': failure,
                'error_code': code, 'next_step': step}

    def route(state: FlowState) -> str:
        if state['retry']:
            return 'retry'
        return 'done' if state['next_step'] else 'search'

    def search(state: FlowState) -> dict:
        inp = state['inp']
        query = build_query([m.content for m in inp.history if m.role == 'user'] + [inp.message])
        return {'search': search_fn(SearchRequest(query=query, service_role=inp.user_context.service_role)),
                'retried': False}

    def urgency(state: FlowState) -> dict:
        return {'urgency': decide_urgency(state['output'], taxonomy, state['inp'].prior_urgency)}

    def package(state: FlowState) -> dict:
        u, out, found = state['urgency'], state['output'], state.get('search')
        return {'result': FlowResult(
            output=out, urgency=u.value, needs_triage=u.needs_triage, next_step=state['next_step'],
            ai_output=state['ai_output'], override_reasons=tuple(state['overrides']) + u.overrides,
            llm_calls=tuple(state['calls']), failure=state['failure'], error_code=state['error_code'],
            sources=source_rows(out, found), evidence=state['judge'].evidence if state['second'] else None)}

    g = StateGraph(FlowState)
    g.add_node('judge_first', lambda s: judge(s, False))
    g.add_node('correct_first', check)
    g.add_node('search', search)
    g.add_node('judge_second', lambda s: judge(s, True))
    g.add_node('correct_second', check)
    g.add_node('decide_urgency', urgency)
    g.add_node('package', package)

    g.add_edge(START, 'judge_first')
    g.add_edge('judge_first', 'correct_first')
    g.add_conditional_edges('correct_first', route,
                            {'retry': 'judge_first', 'done': 'decide_urgency', 'search': 'search'})
    g.add_edge('search', 'judge_second')
    g.add_edge('judge_second', 'correct_second')
    g.add_conditional_edges('correct_second', route, {'retry': 'judge_second', 'done': 'decide_urgency'})
    g.add_edge('decide_urgency', 'package')
    g.add_edge('package', END)
    return g.compile()


def run_flow(inp: AIInput, port: LLMPort, taxonomy: Taxonomy, staff_names: Iterable[str], search_fn: SearchFn,
             limits: Limits | None = None) -> FlowResult:
    """메시지 하나를 판단한다. 같은 설정으로 여러 번 부르면 build_flow 결과를 만들어 두고 invoke 해도 된다."""
    state = build_flow(port, taxonomy, staff_names, search_fn, limits).invoke(
        {'inp': inp, 'search': None, 'retried': False, 'calls': []})
    return state['result']


def next_step(out: AIOutput, overrides: list[dict], second: bool, failure: str | None) -> str | None:
    """보정 후 값 → 다음 상태 (09 4.1). None 이면 1차 뒤 검색으로 간다."""
    if out.action == 'ASK_MORE':
        return 'collect'
    if second:
        return 'answered' if out.action == 'ANSWER' else 'offer'
    # 1차: 긴급 징후·추가 질문 상한(T04)·호출 실패(T11)만 여기서 끝낸다. 그 밖의 ESCALATE·ANSWER·OUT_OF_SCOPE 는 검색으로
    if failure or out.urgent_signal or any(o['rule'] in LIMIT_RULES for o in overrides):
        return 'offer'
    return None
