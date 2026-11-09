/**
 * 관리자 대시보드 (/dash). (design/ITssue-Prototype.html viewDash)
 * 접수 목록(TK-05 view=ALL)을 조건별로 받아 건수와 먼저 볼 문의를 만든다. 서버에는 집계 API 가 없어 건수는 size=1 로 받은 총건수를 쓴다.
 *   처리 현황       workStatus=RDY / WIP / FIN 각각의 totalCount
 *   연동·배정 확인  needsAdmin=true (원인별 건수는 목록의 jiraSyncStatus·assignStatus·transitionStatus 로 나눈다)
 *   긴급·높음 미해결 urgency=P1,P2 · workStatus=RDY,WIP (처리 대기·처리 중). ITSM 생성 전 접수는 운영 현황의 연동 확인에서 본다
 */
import { listAllTickets, listTickets } from './tickets'
import type { TicketSummary } from './ticketTypes'
import { ok, type ApiResult, type User } from './types'

export interface DashSnapshot {
  rdy: number
  wip: number
  fin: number
  /** 연동·배정 확인이 필요한 접수 수와 원인별 건수 */
  attention: { total: number; jira: number; sync: number; assign: number }
  /** 긴급·높음 미해결: 긴급(P1)이 먼저, 같은 긴급도에서는 접수가 오래된 건 먼저 */
  unresolved: { total: number; p1: number; p2: number; top: TicketSummary[] }
  asOf: string
}

export async function getDashSnapshot(user: User): Promise<ApiResult<DashSnapshot>> {
  const base = { view: 'ALL' as const }
  // 상태별 건수는 상태 조건 없는 1건 요청의 statusCounts 로 한 번에 읽는다 (R-46)
  const [counts, need, open] = await Promise.all([
    listTickets(user, { ...base, size: 1 }),
    listAllTickets(user, { ...base, needsAdmin: true, size: 100 }),
    listAllTickets(user, { ...base, urgency: ['P1', 'P2'], workStatus: ['RDY', 'WIP'], size: 100, sort: 'createdAt,asc' }),
  ])
  if (!counts.ok) return counts
  if (!need.ok) return need
  if (!open.ok) return open
  const items = need.data.items.filter((t) => t.workStatus !== 'CLS') // 해결 완료된 접수는 확인할 일이 없다
  const un = [...open.data.items].sort((a, b) => (a.urgency ?? '').localeCompare(b.urgency ?? '') || Date.parse(a.createdAt) - Date.parse(b.createdAt))
  const p1 = un.filter((t) => t.urgency === 'P1').length
  return ok({
    rdy: counts.data.statusCounts?.RDY ?? 0,
    wip: counts.data.statusCounts?.WIP ?? 0,
    fin: counts.data.statusCounts?.FIN ?? 0,
    attention: {
      total: items.length,
      sync: items.filter((t) => t.transitionStatus === 'NEEDS_ADMIN').length,
      jira: items.filter((t) => t.transitionStatus !== 'NEEDS_ADMIN' && (t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING')).length,
      assign: items.filter((t) => t.jiraSyncStatus === 'SYNCED' && t.assignStatus === 'NEEDS_ADMIN').length,
    },
    unresolved: { total: un.length, p1, p2: un.length - p1, top: un.slice(0, 3) },
    asOf: new Date().toISOString(),
  })
}

/** 대시보드 검색: 접수번호·ITSM 번호·제목 (서버 검색 범위). 최근 접수 10건 */
export async function searchTickets(user: User, q: string): Promise<ApiResult<{ items: TicketSummary[]; total: number }>> {
  const r = await listTickets(user, { view: 'ALL', q, size: 10, sort: 'createdAt,desc' })
  return r.ok ? ok({ items: r.data.items, total: r.data.totalCount }) : r
}
