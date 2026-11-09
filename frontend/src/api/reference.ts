/**
 * 담당 그룹·구성원·부재·업무량 (관리자의 전체 문의 필터, 재배정·지정 후보, 운영 현황의 팀별 개인 현황). (docs/api/05 RF-03·04, TO-01, docs/api/03 TK-05)
 *   GET /support-groups                    RF-03 담당 그룹 목록
 *   GET /support-groups/{id}/members       RF-04 그룹 구성원 (배정 가능 여부, ITSM 계정, 지금 부재 여부, 진행 접수 수)
 *   GET /time-off                          TO-01 오늘의 연차·반차 (부재 사유)
 *   GET /tickets?view=ALL                  TK-05 처리 대기·처리 중 접수 (구성원별 처리 대기/처리 중 건수, 긴급도 분포)
 * 접수 영역(VITE_USE_MOCK_TICKET)을 따른다. 모의 모드에서는 mock/staffTickets.ts 의 그룹·구성원을 쓴다.
 * RF-04 는 업무량을 합계(openTicketCount)로만 주고 처리 대기/처리 중·긴급도 분포는 주지 않아 TK-05 로 센다. (요청 R-13)
 */
import { request } from '../core/apiClient'
import { USE_MOCK_TICKET } from '../core/config'
import type { Urgency } from './chatTypes'
import { GROUP_ID, GROUP_STAFF, workloadOf } from './mock/staffTickets'
import { listTickets } from './tickets'
import { ok, type ApiResult, type User } from './types'

export interface SupportGroupRef {
  id: number
  name: string
}
export interface StaffRef {
  id: number
  name: string
  /** 소속 담당 그룹(팀) 이름 */
  group: string
}

/** 재배정 후보 한 명: 오늘 상태, 업무량(처리 대기·처리 중), 긴급도 분포, ITSM 계정 연결 */
export interface Candidate {
  id: number
  name: string
  avail: boolean
  /** 부재 사유 (연차·반차) */
  leave?: string
  /** ITSM 에 배정을 반영할 수 있는지 (서버: 활성 + 배정 가능 + ITSM 계정 연결) */
  jira: boolean
  rdy: number
  wip: number
  pri: Record<Urgency, number>
}

/** RF-04 응답 중 화면이 쓰는 부분 */
interface ServerMember {
  userId: number
  user: { id: number; employeeNo: string; name: string }
  assignable: boolean
  hasJiraAccount: boolean
  isActive: boolean
  onLeave: boolean
}
interface ServerTimeOff {
  userId: number
  timeOffType: 'ANNUAL' | 'HALF_AM' | 'HALF_PM'
}
const LEAVE_LABEL = { ANNUAL: '연차', HALF_AM: '오전 반차', HALF_PM: '오후 반차' } as const

export async function listSupportGroups(): Promise<ApiResult<SupportGroupRef[]>> {
  if (USE_MOCK_TICKET) return ok(Object.keys(GROUP_STAFF).map((name) => ({ id: GROUP_ID[name], name })))
  const r = await request<{ items: SupportGroupRef[] }>('/support-groups')
  return r.ok ? ok(r.data.items.map((g) => ({ id: g.id, name: g.name }))) : r
}

/** 서버 구성원 표: 담당 그룹마다 RF-04 를 부른다. 같은 화면에서 여러 번 부르지 않도록 잠깐 기억한다 */
let memberCache: { at: number; data: { group: SupportGroupRef; members: ServerMember[] }[] } | null = null
const MEMBER_TTL = 15_000
/** 테스트에서 기억을 비운다 */
export function resetReferenceCache() {
  memberCache = null
}
async function serverMembers(): Promise<ApiResult<{ group: SupportGroupRef; members: ServerMember[] }[]>> {
  if (memberCache && Date.now() - memberCache.at < MEMBER_TTL) return ok(memberCache.data)
  const g = await listSupportGroups()
  if (!g.ok) return g
  const rs = await Promise.all(g.data.map((x) => request<{ items: ServerMember[] }>(`/support-groups/${x.id}/members`)))
  const bad = rs.find((r) => !r.ok)
  if (bad && !bad.ok) return bad
  const data = g.data.map((group, i) => ({ group, members: rs[i].ok ? rs[i].data.items : [] }))
  memberCache = { at: Date.now(), data }
  return ok(data)
}

