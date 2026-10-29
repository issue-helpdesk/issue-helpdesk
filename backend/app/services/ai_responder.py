from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends

from app.models import Inquiry, Message

TITLE_MAX = 50


@dataclass
class AiReply:
    content: str
    action: str
    title: str | None = None


class AiResponder(Protocol):
    def respond(self, inquiry: Inquiry, history: list[Message]) -> AiReply: ...


class PlaceholderAiResponder:
    """실제 AI 연결 전까지 쓰는 임시 응답. 대화를 이어갈 수 있게 항상 추가 질문(ASK_MORE)으로 답한다."""

    def respond(self, inquiry: Inquiry, history: list[Message]) -> AiReply:
        first = next(m.content for m in history if m.sender == "USER")
        return AiReply(
            content="AI 상담 기능을 준비하고 있습니다. 추가로 알려 주실 내용이 있으면 입력해 주세요.",
            action="ASK_MORE",
            title=first.splitlines()[0][:TITLE_MAX],
        )


AiResponderDep = Annotated[AiResponder, Depends(PlaceholderAiResponder)]
