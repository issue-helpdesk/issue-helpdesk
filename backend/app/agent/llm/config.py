"""모델 설정. 값은 서버 .env 에만 둔다 (이름은 시스템 설계서 16.2)."""
import os
from functools import lru_cache

from dotenv import load_dotenv

from app.agent.llm.claude import ClaudeAdapter
from app.core.config import ROOT

load_dotenv(ROOT / '.env')

DEFAULT_MODEL = 'claude-sonnet-5-5'


@lru_cache
def get_llm_adapter() -> ClaudeAdapter:
    key = os.environ.get('LLM_API_KEY')
    if not key:
        raise RuntimeError('LLM_API_KEY 가 없습니다. 루트 .env 를 확인하세요.')
    return ClaudeAdapter(api_key=key, model=os.environ.get('LLM_MODEL') or DEFAULT_MODEL)
