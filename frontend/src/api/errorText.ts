/**
 * 서버 오류 코드별 화면 문구 사전 (서버 모드).
 *
 * 서버는 오류마다 `{ code, message, details }` 를 준다. message 는 백엔드(error_codes.py)의 기본 문구라서 말투·용어가 화면과 다르고
 * ("Jira", "…습니다") 상황을 가리지 못한다. 그래서 화면에 보이는 문구는 이 사전에서 코드로 정한다 (core/apiClient.ts 가 실패 응답을 만들 때 적용).
 *
 * - 해요체, 실패한 대상과 다음 행동을 알린다. 연락처는 서버 문구와 같은 "IT 헬프데스크(내선 1000)"로 통일한다.
 * - 서버가 details 로 준 값(파일 크기 제한, 겹친 문서 번호·버전 등)은 문구에 끼워 쓴다. 값이 없으면 숫자 없는 문구를 쓴다.
 * - 사전에 없는 코드는 서버 문구를 그대로 쓰되 "Jira" 는 "ITSM" 으로 바꾼다.
 * - REQUEST_IN_PROGRESS·IDEMPOTENCY_KEY_REUSED 는 서버가 보내지 않으므로(소스에 없음) 만들지 않았다. 서버 간 호출인 웹훅 서명 오류도 화면 문구가 없다.
 * - 화면이 코드를 보고 문구 대신 동작을 정하는 곳(로그인 폼, 초안 충돌 때의 다시 읽기 등)은 각 화면에 그대로 있고, 거기서 쓰는 글도 이 사전에서 가져온다.
 */
import { HELPDESK } from '../core/config'
import type { ErrorDetail } from './types'

type Make = (details?: ErrorDetail[]) => string

const detail = (details: ErrorDetail[] | undefined, reason: string) => details?.find((d) => d.reason === reason)
/** details.value 는 글자일 수도, 서버가 준 객체일 수도 있다 */
const asObject = (v: unknown): Record<string, unknown> | null => (v && typeof v === 'object' ? (v as Record<string, unknown>) : null)

