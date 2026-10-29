"""Claude Adapter (시스템 설계서 6.3). Claude API 를 부르는 곳은 여기 하나다."""
import anthropic

from app.agent.llm.port import LLMError, LLMReply

# 응답 시간 목표가 아직 없어 정한 값 (2026-10-29). 키를 받아 실제 시간을 잰 뒤 다시 정한다
TIMEOUT_SECONDS = 30.0          # 한 번 호출 제한 시간
MAX_RETRIES = 1                 # SDK 가 시간 초과·연결 오류·429·5xx 를 한 번 더 시도한다. 최악 약 1분
MAX_TOKENS = 16000
# 안전 판단으로 거절하면 다른 모델로 다시 처리하지 않고 REFUSAL 로 끝낸다 → 안전 기본값(담당자 연결 제안). 2026-10-29 결정


class ClaudeAdapter:
    name = 'Claude'

    def __init__(self, api_key: str, model: str, client: anthropic.Anthropic | None = None):
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS,
                                                     max_retries=MAX_RETRIES)

    def complete(self, system: str, user: str, schema: dict) -> LLMReply:
        try:
            r = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                # 시스템 프롬프트는 호출마다 같아서 캐시한다
                system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': user}],
                output_config={'format': {'type': 'json_schema', 'schema': schema}},
            )
        except anthropic.APITimeoutError:
            raise LLMError('TIMEOUT', self.model) from None
        except anthropic.RateLimitError:
            raise LLMError('RATE_LIMIT', self.model) from None
        except anthropic.APIStatusError as e:
            raise LLMError(f'HTTP_{e.status_code}', self.model) from None
        except anthropic.APIConnectionError:
            raise LLMError('CONNECTION', self.model) from None

        u = r.usage
        # 캐시에서 읽거나 캐시에 쓴 입력도 입력 토큰에 넣는다
        tokens = dict(model=r.model,
                      input_tokens=u.input_tokens + (u.cache_creation_input_tokens or 0)
                      + (u.cache_read_input_tokens or 0),
                      output_tokens=u.output_tokens)
        if r.stop_reason == 'refusal':
            raise LLMError('REFUSAL', **tokens)
        if r.stop_reason == 'max_tokens':
            raise LLMError('MAX_TOKENS', **tokens)
        text = next((b.text for b in r.content if b.type == 'text'), '')
        return LLMReply(text=text, **tokens)
