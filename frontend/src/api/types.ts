/**
 * API 계약 타입 (제안).
 * 백엔드(A)가 확정한 값에 맞춰 이 파일과 어댑터(auth.ts, consult.ts)만 고친다.
 */

/** 사용자 역할: 문의자 / 담당자(IT 운영) / 관리자 */
export type Role = 'user' | 'staff' | 'admin'

/** 서비스 계정 상태 (SRS 4.6). 승인 대기·이용 제한 계정은 로그인할 수 없다. */
export type AccountStatus = '승인' | '승인 대기' | '이용 제한'

export interface User {
  /** 사번 (예: HS1001) */
  id: string
  name: string
  /** 소속 부서 */
  dept: string
  role: Role
  status: AccountStatus
}

/** 성공 응답 */
export interface ApiOk<T> {
  ok: true
  data: T
}

/** 실패 응답. message 는 사용자에게 그대로 보여 줄 수 있는 한국어 문구여야 한다. */
export interface ApiFail {
  ok: false
  error: { code: string; message: string }
}

export type ApiResult<T> = ApiOk<T> | ApiFail

export interface LoginRequest {
  /** 사번 */
  employeeId: string
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
  /** 근거 Guide 출처. 예: "IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3.2" */
  source?: string
}

/** 성공 응답을 만드는 도우미 */
export const ok = <T,>(data: T): ApiOk<T> => ({ ok: true, data })

/** 실패 응답을 만드는 도우미 */
export const fail = (code: string, message: string): ApiFail => ({ ok: false, error: { code, message } })
