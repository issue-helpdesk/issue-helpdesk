/**
 * 운영 현황 (관리자). (design/ITssue-Prototype.html viewExc)
 * 지금 확인하고 처리할 일을 모아 보여 준다: 긴급 조치(P1), 당일 미종결 예외, 티켓 연동 확인, 담당자 배정 확인.
 * 목록은 접수 목록(TK-05 view=ALL)을 조건별로 받아 나눈다. 서버에는 이 화면 전용 집계 API 가 없다.
 *   긴급 조치       urgency=P1 · workStatus=RDY,WIP
 *   당일 미종결     urgency=P1,P2 · 처리 대기·처리 중·해결 확인 대기 중 접수일이 오늘 이전인 것
 *   연동·배정 확인  needsAdmin=true 를 jiraSyncStatus·assignStatus·transitionStatus 로 나눈다
 * 확인·재시도는 서버의 연동 작업 목록(TK-11)에서 실패한 작업을 골라 재처리(TK-12)를 등록한다. 실행기가 처리해야 끝나므로
 * 접수를 서버로 보내는 환경(VITE_SERVER_INTAKE)에서만 요청하고, 아니면 안내만 한다. 담당자 지정(TK-09)은 따로 연결한다.
 */
import { request } from '../core/apiClient'
import { SERVER_INTAKE, USE_MOCK_TICKET } from '../core/config'
import { nowIso } from '../core/format'
import { notReady } from './inquiryServer'
import { GROUP_STAFF, findStaffTicket, mutateSeed, workloadOf } from './mock/staffTickets'
import { getTicket, listTickets } from './tickets'
import type { IntegrationJob, IntegrationJobType, RetryOutcome, TicketDetail, TicketSummary } from './ticketTypes'
import { fail, ok, type ApiResult, type User } from './types'

export interface OpsSnapshot {
  urgent: TicketSummary[]
  exception: TicketSummary[]
  /** Jira 이슈가 안 만들어졌거나(확인 필요·결과 확인 중) 상태 변경을 Jira 에서 확인하지 못한 접수 */
  link: TicketSummary[]
  /** Jira 이슈는 만들어졌지만 담당자가 비어 있는 접수 */
  assign: TicketSummary[]
  /** 조회 시각 */
  asOf: string
}

