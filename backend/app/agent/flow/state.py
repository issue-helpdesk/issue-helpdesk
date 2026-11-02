"""판단 흐름 노드끼리 주고받는 값 (LangGraph State). 노드는 바꾼 칸만 돌려준다."""
import operator
from typing import Annotated, TypedDict

from app.agent.flow.result import FlowResult
from app.agent.flow.urgency import Urgency
from app.agent.llm import AIInput, AIOutput, JudgeResult, LlmCallRecord
from app.rag.search import SearchResponse


class FlowState(TypedDict, total=False):
    inp: AIInput                        # 서버가 넘긴 입력. search 는 흐름이 채운다
    second: bool                        # 지금 2차(검색 뒤) 판단인가
    judge: JudgeResult                  # 이번 call_judge 결과
    retried: bool                       # 이번 판단에서 reply 때문에 이미 다시 불렀는가 (9단계는 한 번만)
    retry: bool                         # 보정 노드가 다시 생성을 요청함
    search: SearchResponse | None
    output: AIOutput                    # 보정 후 값
    ai_output: dict | None
    overrides: list[dict]
    failure: str | None
    error_code: str | None
    next_step: str | None               # None 이면 1차 뒤 검색으로 간다
    calls: Annotated[list[LlmCallRecord], operator.add]     # 호출 기록은 덮어쓰지 않고 이어 붙인다
    urgency: Urgency
    result: FlowResult
