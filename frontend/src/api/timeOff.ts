/**
 * 연차·반차 일정 API 어댑터 (캘린더 화면). docs/api/05 TO-01~04
 *
 *   GET    /time-off?dateFrom&dateTo&size&page   TO-01 일정 목록 (기간과 겹치는 일정, 서버가 볼 수 있는 범위만)
 *   POST   /time-off                             TO-02 일정 등록 (userId 를 빼면 본인)
 *   DELETE /time-off/{id}                        TO-04 일정 삭제
 *
 * 화면은 본인 일정만 등록·삭제한다 (서버는 팀장·관리자에게 더 넓게 허용하지만 화면에서는 쓰지 않는다).
 * 서버가 볼 수 있게 해 주는 범위: 관리자는 전체, 팀장은 자기 그룹, 일반 담당자는 지금은 본인만(팀 일정 조회는 서버에 요청 중).
 * 접수 영역(VITE_USE_MOCK_TICKET)을 따른다. 모의 모드에서는 메모리에 둔 예시 일정을 쓴다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_TICKET } from '../core/config'
import { fail, ok, type ApiResult, type ErrorDetail, type User } from './types'

export type TimeOffType = 'ANNUAL' | 'HALF_AM' | 'HALF_PM'

export const TIME_OFF_LABEL: Record<TimeOffType, string> = { ANNUAL: '연차', HALF_AM: '오전 반차', HALF_PM: '오후 반차' }

export interface TimeOff {
  id: number
  userId: number
  user: { id: number; employeeNo: string; name: string }
  timeOffType: TimeOffType
  /** YYYY-MM-DD */
  startDate: string
  /** YYYY-MM-DD (포함) */
  endDate: string
  note: string | null
  createdBy: { id: number; name: string } | null
  createdAt: string
}

interface TimeOffInput {
  timeOffType: TimeOffType
  startDate: string
  endDate: string
  note?: string
}

/** 날짜를 YYYY-MM-DD 로 (사용자 기기의 날짜 기준) */
export const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

const PAGE_SIZE = 100

/** 기간(포함)과 겹치는 일정. 서버가 알려 준 마지막 페이지까지 읽는다. */
export async function listTimeOff(user: User, from: string, to: string): Promise<ApiResult<TimeOff[]>> {
  if (USE_MOCK_TICKET) return ok(mockList(user, from, to))
  const all: TimeOff[] = []
  for (let page = 1; ; page++) {
    const r = await request<{ items: TimeOff[]; totalPages?: number }>(`/time-off?dateFrom=${from}&dateTo=${to}&sort=startDate,asc&size=${PAGE_SIZE}&page=${page}`)
    if (!r.ok) return r
    all.push(...r.data.items)
    if (page >= (r.data.totalPages ?? 1)) break
  }
  return ok(all)
}

/** 본인 일정 등록 */
export async function createTimeOff(user: User, input: TimeOffInput): Promise<ApiResult<TimeOff>> {
  if (USE_MOCK_TICKET) return mockCreate(user, input)
  return request<TimeOff>('/time-off', { method: 'POST', body: JSON.stringify({ ...input, note: input.note?.trim() || undefined }) })
}

export async function deleteTimeOff(id: number): Promise<ApiResult<null>> {
  if (USE_MOCK_TICKET) {
    store = (store ?? []).filter((t) => t.id !== id)
    return ok(null)
  }
  return request<null>(`/time-off/${id}`, { method: 'DELETE' })
}

