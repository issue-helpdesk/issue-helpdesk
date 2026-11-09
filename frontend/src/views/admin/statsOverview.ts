/**
 * 관리자 통계가 쓰는 운영 집계를 읽는다.
 * 서버 모드는 운영 집계 API(OP-01)의 값을 그대로 쓰고, 모의 모드는 접수 목록으로 같은 모양의 값을 만든다.
 * 구역마다 따로 읽는 화면(useSection)이 그대로 쓰도록 { items, names, extra } 모양으로 돌려준다.
 */
import { USE_MOCK_TICKET } from '../../core/config'
import { getAdminOverview, listTeams, type OverviewGroup, type StatCounts, type StatsOverview } from '../../api/adminStats'
import type { Urgency } from '../../api/chatTypes'
import { listTickets } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import { ok, type ApiResult, type User } from '../../api/types'
import { DAY, PERD, bucket, countBy, startOfDay, type Per, type Unit } from '../staff/StatsView'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

type Source = { items: TicketSummary[]; names: string[]; extra: StatsOverview }

/** 접수 목록(선택 기간에 접수된 것)으로 서버 집계와 같은 모양의 값을 만든다 (모의 모드) */
function overviewFromItems(items: TicketSummary[], teams: { name: string; members: string[] }[], per: Per, unit: Unit, now: number): StatsOverview {
  const from = per === 'd' ? startOfDay(now) : now - PERD[per] * DAY
  const win = items.filter((t) => Date.parse(t.createdAt) >= from)
  const states = countBy(win)
  const urgency = Object.fromEntries((['P1', 'P2', 'P3', 'P4'] as Urgency[]).map((p) => [p, win.filter((t) => t.urgency === p).length])) as Record<Urgency, number>
  const groups: OverviewGroup[] = teams.map((g, gi) => {
    const mine = win.filter((t) => t.group?.name === g.name)
    return {
      id: gi + 1,
      name: g.name,
      v: countBy(mine),
      members: g.members.map((n, mi) => ({ id: (gi + 1) * 1000 + mi, name: n, v: countBy(mine.filter((t) => t.assignee?.name === n)) })),
    }
  })
  const none = win.filter((t) => !t.workStatus).length
  let trend: StatsOverview['trend'] = null
  if (per !== 'd') {
    const b = bucket(win, per, unit, now)
    trend = { labels: b.labels, recv: b.recv, done: b.done }
  }
  return { total: win.length, states: states as StatCounts, none, urgency, groups, trend }
}

/** 통계 한 구역이 쓸 운영 집계. unit 은 추이 막대의 단위 */
export async function loadOverview(user: User, per: Per, unit: Unit): Promise<ApiResult<Source>> {
  if (!USE_MOCK_TICKET) {
    const r = await getAdminOverview(per, unit)
    return r.ok ? ok({ items: [], names: [], extra: r.data }) : r
  }
  await sleep(350) // 응답 지연 흉내
  const [t, teams] = await Promise.all([listTickets(user, { view: 'ALL', size: 200 }), listTeams(user)])
  if (!t.ok) return t
  if (!teams.ok) return teams
  return ok({ items: [], names: [], extra: overviewFromItems(t.data.items, teams.data, per, unit, Date.now()) })
}