const isOpen = (t: TicketSummary) => t.workStatus === 'RDY' || t.workStatus === 'WIP'
const startOfToday = () => {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

export async function getOpsSnapshot(user: User, groupId?: number): Promise<ApiResult<OpsSnapshot>> {
  const base = { view: 'ALL' as const, size: 100, ...(groupId ? { groupId } : {}) }
  const [u, x, n] = await Promise.all([
    listTickets(user, { ...base, urgency: ['P1'], workStatus: ['RDY', 'WIP'], sort: 'createdAt,asc' }),
    listTickets(user, { ...base, urgency: ['P1', 'P2'], workStatus: ['RDY', 'WIP', 'FIN'], sort: 'createdAt,asc' }),
    listTickets(user, { ...base, needsAdmin: true, sort: 'createdAt,asc' }),
  ])
  if (!u.ok) return u
  if (!x.ok) return x
  if (!n.ok) return n
  const today = startOfToday()
  const exception = x.data.items
    .filter((t) => Date.parse(t.createdAt) < today && !(t.urgency === 'P1' && isOpen(t)))
    // P1 먼저, 같은 긴급도에서는 오래된 건 먼저
    .sort((a, b) => (a.urgency ?? '').localeCompare(b.urgency ?? '') || Date.parse(a.createdAt) - Date.parse(b.createdAt))
  // 해결 완료(CLS)된 접수는 더 확인할 일이 없다
  const open = n.data.items.filter((t) => t.workStatus !== 'CLS')
  const link = open.filter((t) => t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING' || t.transitionStatus === 'NEEDS_ADMIN')
  const assign = open.filter((t) => t.jiraSyncStatus === 'SYNCED' && t.assignStatus === 'NEEDS_ADMIN')
  return ok({ urgent: u.data.items, exception, link, assign, asOf: nowIso() })
}

/** 사이드바 배지용: 연동·배정 확인이 필요한 접수 수 */
export async function countOpsAttention(user: User): Promise<number> {
  const r = await listTickets(user, { view: 'ALL', needsAdmin: true, size: 100 })
  return r.ok ? r.data.items.filter((t) => t.workStatus !== 'CLS').length : 0
}

/** 재처리 결과를 담은 접수 상세 */
export type RetryDone = TicketDetail & { outcome: RetryOutcome }

/**
 * 서버 재처리: 이 접수의 연동 작업(TK-11) 중 실패했고 아직 재처리하지 않은 같은 종류의 마지막 작업을 골라 TK-12 로 등록한다.
 * 201 은 작업만 등록한 것(실행기가 처리), 200 은 Jira 에서 이미 해결된 것을 확인해 바로 끝난 것이다.
 */
async function serverRetry(user: User, id: number, jobType: IntegrationJobType, reason: string): Promise<ApiResult<RetryDone>> {
  if (!SERVER_INTAKE) return notReady(jobType === 'JIRA_CREATE' ? 'Jira 생성 확인·재시도' : 'Jira 상태 확인·다시 반영')
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 확인할 수 있어요.')
  const jobs = await request<{ items: IntegrationJob[] }>(`/tickets/${id}/integration-jobs`)
  if (!jobs.ok) return jobs
  const retried = new Set(jobs.data.items.map((j) => j.retryOfJobId))
  const origin = [...jobs.data.items].reverse().find((j) => j.jobType === jobType && (j.status === 'FAILED' || j.status === 'NEEDS_ADMIN') && !retried.has(j.id))
  if (!origin) return fail('INTEGRATION_RETRY_NOT_ALLOWED', '다시 처리할 수 있는 실패 작업이 없어요. 이미 재처리를 등록했을 수 있어요.')
  const r = await request<IntegrationJob | { ticket: TicketDetail; job: null; recoveryResult: 'LINKED_EXISTING' | 'ALREADY_APPLIED' }>(`/tickets/${id}/integration-jobs`, {
    method: 'POST',
    body: JSON.stringify({ retryOfJobId: origin.id, reason: reason.trim().slice(0, 500) }),
  })
  if (!r.ok) return r
  const outcome: RetryOutcome = 'recoveryResult' in r.data ? r.data.recoveryResult : 'REGISTERED'
  const t = 'recoveryResult' in r.data ? ok(r.data.ticket) : await getTicket(user, id)
  return t.ok ? ok({ ...t.data, outcome }) : t
}

const needsOf = (t: TicketDetail) => t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING' || t.assignStatus === 'NEEDS_ADMIN' || t.transitionStatus === 'NEEDS_ADMIN'

/**
 * Jira 생성 확인·재시도. Jira 에 같은 접수번호의 이슈가 없다는 확인을 거친 뒤 눌러서 새로 만든다 (중복 생성 방지).
 * 모의에서는 이슈를 만들고 처리 대기로 두며, 같은 그룹에서 근무 중이고 Jira 계정이 있는 가장 한가한 사람에게 자동 배정한다. 없으면 배정 확인으로 넘긴다.
 */
export async function retryJiraCreate(user: User, id: number, reason: string): Promise<ApiResult<RetryDone>> {
  if (!USE_MOCK_TICKET) return serverRetry(user, id, 'JIRA_CREATE', reason)
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 확인할 수 있어요.')
  const t = findStaffTicket(id)
  if (!t) return fail('TICKET_NOT_FOUND', '접수를 찾을 수 없어요.')
  if (t.jiraSyncStatus === 'SYNCED') return fail('TICKET_INVALID_TRANSITION', '이미 Jira 이슈가 만들어진 접수예요.')
  const pool = (GROUP_STAFF[t.group?.name ?? ''] ?? [])
    .filter((m) => m.avail && m.jira)
    .map((m) => ({ m, n: workloadOf(m.id).rdy + workloadOf(m.id).wip }))
    .sort((a, b) => a.n - b.n)
  const pick = pool[0]?.m
  const key = `ITHD-${t.id - 5000 + 880}`
  mutateSeed(id, (x) => {
    x.jiraSyncStatus = 'SYNCED'
    x.jiraKey = key
    x.jiraUrl = `https://jira.example.com/browse/${key}`
    x.workStatus = 'RDY'
    x.displayStatus = 'assigned'
    x.workStatusConfirmedAt = nowIso()
    x.assignee = pick ? { id: pick.id, employeeNo: pick.employeeNo, name: pick.name } : null
    x.assignStatus = pick ? 'ASSIGNED' : 'NEEDS_ADMIN'
    x.needsAdmin = needsOf(x)
  })
  return ok({ ...findStaffTicket(id)!, outcome: 'DONE' as const })
}

/** Jira 상태 확인·다시 반영: 요청한 상태 변경을 Jira 에서 확인하지 못한 접수를 확인 후 반영한다 */
export async function recheckTransition(user: User, id: number, reason: string): Promise<ApiResult<RetryDone>> {
  if (!USE_MOCK_TICKET) return serverRetry(user, id, 'JIRA_TRANSITION', reason)
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 확인할 수 있어요.')
  const t = findStaffTicket(id)
  if (!t) return fail('TICKET_NOT_FOUND', '접수를 찾을 수 없어요.')
  if (t.transitionStatus !== 'NEEDS_ADMIN' || !t.requestedWorkStatus) return fail('TICKET_INVALID_TRANSITION', '상태 동기화 확인이 필요한 접수가 아니에요.')
  const to = t.requestedWorkStatus
  mutateSeed(id, (x) => {
    x.workStatus = to
    x.displayStatus = to === 'FIN' ? 'awaiting_confirm' : to === 'CLS' ? 'resolved' : 'progress'
    x.requestedWorkStatus = null
    x.transitionStatus = 'IDLE'
    x.workStatusConfirmedAt = nowIso()
    if (to === 'FIN') {
      x.finishedAt = nowIso()
      x.resolutionNote = x.resolutionNote ?? '조치를 완료했습니다.'
    }
    x.needsAdmin = needsOf(x)
  })
  return ok({ ...findStaffTicket(id)!, outcome: 'DONE' as const })
}