// ───── 모의 데이터 ─────
// 팀 구성원(모의 담당 그룹 표)과 같은 사람들이라서 관리자 캘린더에서 [팀] 표시가 붙는다
const MATES = [
  { id: 302, employeeNo: 'EMP-1049', name: '정서현' },
  { id: 441, employeeNo: 'EMP-1241', name: '한지민' },
  { id: 450, employeeNo: 'EMP-1130', name: '권다은' },
  { id: 410, employeeNo: 'EMP-1321', name: '박서연' },
  { id: 420, employeeNo: 'EMP-1064', name: '강지호' },
  { id: 460, employeeNo: 'EMP-1408', name: '황민석' },
]
let store: TimeOff[] | null = null
let seq = 100
const shift = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return ymd(d)
}
function seed(user: User): TimeOff[] {
  const me = { id: user.id, employeeNo: user.employeeNo, name: user.name }
  const mk = (id: number, u: TimeOff['user'], t: TimeOffType, a: number, b: number, note: string | null): TimeOff => ({ id, userId: u.id, user: u, timeOffType: t, startDate: shift(a), endDate: shift(b), note, createdBy: { id: u.id, name: u.name }, createdAt: new Date().toISOString() })
  return [mk(1, me, 'ANNUAL', 4, 6, '가족 행사'), mk(2, MATES[0], 'HALF_AM', 1, 1, '병원 진료'), mk(3, MATES[0], 'HALF_PM', 1, 1, null), mk(4, MATES[1], 'ANNUAL', 9, 10, null), mk(5, MATES[2], 'ANNUAL', -2, -1, '리프레시'),
    // 하루에 일정이 몰린 날("+N개 더 보기" 확인용)
    mk(6, MATES[3], 'ANNUAL', 1, 1, null), mk(7, MATES[4], 'HALF_AM', 1, 1, null), mk(8, MATES[5], 'ANNUAL', 1, 1, null)]
}
function data(user: User): TimeOff[] {
  if (!store) store = seed(user)
  return store
}
/** 테스트에서 모의 일정을 처음 상태로 되돌린다 */
export function resetMockTimeOff() {
  store = null
  seq = 100
}

function mockList(user: User, from: string, to: string): TimeOff[] {
  // 관리자는 전체, 담당자는 팀 일정까지 (서버가 팀 조회를 허용했을 때의 모습)
  return data(user)
    .filter((t) => t.startDate <= to && t.endDate >= from)
    .sort((a, b) => (a.startDate < b.startDate ? -1 : a.startDate > b.startDate ? 1 : a.id - b.id))
}

function mockCreate(user: User, i: TimeOffInput): ApiResult<TimeOff> {
  const details: ErrorDetail[] = []
  if (i.endDate < i.startDate) details.push({ field: 'endDate', reason: 'INVALID_VALUE', message: '종료일은 시작일 이후여야 해요.' })
  else if (i.timeOffType !== 'ANNUAL' && i.endDate !== i.startDate) details.push({ field: 'endDate', reason: 'INVALID_VALUE', message: '반차는 하루만 등록할 수 있어요.' })
  if (details.length) return fail('VALIDATION_ERROR', '입력한 내용을 확인해 주세요.', { details })
  const mine = data(user).filter((t) => t.userId === user.id)
  const clash = mine.find((t) => {
    if (t.startDate > i.endDate || t.endDate < i.startDate) return false
    // 같은 날 오전·오후 반차는 함께 등록할 수 있다
    const half = (x: TimeOffType) => x === 'HALF_AM' || x === 'HALF_PM'
    return !(half(t.timeOffType) && half(i.timeOffType) && t.timeOffType !== i.timeOffType && t.startDate === i.startDate && i.startDate === i.endDate)
  })
  if (clash) return fail('TIME_OFF_OVERLAP', '', { details: [{ reason: 'TIME_OFF_ID', message: '겹치는 일정', value: clash.id as never }] })
  const row: TimeOff = { id: ++seq, userId: user.id, user: { id: user.id, employeeNo: user.employeeNo, name: user.name }, timeOffType: i.timeOffType, startDate: i.startDate, endDate: i.endDate, note: i.note?.trim() || null, createdBy: { id: user.id, name: user.name }, createdAt: new Date().toISOString() }
  data(user).push(row)
  return ok(row)
}
