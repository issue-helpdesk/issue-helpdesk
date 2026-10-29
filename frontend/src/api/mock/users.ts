/**
 * 시연용 사용자 관리 (US-01~05, RF-05). 로그인에 쓰는 가상 계정(accounts.ts)을 그대로 읽고 바꾼다.
 * 그래서 여기서 이용 제한을 걸면 그 계정은 로그인할 수 없고, 임시 비밀번호를 발급하면 임시 비밀번호 상태로 로그인된다.
 * 서버 규칙(권한·중복·사유 필수·본인 변경 금지)을 같은 에러 코드로 돌려준다.
 */
import { daysAgoIso, nowIso } from '../../core/format'
import { fail, ok, type ApiResult, type ErrorDetail, type User } from '../types'
import type { Page } from '../inquiries'
import type { AccountHistoryItem, Department, UserCreateRequest, UserCreateResult, UserListQuery, UserSummary, UserUpdateRequest } from '../userTypes'
import { MOCK_ACCOUNTS, setTempPassword, unlockAccount } from './accounts'

/** 시연 부서 목록 (RF-05) */
export const DEPARTMENTS: Department[] = [
  { id: 11, name: '개발1팀', parentId: 10, isActive: true },
  { id: 12, name: '개발2팀', parentId: 10, isActive: true },
  { id: 20, name: '서비스데스크', parentId: null, isActive: true },
  { id: 21, name: '네트워크팀', parentId: null, isActive: true },
  { id: 22, name: '보안팀', parentId: null, isActive: true },
  { id: 23, name: '인프라팀', parentId: null, isActive: true },
  { id: 31, name: '영업1팀', parentId: 30, isActive: true },
  { id: 32, name: '영업2팀', parentId: 30, isActive: true },
  { id: 41, name: '디자인팀', parentId: null, isActive: true },
  { id: 51, name: '인사팀', parentId: null, isActive: true },
  { id: 52, name: '재무팀', parentId: null, isActive: true },
]

/** 계정에 딸린 값 중 로그인용 User 에 없는 것 (처음 읽을 때 사번으로 만든다) */
interface Meta {
  email: string
  position: string | null
  lastLoginAt: string | null
  createdAt: string
}
const metas = new Map<string, Meta>()
const history: AccountHistoryItem[] = []
let historySeq = 1

/** 시연 데이터를 처음 상태로 되돌린다. (accounts.ts 의 resetMockState 와 함께 부른다) */
export function resetUsersMock() {
  metas.clear()
  history.length = 0
  historySeq = 1
}

const metaOf = (u: User): Meta => {
  let m = metas.get(u.employeeNo)
  if (!m) {
    m = {
      email: `${u.employeeNo.toLowerCase()}@itssue.example`,
      position: u.serviceRole === 'EMPLOYEE' ? '팀원' : '선임',
      lastLoginAt: u.id % 7 === 0 ? null : daysAgoIso((u.id * 3) % 20),
      createdAt: daysAgoIso(60 + u.id),
    }
    metas.set(u.employeeNo, m)
  }
  return m
}

const deptOf = (id: number | null | undefined) => (id ? DEPARTMENTS.find((d) => d.id === id) ?? null : null)

const toSummary = (u: User): UserSummary => {
  const m = metaOf(u)
  const d = deptOf(u.departmentId)
  return {
    id: u.id,
    employeeNo: u.employeeNo,
    name: u.name,
    email: m.email,
    department: d ? { id: d.id, name: d.name } : u.departmentId ? { id: u.departmentId, name: u.departmentName } : null,
    position: m.position,
    serviceRole: u.serviceRole,
    accountStatus: u.accountStatus,
    lastLoginAt: m.lastLoginAt,
  }
}

const isEmail = (v: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)
const forbidden = () => fail('FORBIDDEN', '이 기능을 쓸 권한이 없습니다.')
const validation = (details: ErrorDetail[]) => fail('VALIDATION_ERROR', '입력값을 확인해 주세요.', { details })

/** 12자 임시 비밀번호 (서버처럼 영문 대·소문자, 숫자, 특수문자를 섞는다) */
function newTempPassword(): string {
  const cs = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  let out = 'Tmp#'
  for (let i = 0; i < 8; i++) out += cs[Math.floor(Math.random() * cs.length)]
  return out
}