const TEXT: Record<string, string | Make> = {
  // 공통
  UNAUTHORIZED: '로그인이 필요해요. 다시 로그인해 주세요.',
  TOKEN_EXPIRED: '로그인이 만료되었어요. 다시 로그인해 주세요.',
  FORBIDDEN: '이 작업을 할 권한이 없어요.',
  NOT_FOUND: '요청한 정보를 찾을 수 없어요. 목록을 다시 불러와 주세요.',
  VALIDATION_ERROR: '입력한 내용을 확인해 주세요.',
  INVALID_REQUEST: '조회 조건을 확인한 뒤 다시 시도해 주세요.',
  METHOD_NOT_ALLOWED: `요청을 처리하지 못했어요. 문제가 계속되면 ${HELPDESK}로 문의해 주세요.`,
  TOO_MANY_REQUESTS: '요청이 잠시 제한됐어요. 잠시 후 다시 시도해 주세요.',
  INTERNAL_ERROR: '처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.',
  SERVICE_UNAVAILABLE: '연동 시스템의 처리 결과를 확인하지 못했어요. 최신 상태를 확인한 뒤 다시 시도해 주세요.',
  // 인증·계정 (로그인 폼의 문구는 api/auth.ts 가 잠금 해제 시각 등을 넣어 따로 만든다)
  AUTH_INVALID_CREDENTIALS: '사번 또는 비밀번호를 확인해 주세요.',
  AUTH_ACCOUNT_INACTIVE: `이용이 제한된 계정이에요. ${HELPDESK}로 문의해 주세요.`,
  AUTH_PASSWORD_CHANGE_REQUIRED: '비밀번호를 변경한 뒤 이용할 수 있어요.',
  AUTH_CURRENT_PASSWORD_MISMATCH: '현재 비밀번호를 확인해 주세요.',
  AUTH_PASSWORD_POLICY_VIOLATION: (d) => (d?.[0]?.message ? `새 비밀번호가 변경 규칙에 맞지 않아요. ${d[0].message}` : '새 비밀번호가 변경 규칙에 맞지 않아요.'),
  AUTH_REFRESH_TOKEN_INVALID: '로그인이 만료되었어요. 다시 로그인해 주세요.',
  USER_NOT_FOUND: '사용자를 찾을 수 없어요. 목록을 다시 불러온 뒤 확인해 주세요.',
  USER_EMPLOYEE_NO_DUPLICATE: '이미 등록된 사번이에요.',
  USER_EMAIL_DUPLICATE: '이미 등록된 이메일이에요.',
  USER_SELF_CHANGE_NOT_ALLOWED: '내 계정의 권한과 상태는 바꿀 수 없어요.',
  USER_STATUS_REASON_REQUIRED: '변경 사유를 입력해 주세요.',
  // 문의·대화
  INQUIRY_NOT_FOUND: '문의를 찾을 수 없어요. 문의 내역에서 다른 문의를 확인하거나 새 문의를 시작해 주세요.',
  INQUIRY_CLOSED: '이미 종료된 문의예요. 새 문의로 시작해 주세요.',
  INQUIRY_INVALID_STATE: '문의 상태가 바뀌어 요청을 처리하지 못했어요. 최신 상태를 확인해 주세요.',
  AI_UNAVAILABLE: '지금은 AI 답변을 만들지 못했어요. 입력한 내용은 저장됐어요. 담당자에게 연결해 드릴까요?',
  // 접수 초안
  DRAFT_NOT_FOUND: '접수 초안을 찾을 수 없어요. 문의의 최신 상태를 확인해 주세요.',
  DRAFT_ALREADY_EXISTS: '기존 접수 초안을 불러왔어요.',
  DRAFT_NOT_EDITABLE: '접수 초안을 더 이상 수정할 수 없어요. 최신 상태를 확인해 주세요.',
  DRAFT_RECONFIRM_REQUIRED: '접수 초안 내용이 바뀌었어요. 변경된 내용을 확인한 뒤 다시 접수해 주세요.',
  // 티켓
  TICKET_NOT_FOUND: '티켓을 찾을 수 없어요. 목록을 다시 불러와 주세요.',
  TICKET_INVALID_TRANSITION: '티켓 상태가 바뀌어 요청한 작업을 진행할 수 없어요. 최신 상태를 확인해 주세요.',
  TICKET_NOT_SYNCED: '아직 ITSM 연동이 완료되지 않아 상태를 변경할 수 없어요.',
  TICKET_RESOLUTION_NOTE_REQUIRED: '처리 결과를 입력해 주세요.',
  TICKET_SAVE_FAILED: `접수를 저장하지 못했어요. 작성한 내용은 보존돼 있으니 잠시 후 다시 시도하거나 ${HELPDESK}·그룹웨어 IT 요청 메뉴를 이용해 주세요.`,
  // ITSM 연동·배정
  INTEGRATION_JOB_IN_PROGRESS: '연동 작업이 진행 중이에요. 최신 상태를 확인해 주세요.',
  INTEGRATION_RETRY_NOT_ALLOWED: '작업 상태가 바뀌어 다시 처리할 수 없어요. 최신 상태를 확인해 주세요.',
  INTEGRATION_ALREADY_SYNCED: '이미 ITSM에 연동된 티켓이에요. 최신 상태를 확인해 주세요.',
  ASSIGNMENT_REASON_REQUIRED: '담당자 지정·변경 사유를 입력해 주세요.',
  ASSIGNEE_NOT_ASSIGNABLE: '이 담당자에게 배정할 수 없어요. 소속 그룹·배정 가능 여부·ITSM 계정을 확인해 주세요.',
  // 가이드 문서
  DOCUMENT_NOT_FOUND: '가이드를 찾을 수 없어요. 목록을 다시 불러와 주세요.',
  DOCUMENT_CODE_DUPLICATE: '이미 등록된 문서 번호예요.',
  DOCUMENT_VERSION_NOT_FOUND: '가이드 버전을 찾을 수 없어요. 버전 목록을 다시 불러와 주세요.',
  DOCUMENT_VERSION_DUPLICATE: '이미 등록된 버전이에요. 버전을 확인해 주세요.',
  DOCUMENT_VERSION_NOT_READY: '검색 준비가 완료된 버전만 현행으로 전환할 수 있어요.',
  DOCUMENT_FILE_FORMAT_UNSUPPORTED: 'PDF·DOCX·PPTX·MD·TXT 파일만 등록할 수 있어요. 파일을 확인한 뒤 다시 선택해 주세요.',
  DOCUMENT_FILE_TOO_LARGE: (d) => {
    const max = detail(d, 'OUT_OF_RANGE')?.value
    return max ? `파일 크기가 등록 가능한 용량(${max})을 초과했어요. 더 작은 파일을 선택해 주세요.` : '파일 크기가 등록 가능한 용량을 초과했어요. 더 작은 파일을 선택해 주세요.'
  },
  DOCUMENT_FILE_DUPLICATE: (d) => {
    // 같은 파일이 있는 문서·버전: 서버가 value 에 문서 번호·버전을 준다 (열람할 수 있는 값만 온다)
    const v = asObject(detail(d, 'DUPLICATE')?.value as unknown)
    const where = v && typeof v.docCode === 'string' ? ` ${v.docCode}${typeof v.version === 'string' ? ` · ${v.version}` : ''}을(를) 확인해 주세요.` : ''
    return `같은 파일이 이미 등록되어 있어요.${where}`
  },
  DOCUMENT_VERSION_NOT_RETRYABLE: '검색 준비에 실패한 버전만 다시 시도할 수 있어요.',
  // 해결 사례 제안(AI 가이드 제안)이 들어 있는 버전을 현행으로 바꿀 때
  DOCUMENT_VERSION_HAS_REJECTED_CLUSTER: '거절한 제안이 포함된 버전은 현행으로 전환할 수 없어요. 거절한 항목을 뺀 새 버전을 올려 주세요.',
  DOCUMENT_VERSION_BASE_CHANGED: '제안을 만든 뒤 기준 가이드가 바뀌어서 현행으로 전환할 수 없어요. 최신 내용과 비교한 뒤 다시 등록해 주세요.',
  // 가이드 본문을 읽을 파일이 서버에 없거나 읽지 못한 경우 (관리자에게는 getGuideContent 가 파일 확인 안내로 바꾼다)
  DOCUMENT_CONTENT_UNAVAILABLE: `가이드 본문을 읽을 수 없어요. 문제가 계속되면 ${HELPDESK}로 문의해 주세요.`,
  GUIDE_IMAGE_NOT_FOUND: '이미지를 불러올 수 없어요.',
  // FAQ·알림·일정
  FAQ_NOT_FOUND: 'FAQ를 찾을 수 없어요. 목록을 다시 불러와 주세요.',
  FAQ_CODE_DUPLICATE: '이미 등록된 FAQ 번호예요.',
  FAQ_SOURCE_NOT_PUBLIC: '전 직원이 볼 수 있는 현행 가이드를 출처로 연결한 뒤 게시해 주세요.',
  NOTIFICATION_NOT_FOUND: '알림을 찾을 수 없어요. 목록을 다시 불러와 주세요.',
  TIME_OFF_NOT_FOUND: '부재 일정을 찾을 수 없어요. 일정을 다시 불러와 주세요.',
  TIME_OFF_OVERLAP: '선택한 기간에 이미 등록된 부재 일정이 있어요. 기간을 확인해 주세요.',
}

