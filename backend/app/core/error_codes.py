"""에러 코드·HTTP 상태·기본 message. docs/07.API_설계서.md 5.5·5.6 표와 맞춘다."""
from enum import Enum


class ErrorCode(Enum):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message

    # 공통 (5.5)
    INVALID_REQUEST = (400, "요청 형식이 올바르지 않습니다.")
    UNAUTHORIZED = (401, "로그인이 필요합니다.")
    TOKEN_EXPIRED = (401, "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.")
    FORBIDDEN = (403, "이 기능을 사용할 권한이 없습니다.")
    NOT_FOUND = (404, "요청한 정보를 찾을 수 없습니다.")
    METHOD_NOT_ALLOWED = (405, "지원하지 않는 요청입니다.")
    VALIDATION_ERROR = (422, "입력값을 확인해 주세요.")
    TOO_MANY_REQUESTS = (429, "요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    INTERNAL_ERROR = (500, "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    # 인증·사용자 (5.6)
    AUTH_INVALID_CREDENTIALS = (401, "사번 또는 비밀번호가 올바르지 않습니다.")
    AUTH_REFRESH_TOKEN_INVALID = (401, "로그인 정보가 만료되었습니다. 다시 로그인해 주세요.")
    AUTH_ACCOUNT_LOCKED = (403, "로그인 5회 실패로 계정이 잠겼습니다. 10분 후 다시 시도하거나 IT 헬프데스크(내선 1000)로 문의해 주세요.")
    AUTH_ACCOUNT_INACTIVE = (403, "이용이 제한된 계정입니다. IT 헬프데스크(내선 1000)로 문의해 주세요.")
    AUTH_PASSWORD_CHANGE_REQUIRED = (403, "비밀번호를 변경한 뒤 이용할 수 있습니다.")
    AUTH_CURRENT_PASSWORD_MISMATCH = (400, "현재 비밀번호가 올바르지 않습니다.")
    AUTH_PASSWORD_POLICY_VIOLATION = (422, "비밀번호 규칙에 맞지 않습니다.")
