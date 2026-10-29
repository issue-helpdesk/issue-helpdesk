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
    USER_NOT_FOUND = (404, "사용자를 찾을 수 없습니다.")
    USER_EMPLOYEE_NO_DUPLICATE = (409, "이미 등록된 사번입니다.")
    USER_EMAIL_DUPLICATE = (409, "이미 등록된 이메일입니다.")
    USER_SELF_CHANGE_NOT_ALLOWED = (409, "자신의 서비스 권한과 계정 상태는 변경할 수 없습니다.")
    USER_STATUS_REASON_REQUIRED = (422, "계정 상태를 변경할 때는 사유를 입력해 주세요.")

    # 문의·상담 (5.6)
    INQUIRY_NOT_FOUND = (404, "문의를 찾을 수 없습니다.")
    INQUIRY_CLOSED = (409, "종료된 문의입니다. 문의를 다시 열어 대화를 이어가 주세요.")
    INQUIRY_INVALID_STATE = (409, "현재 문의 상태에서는 처리할 수 없는 요청입니다.")
    AI_UNAVAILABLE = (503, "지금은 AI 답변을 드리기 어렵습니다. 입력하신 내용은 저장되었으니 담당자 연결을 이용해 주세요.")

