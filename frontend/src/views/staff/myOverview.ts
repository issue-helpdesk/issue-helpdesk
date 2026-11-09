/**
 * 담당자 통계가 쓰는 내 접수·팀 상태별 건수.
 * 서버 모드는 운영 집계(OP-02)를 그대로 쓰고, 모의 모드는 접수 목록으로 같은 모양의 값을 만든다.
 * 구역마다 따로 읽는 화면(useSection)이 그대로 쓰도록 { items, names, extra } 모양으로 돌려준다.
 */
import { USE_MOCK_TICKET } from '../../core/config'
import { getMyOverview, type MyOverview } from '../../api/myStats'
import { getStatsSource } from '../../api/tickets'
import { ok, type ApiResult, type User } from '../../api/types'
import type { TicketSummary } from '../../api/ticketTypes'
import { DAY, PERD, countBy, startOfDay, type Per } from './StatsView'

type Source = { items: TicketSummary[]; names: string[]; extra: MyOverview }

/** 접수 목록(내 팀 접수)으로 서버 집계와 같은 모양의 값을 만든다 (모의 모드) */
function overviewFromTeamItems(items: TicketSummary[], names: string[], user: { id: number; departmentName?: string | null }, per: Per, now: number): MyOverview {
  const from = per === 'd' ? startOfDay(now) : now - PERD[per] * DAY
  const win = items.filter((t) => Date.parse(t.createdAt) >= from)
  return {
    me: countBy(win.filter((t) => t.assignee?.id === user.id)),
    group: {
      id: 1,
      name: user.departmentName ?? '',
      v: countBy(win),
      members: names.map((n, i) => ({ id: i + 1, name: n, v: countBy(win.filter((t) => t.assignee?.name === n)) })),
    },
    none: win.filter((t) => !t.workStatus).length,
  }
}

export async function loadMine(user: User, per: Per): Promise<ApiResult<Source>> {
  if (!USE_MOCK_TICKET) {
    const r = await getMyOverview(user, per)
    return r.ok ? ok({ items: [], names: [], extra: r.data }) : r
  }
  const src = await getStatsSource(user, 'mem')
  if (!src.ok) return src
  return ok({ items: [], names: [], extra: overviewFromTeamItems(src.data.items, src.data.names, user, per, Date.now()) })
}
