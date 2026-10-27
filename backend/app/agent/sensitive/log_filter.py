"""서버 로그 안전망 (docs/10 5.3 ④). 로그를 쓰기 직전에 A·B 를 한 번 더 가린다.

요청 본문·사용자 글을 로그에 찍지 않는 것(5.3 ①~③)이 먼저다. 이 필터는 그 규칙을 실수로 어겨도 비밀정보가 남지 않게 하는 마지막 장치다.

- MaskSecretsFilter : logging.Filter. 모든 핸들러에 붙인다 (handler.addFilter). 로거에 붙이면 하위 로거의 기록은 거르지 못한다
"""
import logging
import re

from app.agent.sensitive.mask import mask_secrets

FAILED_TEXT = '[민감정보 필터 오류로 로그 내용을 지웠습니다]'
# traceId (uuid4). 끝부분이 계좌번호 규칙(숫자를 - 로 이은 10자리 이상)에 걸려 가려지면 오류 원인을 찾을 수 없다 (07 5.7)
UUID = re.compile(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')


def _mask(text: str) -> str:
    """uuid 는 남기고 나머지만 가린다. split 결과의 홀수 자리가 uuid 다"""
    parts = UUID.split(text)
    return ''.join(p if i % 2 else mask_secrets(p).text for i, p in enumerate(parts))


class MaskSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """메시지·예외 내용·호출 위치를 가린다. 가리다 실패하면 내용을 지우고 남긴다 (실패하면 보내지 않는다, 3.3)."""
        try:
            record.msg = _mask(record.getMessage())
            record.args = None
            if record.exc_info:
                # Formatter 는 exc_text 가 있으면 예외를 다시 만들지 않고 이것을 쓴다
                record.exc_text = _mask(logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = _mask(record.exc_text)
            if record.stack_info:
                record.stack_info = _mask(record.stack_info)
        except Exception:
            record.msg, record.args = FAILED_TEXT, None
            record.exc_info = record.exc_text = record.stack_info = None
        return True
