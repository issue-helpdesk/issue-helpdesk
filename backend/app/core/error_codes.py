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
    SERVICE_UNAVAILABLE = (503, "서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.")
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

    # 접수 (5.6)
    DRAFT_NOT_FOUND = (404, "접수 초안을 찾을 수 없습니다.")
    DRAFT_ALREADY_EXISTS = (409, "작성 중인 접수 초안이 있습니다.")
    DRAFT_NOT_EDITABLE = (409, "이미 접수되었거나 취소된 초안입니다.")
    DRAFT_RECONFIRM_REQUIRED = (409, "초안 내용이 바뀌었습니다. 변경된 내용을 확인한 뒤 다시 접수해 주세요.")
    TICKET_NOT_FOUND = (404, "접수 건을 찾을 수 없습니다.")
    TICKET_INVALID_TRANSITION = (409, "현재 처리 상태에서 변경할 수 없는 상태입니다.")
    TICKET_NOT_SYNCED = (409, "Jira 연동이 끝난 뒤에 처리 상태를 변경할 수 있습니다.")
    TICKET_RESOLUTION_NOTE_REQUIRED = (422, "처리 완료로 변경하려면 처리 결과를 입력해 주세요.")
    INTEGRATION_JOB_IN_PROGRESS = (409, "이미 연동 작업이 진행 중입니다.")
    INTEGRATION_RETRY_NOT_ALLOWED = (409, "현재 작업 상태에서는 재처리할 수 없습니다.")
    INTEGRATION_ALREADY_SYNCED = (409, "이미 Jira에 연동된 접수입니다.")
    WEBHOOK_SIGNATURE_INVALID = (401, "웹훅 인증에 실패했습니다.")
    ASSIGNMENT_REASON_REQUIRED = (422, "담당자를 지정·변경할 때는 사유를 입력해 주세요.")
    ASSIGNEE_NOT_ASSIGNABLE = (422, "배정할 수 없는 담당자입니다. 그룹 소속·배정 가능 여부·Jira 계정을 확인해 주세요.")
    TICKET_SAVE_FAILED = (500, "접수를 저장하지 못했습니다. 작성하신 내용은 보존되어 있으니 잠시 후 다시 시도하거나 "
                               "IT 헬프데스크(내선 1000)·그룹웨어 IT 요청 메뉴를 이용해 주세요.")

    # 문서 (DC)
    DOCUMENT_NOT_FOUND = (404, "문서를 찾을 수 없습니다.")
    DOCUMENT_CODE_DUPLICATE = (409, "이미 등록된 문서 번호입니다.")
    DOCUMENT_VERSION_NOT_FOUND = (404, "문서 버전을 찾을 수 없습니다.")
    DOCUMENT_VERSION_DUPLICATE = (409, "이미 등록된 버전입니다.")
    DOCUMENT_VERSION_NOT_READY = (409, "검색 준비가 끝난 버전만 현행으로 바꿀 수 있습니다.")
    DOCUMENT_FILE_FORMAT_UNSUPPORTED = (415, "PDF·DOCX·PPTX·MD·TXT 파일만 등록할 수 있습니다.")
    DOCUMENT_FILE_TOO_LARGE = (413, "파일 크기가 너무 큽니다.")
    DOCUMENT_FILE_DUPLICATE = (409, "같은 파일이 이미 등록되어 있습니다.")
    DOCUMENT_CONTENT_UNAVAILABLE = (409, "가이드 본문을 읽을 수 없습니다. 파일을 다시 올려 주세요.")
    DOCUMENT_VERSION_NOT_RETRYABLE =(409, "적재에 실패한 버전만 다시 시도할 수 있습니다.")
    DOCUMENT_VERSION_HAS_REJECTED_CLUSTER = (409, "거절한 해결 사례가 들어 있는 버전은 현행으로 바꿀 수 없습니다. 남은 해결 사례가 있으면 다시 등록해 주세요.")
    DOCUMENT_VERSION_BASE_CHANGED = (409, "초안을 만든 뒤 현행 버전이 바뀌어 이 버전을 현행으로 바꿀 수 없습니다. 해결 사례를 다시 맞춘 뒤 새로 등록해 주세요.")
    DOCUMENT_VERSION_OUTDATED = (409, "지금 현행에 반영된 해결 사례가 이 버전에는 없습니다. 현행을 기준으로 고쳐 새 버전으로 올려 주세요.")
    DOCUMENT_VERSION_ORPHANED = (409, "연결된 해결 사례가 없는 초안 버전은 현행으로 바꿀 수 없습니다.")
    DOCUMENT_MANUAL_TRANSFER_FIXED = (422, "담당자용 매뉴얼의 외부 전송 정책은 전송 금지로 고정됩니다. 항목별 전송은 허용 목록으로 관리합니다.")

    # 해결 사례 가이드화 (GC)
    GUIDE_CLUSTER_NOT_FOUND = (404, "해결 사례 묶음을 찾을 수 없습니다.")
    GUIDE_CLUSTER_NOT_REVIEWING = (409, "검토 중인 묶음만 처리할 수 있습니다.")
    GUIDE_CLUSTER_REGISTERED = (409, "등록한 묶음은 현행 전환으로 반영됩니다. 가이드 관리에서 현행으로 바꿔 주세요.")
    GUIDE_CLUSTER_DRAFT_CONFLICT = (409, "다른 관리자가 먼저 초안을 고쳤습니다. 최신 초안을 다시 불러온 뒤 고쳐 주세요.")
    GUIDE_CLUSTER_DRAFT_LOCKED = (409, "등록한 초안은 고칠 수 없습니다.")
    GUIDE_CLUSTER_NO_DRAFT = (409, "초안이 없는 묶음입니다. 매뉴얼 후보는 매뉴얼에 직접 반영한 뒤 반영 표시해 주세요.")
    GUIDE_CLUSTER_NOT_REGISTRABLE = (409, "이 묶음에는 할 수 없는 작업입니다. 문제 내용을 확인해 주세요.")
    GUIDE_CLUSTER_BASE_CHANGED = (409, "초안을 만든 뒤 현행 버전이 바뀌어 등록할 수 없습니다. 다시 맞춘 뒤 등록해 주세요.")
    GUIDE_CLUSTER_CONFLICT_UNRESOLVED = (409, "현행에서 바뀐 항목과 초안이 충돌합니다. 초안을 고쳐 저장한 뒤 등록해 주세요.")
    GUIDE_CLUSTER_REBASE_FAILED = (409, "초안을 현행에 다시 맞추지 못했습니다. 문제 내용을 확인해 주세요.")
    GUIDE_CLUSTER_TARGET_INVALID = (409, "이 문서에는 넣을 수 없습니다. 문제 내용을 확인해 주세요.")
    GUIDE_CLUSTER_TARGET_UNCHANGED = (409, "이미 이 위치에 넣도록 되어 있습니다.")
    GUIDE_CLUSTER_ASSEMBLE_FAILED = (409, "초안을 가이드에 합치지 못했습니다. 문제 내용을 확인해 주세요.")

    # 화면 알림
    NOTIFICATION_NOT_FOUND = (404, "알림을 찾을 수 없습니다.")

    # 연차·반차 일정 (5.6)
    TIME_OFF_NOT_FOUND = (404, "연차·반차 일정을 찾을 수 없습니다.")
    TIME_OFF_OVERLAP = (409, "같은 기간에 이미 등록된 연차·반차 일정이 있습니다.")

    # 가이드 그림
    GUIDE_IMAGE_NOT_FOUND = (404, "그림을 찾을 수 없습니다.")

    # FAQ (5.6)
    FAQ_NOT_FOUND = (404, "FAQ를 찾을 수 없습니다.")
    FAQ_CODE_DUPLICATE = (409, "이미 등록된 FAQ 번호입니다.")
    FAQ_SOURCE_NOT_PUBLIC = (409, "공개 가능한 현행 출처를 확인한 뒤 게시해 주세요.")

    # 보안·감사 알림 (1C)
    SECURITY_ALERT_NOT_FOUND = (404, "보안 알림을 찾을 수 없습니다.")
    SECURITY_ALERT_NO_ORIGINAL = (409, "열람할 문의 내용이 없는 알림입니다.")
    SECURITY_ALERT_INVALID_STATE = (409, "현재 알림 상태에서는 처리할 수 없습니다.")