/** 정렬 값. 서버가 받는 필드(name·employeeNo·createdAt·lastLoginAt) 외에 부서·역할·상태는 시안용 임시 값이다. */
const SORTERS: Record<string, (u: User) => string | number> = {
  name: (u) => u.name,
  employeeNo: (u) => u.employeeNo,
  createdAt: (u) => metaOf(u).createdAt,
  lastLoginAt: (u) => metaOf(u).lastLoginAt ?? '',
  department: (u) => u.departmentName || '힣',
  serviceRole: (u) => ({ EMPLOYEE: 1, AGENT: 2, ADMIN: 3 })[u.serviceRole],
  accountStatus: (u) => ({ ACTIVE: 1, LOCKED: 2, INACTIVE: 3 })[u.accountStatus],
}

export function mockListUsers(actor: User, q: UserListQuery): ApiResult<Page<UserSummary>> {
  if (actor.serviceRole !== 'ADMIN') return forbidden()
  const [field, dir] = (q.sort ?? 'name,asc').split(',')
  const sorter = SORTERS[field]
  if (!sorter || (dir !== 'asc' && dir !== 'desc')) return validation([{ field: 'sort', reason: 'INVALID_VALUE', message: '정렬 기준이 올바르지 않습니다.' }])
  const key = (q.q ?? '').trim().toLowerCase()
  let list = MOCK_ACCOUNTS.filter((u) => {
    if (key && ![u.name, u.employeeNo, metaOf(u).email, u.departmentName].some((v) => v.toLowerCase().includes(key))) return false
    if (q.departmentId && u.departmentId !== q.departmentId) return false
    if (q.serviceRole?.length && !q.serviceRole.includes(u.serviceRole)) return false
    if (q.accountStatus?.length && !q.accountStatus.includes(u.accountStatus)) return false
    return true
  })
  const sign = dir === 'desc' ? -1 : 1
  list = list.slice().sort((a, b) => {
    const x = sorter(a)
    const y = sorter(b)
    return (typeof x === 'string' && typeof y === 'string' ? x.localeCompare(y, 'ko') : x < y ? -1 : x > y ? 1 : 0) * sign
  })
  const page = q.page ?? 1
  const size = q.size ?? 20
  return ok({ items: list.slice((page - 1) * size, page * size).map(toSummary), page, size, totalCount: list.length, totalPages: list.length ? Math.ceil(list.length / size) : 0 })
}

export function mockCreateUser(actor: User, req: UserCreateRequest): ApiResult<UserCreateResult> {
  if (actor.serviceRole !== 'ADMIN') return forbidden()
  const details: ErrorDetail[] = []
  const employeeNo = (req.employeeNo ?? '').trim()
  const name = (req.name ?? '').trim()
  const email = (req.email ?? '').trim()
  if (!employeeNo) details.push({ field: 'employeeNo', reason: 'REQUIRED', message: '사번을 입력해 주세요.' })
  else if (employeeNo.length > 20) details.push({ field: 'employeeNo', reason: 'TOO_LONG', message: '사번은 20자까지 입력할 수 있습니다.' })
  if (!name) details.push({ field: 'name', reason: 'REQUIRED', message: '이름을 입력해 주세요.' })
  if (!email) details.push({ field: 'email', reason: 'REQUIRED', message: '이메일을 입력해 주세요.' })
  else if (!isEmail(email)) details.push({ field: 'email', reason: 'INVALID_FORMAT', message: '이메일 형식이 올바르지 않습니다.' })
  if (req.departmentId && !deptOf(req.departmentId)) details.push({ field: 'departmentId', reason: 'NOT_FOUND', message: '없는 부서입니다.' })
  if (details.length) return validation(details)
  if (MOCK_ACCOUNTS.some((u) => u.employeeNo.toLowerCase() === employeeNo.toLowerCase()))
    return fail('USER_EMPLOYEE_NO_DUPLICATE', '이미 등록된 사번입니다.', { details: [{ field: 'employeeNo', reason: 'DUPLICATE', message: '이미 등록된 사번입니다.' }] })
  if (MOCK_ACCOUNTS.some((u) => metaOf(u).email.toLowerCase() === email.toLowerCase()))
    return fail('USER_EMAIL_DUPLICATE', '이미 등록된 이메일입니다.', { details: [{ field: 'email', reason: 'DUPLICATE', message: '이미 등록된 이메일입니다.' }] })

  const dept = deptOf(req.departmentId)
  const user: User = {
    id: Math.max(0, ...MOCK_ACCOUNTS.map((u) => u.id)) + 1,
    employeeNo,
    name,
    departmentId: dept?.id ?? null,
    departmentName: dept?.name ?? '',
    serviceRole: req.serviceRole,
    accountStatus: 'ACTIVE',
  }
  MOCK_ACCOUNTS.push(user)
  metas.set(employeeNo, { email, position: req.position?.trim() || null, lastLoginAt: null, createdAt: nowIso() })
  const temporaryPassword = newTempPassword()
  setTempPassword(employeeNo, temporaryPassword)
  return ok({ user: toSummary(user), temporaryPassword })
}

