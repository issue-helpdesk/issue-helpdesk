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

/** 임시 비밀번호 상태를 시연하는 계정(EMP-1300)의 임시 비밀번호 */
export const MOCK_TEMP_PASSWORD = 'Tmp#Demo1234'

/** 연속 로그인 실패가 이 횟수에 이르면 계정이 잠긴다. */
export const MAX_FAILS = 5

/** 잠금이 유지되는 시간(분). 이후 로그인 시도 때 자동으로 풀린다. */
export const LOCK_MINUTES = 10

/** 계정 초기 상태 (reset 할 때 이 값으로 되돌린다) */
const SEED: User[] = [
  { id: 1, employeeNo: 'EMP-1001', name: '이태윤', departmentId: 11, departmentName: '개발1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 2, employeeNo: 'EMP-1004', name: '성민경', departmentId: 21, departmentName: '네트워크팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 3, employeeNo: 'EMP-1178', name: '이건우', departmentId: 20, departmentName: '서비스데스크', serviceRole: 'ADMIN', accountStatus: 'ACTIVE' },
  { id: 4, employeeNo: 'EMP-1003', name: '김민지', departmentId: 51, departmentName: '인사팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 5, employeeNo: 'EMP-1082', name: '공은서', departmentId: 41, departmentName: '디자인팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 6, employeeNo: 'EMP-1005', name: '최하준', departmentId: 32, departmentName: '영업2팀', serviceRole: 'EMPLOYEE', accountStatus: 'INACTIVE' },
  { id: 7, employeeNo: 'EMP-1037', name: '황지윤', departmentId: 31, departmentName: '영업1팀', serviceRole: 'EMPLOYEE', accountStatus: 'LOCKED' },
  { id: 8, employeeNo: 'EMP-1300', name: '최지혜', departmentId: 12, departmentName: '개발2팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  // 관리자 계정 관리 화면(목록·필터·페이지)을 보여 주려고 더한 가상 계정. 서버 시드의 실제 직원이다 (tests/mockAccounts.test.ts 가 확인한다)
  { id: 9, employeeNo: 'EMP-1049', name: '정서현', departmentId: 21, departmentName: '네트워크팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 10, employeeNo: 'EMP-1156', name: '황진혁', departmentId: 21, departmentName: '네트워크팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 11, employeeNo: 'EMP-1064', name: '강지호', departmentId: 25, departmentName: '엔드포인트지원팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 12, employeeNo: 'EMP-1036', name: '정수호', departmentId: 24, departmentName: '업무시스템팀', serviceRole: 'AGENT', accountStatus: 'ACTIVE' },
  { id: 13, employeeNo: 'EMP-1270', name: '오한결', departmentId: 22, departmentName: '정보보안팀', serviceRole: 'ADMIN', accountStatus: 'ACTIVE' },
  { id: 14, employeeNo: 'EMP-1009', name: '도재훈', departmentId: 61, departmentName: '연구소', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 15, employeeNo: 'EMP-1007', name: '정영호', departmentId: 62, departmentName: '생산관리팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 16, employeeNo: 'EMP-1039', name: '최우진', departmentId: 63, departmentName: '품질관리팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 17, employeeNo: 'EMP-1018', name: '허수진', departmentId: 64, departmentName: '고객지원팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 18, employeeNo: 'EMP-1016', name: '노현준', departmentId: 33, departmentName: '마케팅팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 19, employeeNo: 'EMP-1002', name: '원상우', departmentId: 53, departmentName: '경영기획팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 20, employeeNo: 'EMP-1066', name: '신미진', departmentId: 55, departmentName: '구매팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 21, employeeNo: 'EMP-1067', name: '허혜진', departmentId: 54, departmentName: '법무팀', serviceRole: 'EMPLOYEE', accountStatus: 'INACTIVE' },
  { id: 22, employeeNo: 'EMP-1024', name: '김성훈', departmentId: 52, departmentName: '재무팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 23, employeeNo: 'EMP-1033', name: '정시은', departmentId: 51, departmentName: '인사팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 24, employeeNo: 'EMP-1013', name: '박세희', departmentId: 11, departmentName: '개발1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 25, employeeNo: 'EMP-1006', name: '정서진', departmentId: 12, departmentName: '개발2팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 26, employeeNo: 'EMP-1088', name: '명종현', departmentId: 41, departmentName: '디자인팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 27, employeeNo: 'EMP-1081', name: '배예린', departmentId: 31, departmentName: '영업1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 28, employeeNo: 'EMP-1014', name: '전미진', departmentId: 32, departmentName: '영업2팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 29, employeeNo: 'EMP-1019', name: '허주원', departmentId: 61, departmentName: '연구소', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
  { id: 30, employeeNo: 'EMP-1030', name: '한민재', departmentId: 11, departmentName: '개발1팀', serviceRole: 'EMPLOYEE', accountStatus: 'ACTIVE' },
]

/** 현재 가상 계정 목록. 로그인 실패·잠금에 따라 status 가 바뀐다. */
export const MOCK_ACCOUNTS: User[] = []

/** 사번별 현재 비밀번호. 없으면 공통 비밀번호(MOCK_PASSWORD)이다. */
const passwords = new Map<string, string>()
/** 임시 비밀번호 상태인 사번 (새 비밀번호를 정하기 전까지 다른 기능을 쓸 수 없다) */
const tempPw = new Set<string>()

/** 사번별 연속 실패 횟수 */
const fails = new Map<string, number>()
/** 사번별 잠금이 풀리는 시각(밀리초) */
const lockedUntil = new Map<string, number>()

/** 가상 계정과 잠금·실패 기록을 처음 상태로 되돌린다. (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetMockState() {
  MOCK_ACCOUNTS.splice(0, MOCK_ACCOUNTS.length, ...SEED.map((a) => ({ ...a })))
  fails.clear()
  lockedUntil.clear()
  passwords.clear()
  tempPw.clear()
  passwords.set('EMP-1300', MOCK_TEMP_PASSWORD)
  tempPw.add('EMP-1300')
  // 시연용으로 처음부터 잠겨 있는 계정은 잠금 시간이 남아 있게 한다
  lockedUntil.set('EMP-1037', Date.now() + LOCK_MINUTES * 60_000)
}
resetMockState()

/** 관리자가 계정을 만들거나 임시 비밀번호를 다시 발급했을 때: 임시 비밀번호 상태로 둔다 */
export function setTempPassword(id: string, pw: string) {
  passwords.set(id, pw)
  tempPw.add(id)
}

/** 사번의 현재 비밀번호 */
export const passwordOf = (id: string) => passwords.get(id) ?? MOCK_PASSWORD

/** 임시 비밀번호 상태인지 */
export const isTempPassword = (id: string) => tempPw.has(id)

/** 비밀번호를 바꾸면 임시 비밀번호 상태도 끝난다. */
export function setPassword(id: string, pw: string) {
  passwords.set(id, pw)
  tempPw.delete(id)
}

/** 로그인 응답에 담아 줄 사용자: 임시 비밀번호 상태와 비밀번호 변경 후 날수를 붙인 사본 (저장된 계정은 건드리지 않는다) */
export function sessionUser(acc: User): User {
  return { ...acc, passwordChangeRequired: tempPw.has(acc.employeeNo), passwordChangedDaysAgo: tempPw.has(acc.employeeNo) ? 0 : 38 }
}

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
  { id: 'EMP-1004', label: '담당자' },
  { id: 'EMP-1178', label: '관리자' },
  { id: 'EMP-1300', label: '임시 비밀번호 계정' },
  { id: 'EMP-1005', label: '이용 제한 계정' },
  { id: 'EMP-1037', label: '잠김 계정' },
]
