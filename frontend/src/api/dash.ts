/**
 * 관리자 대시보드 (/dash). (design/ITssue-Prototype.html viewDash)
 * 접수 목록(TK-05 view=ALL)을 조건별로 받아 건수와 먼저 볼 문의를 만든다. 서버에는 집계 API 가 없어 건수는 size=1 로 받은 총건수를 쓴다.
 *   처리 현황       workStatus=RDY / WIP / FIN 각각의 totalCount
 *   연동·배정 확인  needsAdmin=true (원인별 건수는 목록의 jiraSyncStatus·assignStatus·transitionStatus 로 나눈다)
 *   Jira 알림       jiraMention=true (제안)
 *   긴급·높음 미해결 urgency=P1,P2 · workStatus=RDY,WIP,FIN + Jira 생성 전(jiraSyncStatus) 접수
 */
import { listTickets } from './tickets'
import type { TicketSummary } from './ticketTypes'
import { ok, type ApiResult, type User } from './types'

export interface DashSnapshot {
  rdy: number
  wip: number
  fin: number
  /** 연동·배정 확인이 필요한 접수 수와 원인별 건수 */
  attention: { total: number; jira: number; sync: number; assign: number }
  /** Jira 알림이 온 접수 수 */
  mentions: number
  /** 긴급·높음 미해결: 긴급(P1)이 먼저, 같은 긴급도에서는 접수가 오래된 건 먼저 */
  unresolved: { total: number; p1: number; p2: number; top: TicketSummary[] }
  asOf: string
}

const PRE_JIRA = ['PENDING', 'VERIFYING', 'NEEDS_ADMIN'] as const

export async function getDashSnapshot(user: User): Promise<ApiResult<DashSnapshot>> {
  const base = { view: 'ALL' as const }
  const total = (workStatus: ('RDY' | 'WIP' | 'FIN')[]) => listTickets(user, { ...base, workStatus, size: 1 })
  const [rdy, wip, fin, need, mention, open, pre] = await Promise.all([
    total(['RDY']),
    total(['WIP']),
    total(['FIN']),
    listTickets(user, { ...base, needsAdmin: true, size: 100 }),
    listTickets(user, { ...base, jiraMention: true, size: 1 }),
    listTickets(user, { ...base, urgency: ['P1', 'P2'], workStatus: ['RDY', 'WIP', 'FIN'], size: 100, sort: 'createdAt,asc' }),
    listTickets(user, { ...base, urgency: ['P1', 'P2'], jiraSyncStatus: [...PRE_JIRA], size: 100, sort: 'createdAt,asc' }),
  ])
  if (!rdy.ok) return rdy
  if (!wip.ok) return wip
  if (!fin.ok) return fin
  if (!need.ok) return need
  if (!mention.ok) return mention
  if (!open.ok) return open
  if (!pre.ok) return pre
  const items = need.data.items
  const seen = new Set<number>()
  const un = [...open.data.items, ...pre.data.items.filter((t) => !t.workStatus)]
    .filter((t) => (seen.has(t.id) ? false : (seen.add(t.id), true)))
    .sort((a, b) => (a.urgency ?? '').localeCompare(b.urgency ?? '') || Date.parse(a.createdAt) - Date.parse(b.createdAt))
  const p1 = un.filter((t) => t.urgency === 'P1').length
  return ok({
    rdy: rdy.data.totalCount,
    wip: wip.data.totalCount,
    fin: fin.data.totalCount,
    attention: {
      total: need.data.totalCount,
      sync: items.filter((t) => t.transitionStatus === 'NEEDS_ADMIN').length,
      jira: items.filter((t) => t.transitionStatus !== 'NEEDS_ADMIN' && (t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING')).length,
      assign: items.filter((t) => t.jiraSyncStatus === 'SYNCED' && t.assignStatus === 'NEEDS_ADMIN').length,
    },
    mentions: mention.data.totalCount,
    unresolved: { total: un.length, p1, p2: un.length - p1, top: un.slice(0, 3) },
    asOf: new Date().toISOString(),
  })
}

/** 대시보드 검색: 접수번호·Jira 번호·제목 (서버 검색 범위). 최근 접수 10건 */
export async function searchTickets(user: User, q: string): Promise<ApiResult<{ items: TicketSummary[]; total: number }>> {
  const r = await listTickets(user, { view: 'ALL', q, size: 10, sort: 'createdAt,desc' })
  return r.ok ? ok({ items: r.data.items, total: r.data.totalCount }) : r
}