export function mockUpdateUser(actor: User, id: number, req: UserUpdateRequest): ApiResult<UserSummary> {
  if (actor.serviceRole !== 'ADMIN') return forbidden()
  const u = MOCK_ACCOUNTS.find((x) => x.id === id)
  if (!u) return fail('USER_NOT_FOUND', '사용자를 찾을 수 없습니다.')
  const roleChange = req.serviceRole !== undefined && req.serviceRole !== u.serviceRole
  const statusChange = req.accountStatus !== undefined && req.accountStatus !== u.accountStatus
  if ((roleChange || statusChange) && u.id === actor.id) return fail('USER_SELF_CHANGE_NOT_ALLOWED', '자신의 서비스 권한과 계정 상태는 변경할 수 없습니다.')
  if ((roleChange || statusChange) && !req.reason?.trim())
    return fail('USER_STATUS_REASON_REQUIRED', '계정 상태를 변경할 때는 사유를 입력해 주세요.', { details: [{ field: 'reason', reason: 'REQUIRED', message: '사유를 입력해 주세요.' }] })

  const details: ErrorDetail[] = []
  if (req.name !== undefined && !req.name.trim()) details.push({ field: 'name', reason: 'REQUIRED', message: '이름을 입력해 주세요.' })
  if (req.email !== undefined) {
    const email = req.email.trim()
    if (!email) details.push({ field: 'email', reason: 'REQUIRED', message: '이메일을 입력해 주세요.' })
    else if (!isEmail(email)) details.push({ field: 'email', reason: 'INVALID_FORMAT', message: '이메일 형식이 올바르지 않습니다.' })
  }
  if (req.departmentId && !deptOf(req.departmentId)) details.push({ field: 'departmentId', reason: 'NOT_FOUND', message: '없는 부서입니다.' })
  if (details.length) return validation(details)
  if (req.email !== undefined && MOCK_ACCOUNTS.some((x) => x !== u && metaOf(x).email.toLowerCase() === req.email!.trim().toLowerCase()))
    return fail('USER_EMAIL_DUPLICATE', '이미 등록된 이메일입니다.', { details: [{ field: 'email', reason: 'DUPLICATE', message: '이미 등록된 이메일입니다.' }] })

  const m = metaOf(u)
  if (req.name !== undefined) u.name = req.name.trim()
  if (req.email !== undefined) m.email = req.email.trim()
  if (req.position !== undefined) m.position = req.position?.trim() || null
  if (req.departmentId !== undefined) {
    const d = deptOf(req.departmentId)
    u.departmentId = d?.id ?? null
    u.departmentName = d?.name ?? ''
  }
  if (req.serviceRole !== undefined) u.serviceRole = req.serviceRole
  if (req.accountStatus !== undefined) {
    // 잠긴 계정을 정상으로 바꾸면 잠금을 푼다 (실패 횟수·잠금 시각도 지운다)
    if (u.accountStatus === 'LOCKED' && req.accountStatus === 'ACTIVE') unlockAccount(u)
    else u.accountStatus = req.accountStatus
  }
  return ok(toSummary(u))
}

export function mockIssueTempPassword(actor: User, id: number): ApiResult<{ temporaryPassword: string }> {
  if (actor.serviceRole !== 'ADMIN') return forbidden()
  const u = MOCK_ACCOUNTS.find((x) => x.id === id)
  if (!u) return fail('USER_NOT_FOUND', '사용자를 찾을 수 없습니다.')
  const temporaryPassword = newTempPassword()
  setTempPassword(u.employeeNo, temporaryPassword)
  // 잠긴 계정은 잠금도 풀린다. 이용 제한 계정은 상태를 바꾸지 않는다.
  if (u.accountStatus === 'LOCKED') unlockAccount(u)
  return ok({ temporaryPassword })
}

export const mockDepartments = (): Department[] => DEPARTMENTS.filter((d) => d.isActive).sort((a, b) => a.name.localeCompare(b.name, 'ko'))

export const historyLog = () => history.slice()
export function pushHistory(h: Omit<AccountHistoryItem, 'id' | 'at'>) {
  history.unshift({ ...h, id: historySeq++, at: nowIso() })
}
