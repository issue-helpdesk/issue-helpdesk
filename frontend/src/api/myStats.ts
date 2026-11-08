/**
 * 담당자 통계의 서버 집계 (GET /dashboard/me, OP-02). 선택 기간(접수한 날 기준)에 접수된 티켓 중 내 접수와 내가 속한 팀·팀원의 상태별 건수를 준다.
 * 접수 추이·긴급도 분포는 이 집계에 없어서 화면이 접수 목록으로 센다. (요청 R-01)
 * "배정 전" 건수도 집계에 없다(팀이 정해진 접수만 센다).
 */
import { request } from '../core/apiClient'
import type { OverviewGroup, StatCounts } from './adminStats'
import { ok, type ApiResult, type User } from './types'

type MyPer = 'd' | 'm' | 'y'

export interface MyOverview {
  me: StatCounts
  /** 내가 속한 팀. 찾지 못하면 null */
  group: OverviewGroup | null
  /** 업무 상태가 아직 없는 팀 접수. 서버 집계에는 없어서 모의 모드에서만 있다 */
  none?: number
}

interface SCounts {
  rdy?: number
  wip?: number
  fin?: number
  cls?: number
}
interface SMy {
  me: SCounts
  groups: (SCounts & { groupId: number; name: string; members: (SCounts & { userId: number; name: string })[] })[]
}

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const DAYS: Record<MyPer, number> = { d: 1, m: 30, y: 365 }
const counts = (c: SCounts): StatCounts => ({ RDY: c.rdy ?? 0, WIP: c.wip ?? 0, FIN: c.fin ?? 0, CLS: c.cls ?? 0 })

/** 서버 모드: 내 접수와 내 팀의 상태별 건수 (소속 팀 이름이 같은 그룹을 쓰고, 없으면 첫 그룹) */
export async function getMyOverview(user: User, per: MyPer): Promise<ApiResult<MyOverview>> {
  const to = new Date()
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (DAYS[per] - 1))
  const r = await request<SMy>(`/dashboard/me?from=${ymd(from)}&to=${ymd(to)}`)
  if (!r.ok) return r
  const g = r.data.groups.find((x) => x.name === user.departmentName) ?? r.data.groups[0]
  return ok({
    me: counts(r.data.me),
    group: g ? { id: g.groupId, name: g.name, v: counts(g), members: g.members.map((m) => ({ id: m.userId, name: m.name, v: counts(m) })) } : null,
  })
}