/** 화면이 코드로 만든 오류 (서버가 보내지 않는다) */
export const NETWORK_READ = '정보를 불러오지 못했어요. 연결 상태를 확인한 뒤 다시 불러와 주세요.'
/** 변경 요청이 연결 문제로 끊기면 서버가 이미 처리했을 수 있다: 실패로 단정하지 않고 처리 상태를 확인하게 한다 */
export const NETWORK_WRITE = '처리 결과를 확인하지 못했어요. 연결 상태를 확인한 뒤 처리 상태를 다시 확인해 주세요.'
export const BAD_RESPONSE_TEXT = '서버 응답을 확인하지 못했어요. 잠시 후 다시 확인해 주세요.'

/** 사전의 문구. 없으면 null */
export function errorText(code: string, details?: ErrorDetail[]): string | null {
  const t = TEXT[code]
  if (t === undefined) return null
  return typeof t === 'function' ? t(details) : t
}

/** 사전에 없는 코드의 서버 문구: 용어만 맞춘다 (Jira → ITSM) */
export const cleanServerText = (message: string) => message.replace(/\bJira\b/g, 'ITSM')

/** 서버 오류 하나의 화면 문구: 사전 → (없으면) 서버 문구 */
export function displayMessage(code: string, serverMessage: string, details?: ErrorDetail[]): string {
  return errorText(code, details) ?? cleanServerText(serverMessage)
}
