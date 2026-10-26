/**
 * API 계약 타입.
 * 이름과 값은 06 테이블 설계서의 DB 컬럼·코드 값을 따르고, JSON 키만 camelCase 로 쓴다. (docs/07.API_계약서.md)
 * 한글 표시는 catalog.ts 의 라벨표에서만 붙인다.
 */
import type { CategoryCode, GuideSource } from './chatTypes'

/** 서비스 권한 (users.service_role): 문의자 / 담당자(IT 운영) / 관리자 */
export type ServiceRole = 'EMPLOYEE' | 'AGENT' | 'ADMIN'

/** 서비스 계정 상태 (users.account_status, SRS 4.6). 잠김·이용 제한 계정은 로그인할 수 없다. */
export type AccountStatus = 'ACTIVE' | 'LOCKED' | 'INACTIVE'

export interface User {
  /** 사용자 ID (users.id) */
  id: number
  /** 사번 (users.employee_no, 예: EMP-1001). 로그인 ID 로 쓴다. */
  employeeNo: string
  name: string
  departmentId: number | null
  /** 소속 부서 이름 (departments.name) */
  departmentName: string
  serviceRole: ServiceRole
  accountStatus: AccountStatus
}

/** 성공 응답 */
export interface ApiOk<T> {
  ok: true
  data: T
}

/** 실패 응답. message 는 사용자에게 그대로 보여 줄 수 있는 한국어 문구여야 한다. */
export interface ApiFail {
  ok: false
  error: {
    code: string
    message: string
    /** ACCOUNT_LOCKED 일 때 잠금이 풀리는 시각 (ISO 8601) */
    lockedUntil?: string
  }
}

export type ApiResult<T> = ApiOk<T> | ApiFail

export interface LoginRequest {
  /** 사번 */
  employeeNo: string
  password: string
}

export interface LoginData {
  /** JWT. 이후 요청의 Authorization: Bearer 헤더에 넣는다. */
  accessToken: string
  user: User
}

/** 로그인 전 상담 응답 (제안 기능, PRD 4.1 · SRS PRE-01) */
export interface ConsultReply {
  /** 문단 목록. **굵게** 표시를 지원한다. */
  paragraphs: string[]
  /** 근거 Guide 출처. 문의 화면 답변과 같은 형태 */
  sources: GuideSource[]
  /** 답변에 붙는 바로가기 버튼 (예: 비밀번호 초기화 창 열기). 없으면 버튼을 그리지 않는다. */
  ctas?: ConsultCta[]
}

/** 로그인 전 상담 답변의 바로가기 */
export interface ConsultCta {
  label: string
  /** 화면이 알고 있는 동작 이름. forgot=비밀번호 초기화 창 */
  action: 'forgot'
}

/** FAQ 한 건 (제안 기능, PRD 4.16 · SRS FAQ-01). 열람이 허용된 Guide를 출처로 한다. */
export interface Faq {
  /** 문서 코드 (예: FAQ-001) */
  id: string
  categoryCode: CategoryCode
  question: string
  answer: string
  /** 근거 Guide 출처 */
  sources: GuideSource[]
}

/**
 * 문의 진행 표시 상태. 사이드바 최근 문의와 문의 내역에 쓴다. (PRD 4.8 화면 표시 상태)
 * needs_reply · reassigned · awaiting_confirm 은 SRS 4.x 의 보조 상태 값을 그대로 쓴다.
 */
export type InquiryStateKind = 'progress' | 'assigned' | 'received' | 'resolved' | 'ai' | 'warn' | 'needs_reply' | 'reassigned' | 'awaiting_confirm'

/**
 * 화면 표시 상태 (API 02 1.2 `displayStatus`). 문의 상태와, 접수 건은 Ticket 업무 상태를 합쳐 정한다.
 * 문의 내역의 상태 분류는 이 값을 묶어서 만든다.
 */
export type DisplayStatus = 'in_progress' | 'ai_resolved' | 'unconfirmed' | 'unresolved' | 'received' | 'assigned' | 'progress' | 'awaiting_confirm' | 'resolved'

/** 문의 한 건 요약 (사이드바 최근 문의, 문의 내역) */
export interface InquirySummary {
  id: number
  title: string
  displayStatus: DisplayStatus
  /** 분류. 아직 판단하지 못했으면 null */
  categoryCode: CategoryCode | null
  /** 접수번호·Jira 번호. 접수 전에는 null */
  receiptNo: string | null
  jiraKey: string | null
  /** 문의를 시작한 시각 (ISO 8601) */
  createdAt: string
  /** 화면에 보일 상태 이름 (예: 처리 중, 해결 완료, AI 해결, 미확인) */
  stateLabel: string
  stateKind: InquiryStateKind
  /** 확인하지 않은 담당자 답변 수. 0 이면 표시하지 않는다. */
  unread: number
  /** 최근 활동 시각 (ISO 8601). '어제' 같은 표시는 화면에서 계산한다. */
  updatedAt: string
}

/** 성공 응답을 만드는 도우미 */
export const ok = <T,>(data: T): ApiOk<T> => ({ ok: true, data })

/** 실패 응답을 만드는 도우미 */
export const fail = (code: string, message: string, extra?: { lockedUntil?: string }): ApiFail => ({ ok: false, error: { code, message, ...extra } })
