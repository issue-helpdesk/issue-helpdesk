/**
 * 관리자 계정 관리 계약 타입. (docs/api/01.인증_사용자.md US-01~05, 05.기준정보_운영.md RF-05)
 * 이름과 값은 서버 응답을 그대로 따르고, 한글 표시는 화면에서만 붙인다.
 */
import type { AccountStatus, ServiceRole } from './types'

export interface DepartmentRef {
  id: number
  name: string
}

/** 부서 목록의 한 칸 (RF-05) */
export interface Department {
  id: number
  name: string
  parentId: number | null
  isActive: boolean
}

/** 목록·수정·생성 응답의 사용자 (US-01 UserSummary, 나머지는 User 의 일부) */
export interface UserSummary {
  id: number
  employeeNo: string
  name: string
  email: string
  department: DepartmentRef | null
  position: string | null
  serviceRole: ServiceRole
  accountStatus: AccountStatus
  lastLoginAt: string | null
}

/** US-01 목록 조건. sort 는 `필드,방향` 이고 서버는 name·employeeNo·createdAt·lastLoginAt 만 받는다. */
export interface UserListQuery {
  page?: number
  size?: number
  sort?: string
  q?: string
  departmentId?: number
  serviceRole?: ServiceRole[]
  accountStatus?: AccountStatus[]
}

/** US-02 계정 생성 */
export interface UserCreateRequest {
  employeeNo: string
  name: string
  email: string
  departmentId?: number | null
  position?: string | null
  serviceRole: ServiceRole
  slackUserId?: string | null
}

export interface UserCreateResult {
  user: UserSummary
  /** 임시 비밀번호. 이 응답에서만 볼 수 있다 */
  temporaryPassword: string
}

/** US-04 정보·상태 변경: 보낸 필드만 바꾼다. 역할·상태를 바꿀 때는 reason 이 필수이다. LOCKED 는 서버만 설정한다. */
export interface UserUpdateRequest {
  name?: string
  email?: string
  departmentId?: number | null
  position?: string | null
  serviceRole?: ServiceRole
  accountStatus?: 'ACTIVE' | 'INACTIVE'
  slackUserId?: string | null
  reason?: string
}

/** 이 화면에서 처리한 일의 기록 (서버에 이력 조회 API 가 없어 이 화면에서 한 일만 보여 준다) */
export type HistKind = '이용 제한' | '제한 해제' | '잠금 해제' | '계정 추가' | '계정 수정' | '임시 비밀번호 재발급'

export interface AccountHistoryItem {
  id: number
  at: string
  who: string
  /** 예: `EMP-1001 · 김서연` */
  target: string
  what: HistKind
  why: string
}
