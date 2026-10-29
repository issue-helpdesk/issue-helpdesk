"""모델 호출 공통 규칙 LLMPort (시스템 설계서 6.3). 판단 흐름은 특정 모델 SDK 를 직접 부르지 않고 이것만 쓴다.

Adapter 는 complete() 하나만 만든다. 보낼 글을 고르고 가리는 일, 응답을 검사하는 일은 call.py 가 한다.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMReply:
    text: str                               # 모델이 쓴 JSON 글
    model: str                              # 실제로 답한 모델 (llm_calls.model)
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMError(Exception):
    """모델 호출 실패. code 는 llm_calls.error_code 에 남긴다 (예: TIMEOUT · RATE_LIMIT · HTTP_500 · REFUSAL)."""

    def __init__(self, code: str, model: str | None = None, input_tokens: int | None = None,
                 output_tokens: int | None = None):
        super().__init__(code)
        self.code = code
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class LLMPort(Protocol):
    name: str                               # llm_calls.adapter (Claude · Mock)
    model: str                              # 설정한 모델

    def complete(self, system: str, user: str, schema: dict) -> LLMReply:
        """system·user 를 보내고 schema 모양의 JSON 글을 받는다. 실패하면 LLMError."""
        ...
