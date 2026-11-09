"""서버 로그 안전망 (docs/10 5.3 ④). 로그를 쓰기 직전에 A·B 를 한 번 더 가린다.

요청 본문·사용자 글을 로그에 찍지 않는 것(5.3 ①~③)이 먼저다. 이 필터는 그 규칙을 실수로 어겨도 비밀정보가 남지 않게 하는 마지막 장치다.

- MaskSecretsFilter  : logging.Filter. 모든 핸들러에 붙인다 (handler.addFilter). 로거에 붙이면 하위 로거의 기록은 거르지 못한다
- install_log_filter : 지금 있는 핸들러 모두에 붙인다. 프로그램 시작 때 로그 설정(basicConfig·uvicorn) **뒤에** 한 번 부른다

    from app.agent.sensitive import install_log_filter
    install_log_filter()
"""
import logging
import re

from app.agent.sensitive.mask import mask_secrets

FAILED_TEXT = '[민감정보 필터 오류로 로그 내용을 지웠습니다]'
# 서식기가 args 묶음을 그대로 풀어 쓰는 로거 (uvicorn AccessFormatter 는 args 5개를 꺼낸다). 이 로거는 args 를 하나씩 가린다
KEEP_ARGS = ('uvicorn.access',)
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
            if record.name in KEEP_ARGS and isinstance(record.args, tuple):
                record.args = tuple(_mask(a) if isinstance(a, str) else a for a in record.args)
            else:
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


def install_log_filter() -> int:
    """지금 있는 로그 핸들러 모두(루트·이름 있는 로거·logging.lastResort)에 MaskSecretsFilter 를 붙인다.
    이미 붙은 핸들러는 건너뛴다 (여러 번 불러도 된다). 붙인 핸들러 수를 돌려준다.

    핸들러에 붙이므로 로그 설정 뒤에 불러야 한다. 이 함수 뒤에 새로 만든 핸들러에는 붙지 않는다.
    lastResort 는 핸들러가 없는 로거(uvicorn 아래 app.* 등)의 WARNING 이상을 stderr 로 쓰는 기본 핸들러다."""
    handlers = list(logging.getLogger().handlers)
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            handlers += logger.handlers
    if logging.lastResort is not None:
        handlers.append(logging.lastResort)
    added = 0
    for h in dict.fromkeys(handlers):                 # 같은 핸들러를 여러 로거가 쓸 수 있다
        if not any(isinstance(f, MaskSecretsFilter) for f in h.filters):
            h.addFilter(MaskSecretsFilter())
            added += 1
    return added
