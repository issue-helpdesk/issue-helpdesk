"""문의 메시지를 판단 흐름(M4-2-1)에 넘기는 곳. AI 입력을 만들고 run_flow 결과를 돌려준다. 저장은 InquiryService 가 한다.

- 값 4개(추가 질문 횟수·답을 못 얻은 횟수·긴급 고정·이전 긴급도)는 판단 이력에서 센다 (docs/09 4.2)
- 모델·검색은 의존성으로 받는다. 시험에서는 Mock 모델과 가짜 검색으로 바꾼다
"""
import os
from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import Depends

from app.agent.flow import FlowResult, run_flow
from app.agent.flow.correct import known_items
from app.agent.llm import AIInput, CategoryInfo, Facts, LLMPort, Taxonomy, TypeInfo, UserContext, get_llm_adapter
from app.agent.llm import Message as AiMessage
from app.models import Inquiry, InquiryAssessment, Message, User
from app.rag.search.runtime import SearchFnDep
from app.repositories.inquiry import InquiryRepositoryDep
from app.repositories.reference import ReferenceRepositoryDep
from app.repositories.user import UserRepositoryDep

URGENCY_LEVELS = ("P1", "P2", "P3", "P4")
ROLES = {"USER": "user", "AI": "assistant"}


def history_limit() -> int:
    """AI 에 넘길 이전 대화 수. (기본 10 = 사용자·AI 5번씩)."""
    return int(os.environ.get("AI_HISTORY_LIMIT", 10))


class AiResponder(Protocol):
    def respond(self, inquiry: Inquiry, user: User, history: list[Message]) -> FlowResult: ...


# 모델은 실제로 부를 때 연다. LLM_API_KEY 가 없어도 사용자 글은 먼저 저장되고 503 으로 응답한다 (IQ-01 AI_UNAVAILABLE)
def get_llm_port_factory() -> Callable[[], LLMPort]:
    return get_llm_adapter


LlmPortFactoryDep = Annotated[Callable[[], LLMPort], Depends(get_llm_port_factory)]


class FlowAiResponder:
    def __init__(
        self,
        inquiries: InquiryRepositoryDep,
        references: ReferenceRepositoryDep,
        users: UserRepositoryDep,
        llm_port: LlmPortFactoryDep,
        search_fn: SearchFnDep,
    ) -> None:
        self.inquiries = inquiries
        self.references = references
        self.users = users
        self.llm_port = llm_port
        self.search_fn = search_fn

    def respond(self, inquiry: Inquiry, user: User, history: list[Message]) -> FlowResult:
        """history: 진행 중 세션의 메시지. 마지막이 이번 사용자 글이다."""
        department = self.users.get_department(user.department_id) if user.department_id else None
        inp = build_ai_input(inquiry, user, department.name if department else None, history,
                             self.inquiries.assessments(inquiry.id))
        return run_flow(inp, self.llm_port(), self.taxonomy(), self.users.all_names(), self.search_fn)

    def taxonomy(self) -> Taxonomy:
        """분류 체계 (08 1.1). 세부 유형은 활성인 것만."""
        return Taxonomy(
            categories=tuple(CategoryInfo(c.code, c.name, c.description or "")
                             for c in self.references.list_categories()),
            types=tuple(TypeInfo(t.code, t.category_code, t.name, t.request_kind, t.default_urgency)
                        for t, _ in self.references.list_inquiry_types([], is_active=True)),
        )


AiResponderDep = Annotated[AiResponder, Depends(FlowAiResponder)]


def build_ai_input(inquiry: Inquiry, user: User, department_name: str | None, history: list[Message],
                   prior: list[InquiryAssessment]) -> AIInput:
    *before, current = history
    talk = [AiMessage(role=ROLES[m.sender], content=m.content) for m in before if m.sender in ROLES]
    asked, unanswered = ask_more_counts(prior)
    return AIInput(
        session_id=str(current.session_id),
        inquiry_id=str(inquiry.id),
        message=current.content,
        history=talk[-history_limit():],
        collected_facts=facts_of(prior[-1]) if prior else None,
        ask_more_count=asked,
        ask_more_unanswered_count=unanswered,
        prior_urgent_signal=any(a.urgent_signal for a in prior),
        prior_urgency=min((a.urgency for a in prior if a.urgency), key=URGENCY_LEVELS.index, default=None),
        user_context=UserContext(employee_no=user.employee_no, service_role=user.service_role,
                                 department_name=department_name),
        search=None,
    )


def ask_more_counts(prior: list[InquiryAssessment]) -> tuple[int, int]:
    """(추가 질문 수, 답을 못 얻은 질문 수). docs/09 4.2.

    물은 항목(missing_items)이 바로 다음 판단의 facts 에서 하나도 채워지지 않으면 답을 못 얻은 것이다.
    마지막 질문은 이번 글이 그 답이라 아직 세지 않는다.
    """
    asked = [i for i, a in enumerate(prior) if a.action == "ASK_MORE"]
    unanswered = sum(
        1 for i in asked
        if i + 1 < len(prior) and prior[i].missing_items
        and not set(prior[i].missing_items) & known_items(facts_of(prior[i + 1]))
    )
    return len(asked), unanswered


def facts_of(assessment: InquiryAssessment) -> Facts | None:
    return Facts.model_validate(assessment.facts) if assessment.facts else None
