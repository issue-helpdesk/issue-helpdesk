/**
 * API 계약 타입 (제안).
 * 백엔드(A)가 확정한 값에 맞춰 이 파일과 어댑터(auth.ts, consult.ts)만 고친다.
 */

/** 사용자 역할: 문의자 / 담당자(IT 운영) / 관리자 */
export type Role = 'user' | 'staff' | 'admin'

/**
 * 서비스 계정 상태 (SRS 4.6). 잠김·이용 제한 계정은 로그인할 수 없다.
 * DB 값(`06 테이블 설계서`)과의 대응: 정상=ACTIVE, 잠김=LOCKED, 이용 제한=INACTIVE
 */
export type AccountStatus = '정상' | '잠김' | '이용 제한'

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

/** FAQ 한 건 (제안 기능, PRD 4.16 · SRS FAQ-01). 열람이 허용된 Guide를 출처로 한다. */
export interface Faq {
  id: string
  /** 분류 코드 (ACC · ACS · NET · SW · HW · SYS · SEC) */
  category: string
  question: string
  answer: string
  /** 근거 Guide 출처. 예: "IT-NET-001 VPN 접속 장애 대응 가이드 v2 · 3.1" */
  source: string
}

/** 문의 진행 표시 상태. 사이드바 최근 문의와 문의 내역에 쓴다. (PRD 4.8 화면 표시 상태) */
export type InquiryStateKind = 'progress' | 'assigned' | 'received' | 'resolved' | 'ai' | 'warn'

/** 문의 한 건 요약 (사이드바 최근 문의) */
export interface InquirySummary {
  id: string
  title: string
  /** 화면에 보일 상태 이름 (예: 처리 중, 해결 완료, AI 해결, 미확인) */
  stateLabel: string
  stateKind: InquiryStateKind
  /** 확인하지 않은 담당자 답변 수. 0 이면 표시하지 않는다. */
  unread: number
  /** 최근 활동 (예: 어제, 3일 전) */
  when: string
}

/** 성공 응답을 만드는 도우미 */
export const ok = <T,>(data: T): ApiOk<T> => ({ ok: true, data })

/** 실패 응답을 만드는 도우미 */
export const fail = (code: string, message: string): ApiFail => ({ ok: false, error: { code, message } })