export async function listStaff(actor: User): Promise<ApiResult<StaffRef[]>> {
  void actor
  if (USE_MOCK_TICKET) return ok(Object.entries(GROUP_STAFF).flatMap(([group, list]) => list.map((m) => ({ id: m.id, name: m.name, group }))))
  const r = await serverMembers()
  return r.ok ? ok(r.data.flatMap((x) => x.members.filter((m) => m.isActive).map((m) => ({ id: m.userId, name: m.user.name, group: x.group.name })))) : r
}

const emptyPri = (): Record<Urgency, number> => ({ P1: 0, P2: 0, P3: 0, P4: 0 })

/**
 * 담당 그룹별 구성원과 업무량 (재배정·지정 후보, 팀별 개인 현황). groupNames 를 생략하면 모든 그룹.
 * 서버: 구성원은 RF-04, 오늘의 부재 사유는 TO-01(없으면 사유 없이 "연차"), 처리 대기·처리 중 건수와 긴급도 분포는 TK-05 처리 대기·처리 중 접수(최대 100건)를 센다.
 */
export async function listBoard(user: User, groupNames?: string[]): Promise<ApiResult<Record<string, Candidate[]>>> {
  if (USE_MOCK_TICKET) {
    const names = groupNames ?? Object.keys(GROUP_STAFF)
    return ok(Object.fromEntries(names.map((n) => [n, (GROUP_STAFF[n] ?? []).map((m) => ({ id: m.id, name: m.name, avail: m.avail, leave: m.leave, jira: m.jira, ...workloadOf(m.id) }))])))
  }
  const members = await serverMembers()
  if (!members.ok) return members
  const today = new Date()
  const ymd = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  const [leave, open] = await Promise.all([request<{ items: ServerTimeOff[] }>(`/time-off?dateFrom=${ymd}&dateTo=${ymd}&size=100`), listTickets(user, { view: 'ALL', workStatus: ['RDY', 'WIP'], size: 100 })])
  const why = new Map<number, string>()
  if (leave.ok) leave.data.items.forEach((t) => why.set(t.userId, LEAVE_LABEL[t.timeOffType] ?? '연차'))
  const load = new Map<number, { rdy: number; wip: number; pri: Record<Urgency, number> }>()
  if (open.ok)
    open.data.items.forEach((t) => {
      if (!t.assignee) return
      const w = load.get(t.assignee.id) ?? { rdy: 0, wip: 0, pri: emptyPri() }
      if (t.workStatus === 'RDY') w.rdy++
      else w.wip++
      if (t.urgency) w.pri[t.urgency]++
      load.set(t.assignee.id, w)
    })
  const out: Record<string, Candidate[]> = {}
  members.data
    .filter((x) => !groupNames || groupNames.includes(x.group.name))
    .forEach((x) => {
      out[x.group.name] = x.members
        .filter((m) => m.isActive)
        .map((m) => ({
          id: m.userId,
          name: m.user.name,
          avail: !m.onLeave,
          leave: m.onLeave ? (why.get(m.userId) ?? '연차') : undefined,
          jira: m.hasJiraAccount && m.assignable,
          ...(load.get(m.userId) ?? { rdy: 0, wip: 0, pri: emptyPri() }),
        }))
    })
  return ok(out)
}

/** 한 담당 그룹의 후보 (재배정·지정 창) */
export async function listCandidates(user: User, groupName: string): Promise<ApiResult<Candidate[]>> {
  const r = await listBoard(user, [groupName])
  return r.ok ? ok(r.data[groupName] ?? []) : r
}
