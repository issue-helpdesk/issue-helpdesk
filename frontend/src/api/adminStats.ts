/**
 * 관리자 통계의 원자료 (제안). 서버는 운영 집계 API(GET /dashboard/overview, OP-01)가 있어 기간별 접수·상태·긴급도·팀·구성원·추이를 한 번에 받는다.
 * AI 상담 건수는 문의 목록(IQ-02)의 구분별 총건수를 쓴다.
 * 서버 집계는 "선택 기간에 접수된 티켓"의 현재 상태를 센다(접수한 날 기준). 기간은 최대 1년이다.
 * 분류별 상태 건수와 구성원별 분류 분포는 서버 집계에 없어서 화면에서도 보여 주지 않는다. (요청 R-01)
 */
import { request } from '../core/apiClient'
import { USE_MOCK_TICKET } from '../core/config'
import type { Urgency } from './chatTypes'
import { listAiInquiries, type AiPage } from './inquiries'
import { listStaff, listSupportGroups } from './reference'
import type { TicketSummary } from './ticketTypes'
import { ok, type ApiResult, type User } from './types'

export type AdminStatKey = 'ai'
type Per = 'd' | 'm' | 'y'
type Unit = 'd' | 'w' | 'mo'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface AdminStatsSource {
  items: TicketSummary[]
  names: string[]
  extra?: AiPage['counts'] | StatsOverview
}

/** AI 상담 결과 건수 (문의 목록 IQ-02 의 구분별 총건수) */
export async function getAdminStatsSource(_user: User, _key: AdminStatKey, per: Per): Promise<ApiResult<AdminStatsSource>> {
  if (USE_MOCK_TICKET) await sleep(350) // 응답 지연 흉내
  const r = await listAiInquiries({ per, size: 1 })
  return r.ok ? ok({ items: [], names: [], extra: r.data.counts }) : r
}

/** 팀(담당 그룹)과 구성원 이름. 모의 모드에서 접수 목록으로 집계를 만들 때 쓴다 */
export async function listTeams(user: User): Promise<ApiResult<{ name: string; members: string[] }[]>> {
  const [g, st] = await Promise.all([listSupportGroups(), listStaff(user)])
  if (!g.ok) return g
  if (!st.ok) return st
  return ok(g.data.map((x) => ({ name: x.name, members: st.data.filter((s) => s.group === x.name).map((s) => s.name) })))
}

/* ------------------------------------------------------------------ 운영 집계 (OP-01) */
export type StatCounts = Record<'RDY' | 'WIP' | 'FIN' | 'CLS', number>
export interface OverviewMember {
  id: number
  name: string
  v: StatCounts
}
export interface OverviewGroup {
  id: number
  name: string
  v: StatCounts
  members: OverviewMember[]
}
export interface StatsOverview {
  /** 선택 기간에 접수된 티켓 */
  total: number
  states: StatCounts
  /** 업무 상태가 아직 없는 접수 (배정 전) */
  none: number
  urgency: Record<Urgency, number>
  groups: OverviewGroup[]
  /** 오늘 하루는 추이를 그리지 않는다(null) */
  trend: { labels: string[]; recv: number[]; done: number[] } | null
}

interface SCounts {
  rdy?: number
  wip?: number
  fin?: number
  cls?: number
}
interface SOverview {
  period: { from: string; to: string; interval: 'DAY' | 'WEEK' | 'MONTH' }
  totals: { ticketCount: number }
  byUrgency: { urgency: Urgency; ticketCount: number }[]
  byGroup: (SCounts & { groupId: number; name: string })[]
  byMember: (SCounts & { userId: number; name: string; groupId: number })[]
  trend: { date: string; ticketCount: number; closedCount: number }[]
}

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const DAYS: Record<Per, number> = { d: 1, m: 30, y: 365 }
const INTERVAL: Record<Unit, string> = { d: 'DAY', w: 'WEEK', mo: 'MONTH' }
const counts = (c: SCounts): StatCounts => ({ RDY: c.rdy ?? 0, WIP: c.wip ?? 0, FIN: c.fin ?? 0, CLS: c.cls ?? 0 })
const sum = (v: StatCounts) => v.RDY + v.WIP + v.FIN + v.CLS
const md = (iso: string) => `${Number(iso.slice(5, 7))}.${Number(iso.slice(8, 10))}`

/** 막대 한 구간의 이름: 일별 `11.4`, 주별 `10.29~11.4`, 월별 `26.11` */
export function bucketLabel(date: string, interval: SOverview['period']['interval'], end: string): string {
  if (interval === 'DAY') return md(date)
  if (interval === 'MONTH') return `${date.slice(2, 4)}.${date.slice(5, 7)}`
  const last = new Date(`${date}T00:00:00`)
  last.setDate(last.getDate() + 6)
  const stop = ymd(last) > end ? end : ymd(last)
  return `${md(date)}~${md(stop)}`
}

/** 서버 모드: 선택 기간(오늘·최근 30일·최근 1년)의 운영 집계를 읽어 화면 값으로 바꾼다. unit 은 추이 막대의 단위 */
export async function getAdminOverview(per: Per, unit: Unit): Promise<ApiResult<StatsOverview>> {
  const to = new Date()
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (DAYS[per] - 1))
  const r = await request<SOverview>(`/dashboard/overview?from=${ymd(from)}&to=${ymd(to)}&interval=${INTERVAL[unit]}`)
  if (!r.ok) return r
  const o = r.data
  const groups: OverviewGroup[] = o.byGroup.map((g) => ({
    id: g.groupId,
    name: g.name,
    v: counts(g),
    members: o.byMember.filter((m) => m.groupId === g.groupId).map((m) => ({ id: m.userId, name: m.name, v: counts(m) })),
  }))
  // 업무 상태별 합계: 팀이 정해진 접수 기준(서버 집계가 팀별로만 상태를 준다)
  const states = groups.reduce<StatCounts>((a, g) => ({ RDY: a.RDY + g.v.RDY, WIP: a.WIP + g.v.WIP, FIN: a.FIN + g.v.FIN, CLS: a.CLS + g.v.CLS }), { RDY: 0, WIP: 0, FIN: 0, CLS: 0 })
  const urgency = { P1: 0, P2: 0, P3: 0, P4: 0 } as Record<Urgency, number>
  for (const u of o.byUrgency) urgency[u.urgency] = u.ticketCount
  const end = o.period.to
  return ok({
    total: o.totals.ticketCount,
    states,
    none: Math.max(0, o.totals.ticketCount - sum(states)),
    urgency,
    groups,
    trend: per === 'd' ? null : { labels: o.trend.map((t) => bucketLabel(t.date, o.period.interval, end)), recv: o.trend.map((t) => t.ticketCount), done: o.trend.map((t) => t.closedCount) },
  })
}
