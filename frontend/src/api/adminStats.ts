/**
 * 관리자 통계의 구역별 원자료 (제안). 서버에는 통계 API 가 없어(요청 R-01) 접수 목록(TK-05 view=ALL)을 읽어 화면에서 센다.
 * 서버는 한 번에 최대 100건이라 그보다 많으면 집계가 일부 빠진다. AI 상담 건수는 문의 목록(IQ-02)의 구분별 총건수를 쓴다.
 */
import { USE_MOCK_TICKET } from '../core/config'
import { listAiInquiries, type AiPage } from './inquiries'
import { listStaff, listSupportGroups } from './reference'
import { listTickets } from './tickets'
import type { TicketSummary } from './ticketTypes'
import { ok, type ApiResult, type User } from './types'

export type AdminStatKey = 'sum' | 'trend' | 'pri' | 'prog' | 'mem' | 'ai'
export type Per = 'd' | 'm' | 'y'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export interface AdminStatsSource {
  items: TicketSummary[]
  names: string[]
  extra?: AiPage['counts'] | { groups: { name: string; members: string[] }[] }
}

/** 팀(담당 그룹)과 구성원 이름 */
export async function listTeams(user: User): Promise<ApiResult<{ name: string; members: string[] }[]>> {
  const [g, st] = await Promise.all([listSupportGroups(), listStaff(user)])
  if (!g.ok) return g
  if (!st.ok) return st
  return ok(g.data.map((x) => ({ name: x.name, members: st.data.filter((s) => s.group === x.name).map((s) => s.name) })))
}

export async function getAdminStatsSource(user: User, key: AdminStatKey, per: Per): Promise<ApiResult<AdminStatsSource>> {
  if (USE_MOCK_TICKET) await sleep(350) // 응답 지연 흉내
  if (key === 'ai') {
    const r = await listAiInquiries({ per, size: 1 })
    return r.ok ? ok({ items: [], names: [], extra: r.data.counts }) : r
  }
  const r = await listTickets(user, { view: 'ALL', size: USE_MOCK_TICKET ? 200 : 100 })
  if (!r.ok) return r
  if (key === 'prog' || key === 'mem') {
    const t = await listTeams(user)
    if (!t.ok) return t
    return ok({ items: r.data.items, names: [], extra: { groups: t.data } })
  }
  return ok({ items: r.data.items, names: [] })
}
