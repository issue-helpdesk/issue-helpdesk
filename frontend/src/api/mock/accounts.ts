/**
 * 시연용 가상 계정 (design/ITssue-Prototype.html 과 같은 데이터).
 * 실제 사용자 정보가 아니며, 비밀번호 'demo' 는 시연용 공개 값이다.
 * 실제 API 로 전환(VITE_USE_MOCK=false)하면 쓰이지 않는다.
 *
 * 계정 상태는 ACTIVE(정상) · LOCKED(잠김) · INACTIVE(이용 제한) 세 가지이다. (승인 대기는 없다: 회원가입 없이 관리자가 계정을 만들어 제공한다)
 * 잠김은 로그인 5회 실패 시 걸리고 10분 후 자동으로 풀린다.
 */
import type { User } from '../types'

/** 모든 가상 계정의 공통 비밀번호 */
export const MOCK_PASSWORD = 'demo'

/** 연속 로그인 실패가 이 횟수에 이르면 계정이 잠긴다. */
export const MAX_FAILS = 5

/** 잠금이 유지되는 시간(분). 이후 로그인 시도 때 자동으로 풀린다. */
export const LOCK_MINUTES = 10

/** 계정 초기 상태 (reset 할 때 이 값으로 되돌린다) */
const SEED: User[] = [
  { id: 1, employeeNo: 'EMP-1001', name: '김서연', departmentId: 11, departmentName: '개발1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 2, employeeNo: 'EMP-1107', name: '김담당', departmentId: 21, departmentName: '네트워크팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 3, employeeNo: 'EMP-0912', name: '최관리', departmentId: 20, departmentName: '서비스데스크', serviceRole: 'ADMIN', accountStatus: 'ACTIVE' },
  { id: 4, employeeNo: 'EMP-1003', name: '박민수', departmentId: 31, departmentName: '영업1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 5, employeeNo: 'EMP-1004', name: '이지은', departmentId: 41, departmentName: '디자인팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 6, employeeNo: 'EMP-1488', name: '박과장', departmentId: 32, departmentName: '영업2팀', serviceRole: 'EMPLOYEE', accountStatus: 'INACTIVE' },
  { id: 7, employeeNo: 'EMP-1530', name: '정과장', departmentId: 31, departmentName: '영업1팀', serviceRole: 'EMPLOYEE', accountStatus: 'LOCKED' },
]

/** 현재 가상 계정 목록. 로그인 실패·잠금에 따라 status 가 바뀐다. */
export const MOCK_ACCOUNTS: User[] = []

/** 사번별 연속 실패 횟수 */
const fails = new Map<string, number>()
/** 사번별 잠금이 풀리는 시각(밀리초) */
const lockedUntil = new Map<string, number>()

/** 가상 계정과 잠금·실패 기록을 처음 상태로 되돌린다. (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetMockState() {
  MOCK_ACCOUNTS.splice(0, MOCK_ACCOUNTS.length, ...SEED.map((a) => ({ ...a })))
  fails.clear()
  lockedUntil.clear()
  // 시연용으로 처음부터 잠겨 있는 계정은 잠금 시간이 남아 있게 한다
  lockedUntil.set('EMP-1530', Date.now() + LOCK_MINUTES * 60_000)
}
resetMockState()

/** 연속 실패를 한 번 기록하고 누적 횟수를 돌려준다. */
export function addFail(id: string): number {
  const n = (fails.get(id) ?? 0) + 1
  fails.set(id, n)
  return n
}

/** 로그인에 성공하면 연속 실패 기록을 지운다. */
export function clearFails(id: string) {
  fails.delete(id)
}

/** 계정을 잠그고 10분 뒤에 풀리도록 시각을 기록한다. */
export function lockAccount(user: User) {
  user.accountStatus = 'LOCKED'
  lockedUntil.set(user.employeeNo, Date.now() + LOCK_MINUTES * 60_000)
  fails.delete(user.employeeNo)
}

/** 잠금을 풀고 정상 상태로 되돌린다. */
export function unlockAccount(user: User) {
  user.accountStatus = 'ACTIVE'
  lockedUntil.delete(user.employeeNo)
  fails.delete(user.employeeNo)
}

/** 잠금이 풀릴 때까지 남은 시간(분, 올림). 잠겨 있지 않으면 0 */
export function minutesLeft(id: string): number {
  const until = lockedUntil.get(id)
  return until ? Math.max(1, Math.ceil((until - Date.now()) / 60_000)) : 0
}

/** 잠금이 풀리는 시각 (ISO 8601). 잠겨 있지 않으면 undefined */
export function lockedUntilIso(id: string): string | undefined {
  const until = lockedUntil.get(id)
  return until ? new Date(until).toISOString() : undefined
}

/** 잠금 시간이 지났는지 */
export function lockExpired(id: string): boolean {
  const until = lockedUntil.get(id)
  return until === undefined || Date.now() >= until
}

/** 시연·테스트용: 10분이 지난 것처럼 잠금 시각을 과거로 당긴다. */
export function expireLockForDemo(id: string) {
  lockedUntil.set(id, Date.now() - 1)
}

/** 로그인 화면의 "시연용 바로 로그인" 버튼 목록 */
export const MOCK_QUICK_LOGINS: { id: string; label: string }[] = [
  { id: 'EMP-1001', label: '문의자' },
  { id: 'EMP-1107', label: '담당자' },
  { id: 'EMP-0912', label: '관리자' },
  { id: 'EMP-1488', label: '이용 제한 계정' },
  { id: 'EMP-1530', label: '잠김 계정' },
]
