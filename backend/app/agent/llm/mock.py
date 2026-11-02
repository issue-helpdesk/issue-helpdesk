"""Mock Adapter (시스템 설계서 6.3). API 키 없이 판단 흐름을 돌리거나 시험할 때 쓴다. 외부로 아무것도 보내지 않는다."""
from collections.abc import Callable, Iterable

from app.agent.llm.port import LLMError, LLMReply
from app.agent.llm.schemas import safe_default

Reply = str | LLMError | Callable[[str, str], str]


class MockAdapter:
    name = 'Mock'

    def __init__(self, replies: Iterable[Reply] = (), model: str = 'mock'):
        """replies: 차례로 돌려줄 응답. JSON 글, 던질 LLMError, 또는 (system, user) → 글 함수.
        다 쓰면 마지막 것을 계속 쓴다. 비우면 안전 기본값(담당자 연결 제안)을 돌려준다.
        """
        self.model = model
        self._replies = list(replies) or [safe_default().model_dump_json()]
        self.requests: list[tuple[str, str]] = []      # 받은 (system, user). 시험에서 보낸 글을 확인한다

    def complete(self, system: str, user: str, schema: dict) -> LLMReply:
        self.requests.append((system, user))
        reply = self._replies[min(len(self.requests), len(self._replies)) - 1]
        if isinstance(reply, LLMError):
            raise reply
        text = reply(system, user) if callable(reply) else reply
        return LLMReply(text=text, model=self.model)
