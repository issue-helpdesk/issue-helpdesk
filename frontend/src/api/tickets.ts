/**
 * 담당자 접수 API 어댑터 (처리할 문의 · 상세). (docs/api/03.접수_연동.md)
 *   GET   /tickets                       TK-05 접수 목록 (AGENT 는 소속 그룹, view=ASSIGNED)
 *   GET   /tickets/{id}                  TK-06 접수 상세
 *   PATCH /tickets/{id}                  TK-07 업무 상태 변경·처리 결과 등록 (202, Jira 반영 확인 뒤 확정)
 *   GET   /tickets/{id}/status-history   TK-08 업무 상태 이력
 * 모의 모드(VITE_USE_MOCK=true)에서는 mock/staffTickets.ts 와 문의 저장소를 읽는다. 서버 모드에서는 같은 형태의 응답을 받는다.
 * 실제 서버에서는 상태 변경 뒤 Jira 반영이 서버에서 일어나므로, 화면은 목록·상세를 주기적으로 다시 읽는다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK } from '../core/config'
import { staffTransition } from './mock/chatEngine'
import { later, mockConfig, notify, subscribe } from './mock/chatStore'
import { TEAM_MEMBERS, addMessage, addHistory, messagesOf, slackOf, allStaffTickets, clearMention, findStaffTicket, historyOf, mutateSeed, pending, recordOfTicket } from './mock/staffTickets'
import type { Page } from './inquiries'
import type { MessageKind, SlackPreview, StatusHistory, TicketDetail, TicketMessage, TicketListQuery, TicketSummary, TicketTransitionRequest } from './ticketTypes'
import { fail, ok, type ApiResult, type User } from './types'
import { nowIso } from '../core/format'
import { maskSensitive } from '../core/mask'

/** 서버를 다시 읽는 간격(ms) */
const POLL_MS = 8000

const toQueryString = (q: TicketListQuery) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x))
    else p.set(k, String(v))
  }
  return p.toString()
}

/** 이 사용자가 볼 수 있는 접수인지 (서버는 토큰으로 판단한다): 관리자는 전체, 담당자는 소속 그룹, 문의자는 본인 문의 */
const canSee = (u: User, t: TicketDetail) => (u.serviceRole === 'ADMIN' ? true : u.serviceRole === 'AGENT' ? t.group?.name === u.departmentName : t.requester.employeeNo === u.employeeNo)

const URG = { P1: 1, P2: 2, P3: 3, P4: 4 } as const
const WORK = { RDY: 1, WIP: 2, FIN: 3, CLS: 4 } as const

const summaryOf = (t: TicketDetail): TicketSummary => {
  // 상세에만 있는 값은 목록 응답에 넣지 않는다
  const { targetSystem, symptom, occurredAt, inquiryType, urgencyReason, businessImpact, triedActions, aiSummary, jiraUrl, resolutionNote, finishedAt, closedAt, ...s } = t
  void [targetSystem, symptom, occurredAt, inquiryType, urgencyReason, businessImpact, triedActions, aiSummary, jiraUrl, resolutionNote, finishedAt, closedAt]
  return s
}

/** 접수 목록 (TK-05). AGENT 는 view=ASSIGNED 가 기본이다. */
export async function listTickets(user: User, query: TicketListQuery = {}): Promise<ApiResult<Page<TicketSummary>>> {
  if (!USE_MOCK) return request<Page<TicketSummary>>(`/tickets?${toQueryString(query)}`)
  await sleep(150) // 응답 지연 흉내
  const { page = 1, size = 20, sort = 'createdAt,desc', workStatus, needsAdmin, categoryCode, urgency, assigneeId, createdFrom, q, jiraMention } = query
  const needle = (q ?? '').trim().toLowerCase()
  const from = createdFrom ? new Date(`${createdFrom}T00:00:00`).getTime() : 0
  let rows = allStaffTickets().filter((t) => canSee(user, t))
  rows = rows.filter((t) => {
    if (assigneeId && t.assignee?.id !== assigneeId) return false
    if (workStatus?.length && !(t.workStatus && workStatus.includes(t.workStatus))) return false
    if (needsAdmin !== undefined && t.needsAdmin !== needsAdmin) return false
    if (categoryCode?.length && !(t.category && categoryCode.includes(t.category.code))) return false
    if (urgency?.length && !(t.urgency && urgency.includes(t.urgency))) return false
    if (from && Date.parse(t.createdAt) < from) return false
    if (jiraMention && !t.jiraMention) return false
    if (needle) {
      const hay = [t.receiptNo, t.jiraKey, t.summary, t.requester.name, t.assignee?.name, t.category?.name]
      if (!hay.some((x) => x && String(x).toLowerCase().includes(needle))) return false
    }
    return true
  })
  const [key, dir] = sort.split(',')
  const sign = dir === 'desc' ? -1 : 1
  const val = (t: TicketDetail): string | number => {
    switch (key) {
      case 'urgency':
        return t.urgency ? URG[t.urgency] : 9
      case 'workStatus':
        return t.workStatus ? WORK[t.workStatus] : 0
      case 'summary':
        return t.summary
      case 'category':
        return t.category?.name ?? '힣'
      case 'receiptNo':
        return t.receiptNo
      default:
        return Date.parse(t.createdAt)
    }
  }
  rows.sort((a, b) => {
    const x = val(a)
    const y = val(b)
    const c = (x < y ? -1 : x > y ? 1 : 0) * sign
    if (c) return c
    // 같으면 Jira 알림이 온 건 먼저, 그다음 오래된 건 먼저 (먼저 볼 문의)
    return (b.jiraMention ? 1 : 0) - (a.jiraMention ? 1 : 0) || Date.parse(a.createdAt) - Date.parse(b.createdAt)
  })
  const totalCount = rows.length
  const totalPages = Math.max(1, Math.ceil(totalCount / size))
  const p = Math.min(Math.max(1, page), totalPages)
  return ok({ items: rows.slice((p - 1) * size, p * size).map(summaryOf), page: p, size, totalCount, totalPages })
}

const notFound = () => fail('TICKET_NOT_FOUND', '접수를 찾을 수 없어요.')

/** 접수 상세 (TK-06). 열면 Jira 알림 표시가 지워진다 (제안). */
export async function getTicket(user: User, id: number): Promise<ApiResult<TicketDetail>> {
  if (!USE_MOCK) return request<TicketDetail>(`/tickets/${id}`)
  await sleep(120)
  const t = findStaffTicket(id)
  if (!t || !canSee(user, t)) return notFound()
  const had = !!t.jiraMention // 처음 열 때만 알림 안내를 보여 준다
  clearMention(id)
  if (had) notify() // 사이드바의 NEW 표시가 줄어든다
  return ok({ ...t, jiraMention: had })
}

/** 업무 상태 이력 (TK-08) */
export async function getTicketHistory(user: User, id: number): Promise<ApiResult<{ items: StatusHistory[] }>> {
  if (!USE_MOCK) return request<{ items: StatusHistory[] }>(`/tickets/${id}/status-history`)
  await sleep(100)
  const t = findStaffTicket(id)
  if (!t || !canSee(user, t)) return notFound()
  return ok({ items: historyOf(t) })
}

/**
 * 업무 상태 변경·처리 결과 등록 (TK-07). 담당 그룹·관리자만 RDY → WIP, WIP → FIN 을 요청한다.
 * 응답은 202 이고 확인된 상태(workStatus)는 그대로이며 requestedWorkStatus·transitionStatus=PENDING 이다.
 * Jira 반영을 확인하면 상태가 바뀌고 이력이 한 번 남는다. (모의 모드는 잠깐 뒤에 반영한다)
 */
export async function changeTicketStatus(user: User, id: number, body: TicketTransitionRequest): Promise<ApiResult<TicketDetail>> {
  if (!USE_MOCK) return request<TicketDetail>(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
  await sleep(150)
  const t = findStaffTicket(id)
  if (!t || !canSee(user, t)) return notFound()
  if (user.serviceRole === 'EMPLOYEE') return fail('FORBIDDEN', '이 접수의 상태를 바꿀 수 없어요.')
  if (pending.has(id)) return fail('INTEGRATION_JOB_IN_PROGRESS', '상태 변경을 Jira에 반영하는 중이에요. 잠시 뒤에 다시 시도해 주세요.')
  if (t.jiraSyncStatus !== 'SYNCED') return fail('TICKET_NOT_SYNCED', 'Jira 티켓이 아직 만들어지지 않았어요.')
  const to = body.workStatus
  if (!to) return fail('VALIDATION_ERROR', '바꿀 상태를 골라 주세요.')
  const okMove = (t.workStatus === 'RDY' && to === 'WIP') || (t.workStatus === 'WIP' && to === 'FIN')
  if (!okMove) return fail('TICKET_INVALID_TRANSITION', '이 상태에서는 바꿀 수 없는 변경이에요.')
  const note = (body.resolutionNote ?? t.resolutionNote ?? '').trim()
  if (to === 'FIN' && !note) return fail('TICKET_RESOLUTION_NOTE_REQUIRED', '처리 결과를 입력해 주세요.')
  const from = t.workStatus
  pending.set(id, to)
  notify()
  const rec = recordOfTicket(id)
  later(1200 * mockConfig.pipelineScale, () => {
    pending.delete(id)
    if (rec) staffTransition(rec, to, note)
    else
      mutateSeed(id, (s) => {
        s.workStatus = to
        s.displayStatus = to === 'WIP' ? 'progress' : 'awaiting_confirm'
        s.workStatusConfirmedAt = nowIso()
        if (to === 'FIN') {
          s.resolutionNote = note
          s.finishedAt = nowIso()
        }
      })
    addHistory(id, { fromStatus: from, toStatus: to, source: 'ITSSUE', actor: { id: user.id, employeeNo: user.employeeNo, name: user.name }, reason: to === 'FIN' ? note : null, changedAt: nowIso() })
    notify()
  })
  const cur = findStaffTicket(id)!
  return ok({ ...cur, requestedWorkStatus: to, transitionStatus: 'PENDING' })
}

/**
 * 접수가 바뀔 때마다 알려 준다. (새 접수, 다른 사람이 바꾼 상태, 문의자 접수)
 * 모의 모드에서는 저장소 변경을, 서버 모드에서는 주기적 조회를 쓴다. 돌려주는 함수를 부르면 구독이 끝난다.
 */
export function watchTickets(onChange: () => void): () => void {
  onChange()
  if (USE_MOCK) return subscribe(onChange)
  const timer = setInterval(onChange, POLL_MS)
  return () => clearInterval(timer)
}

/** 우리 팀 현황 (제안): 소속 그룹의 근무 인원과 처리 대기·처리 중·배정 전 건수 */
export interface TeamStatus {
  groupName: string
  /** 팀원 이름 */
  names: string[]
  members: number
  off: number
  rdy: number
  wip: number
  unassigned: number
}
export async function getTeamStatus(user: User): Promise<ApiResult<TeamStatus>> {
  if (!USE_MOCK) return request<TeamStatus>('/tickets/team-status')
  await sleep(120)
  const groupName = user.departmentName ?? ''
  const team = TEAM_MEMBERS[groupName] ?? []
  const list = allStaffTickets().filter((t) => t.group?.name === groupName)
  return ok({
    groupName,
    names: team.map((m) => m.name),
    members: team.length,
    off: team.filter((m) => !m.avail).length,
    rdy: list.filter((t) => t.workStatus === 'RDY').length,
    wip: list.filter((t) => t.workStatus === 'WIP').length,
    unassigned: list.filter((t) => !t.assignee).length,
  })
}

/**
 * 통계 구역 하나의 원자료 (제안): 소속 그룹의 접수와 팀원 이름. 서버에는 구역별 통계 API 가 아직 없어, 구역마다 따로 읽어 화면에서 센다.
 * 한 구역이 실패해도 다른 구역은 그대로 보인다.
 */
export async function getStatsSource(user: User, section: 'sum' | 'trend' | 'pri' | 'mem'): Promise<ApiResult<{ items: TicketSummary[]; names: string[] }>> {
  if (USE_MOCK) {
    await sleep(350)
    if (section === 'trend' && mockConfig.statFail) {
      mockConfig.statFail = false
      return fail('STATS_UNAVAILABLE', '이 구역을 불러오지 못했어요.')
    }
  }
  const r = await listTickets(user, { view: 'ASSIGNED', size: 200 })
  if (!r.ok) return r
  const names = (USE_MOCK ? TEAM_MEMBERS[user.departmentName ?? ''] ?? [] : []).map((m) => m.name)
  return ok({ items: r.data.items, names })
}

/**
 * 문의자에게 보낸 메시지와 Slack 알림 미리보기 (제안). 문서상 AI 중개 양방향 소통은 Could 범위라 서버 API 가 아직 없다.
 * Slack 미리보기는 담당자·관리자에게만 준다 (실제 발송 없음).
 */
export async function getTicketMessages(user: User, id: number): Promise<ApiResult<{ messages: TicketMessage[]; slack: SlackPreview[] }>> {
  if (!USE_MOCK) return request<{ messages: TicketMessage[]; slack: SlackPreview[] }>(`/tickets/${id}/messages`)
  await sleep(100)
  const t = findStaffTicket(id)
  if (!t || !canSee(user, t)) return notFound()
  return ok({ messages: messagesOf(id), slack: user.serviceRole === 'EMPLOYEE' ? [] : slackOf(id) })
}

/** 담당자가 문의자에게 메시지를 보낸다 (제안). 민감정보는 저장 전에 가린다 */
export async function sendTicketMessage(user: User, id: number, body: { kind: MessageKind; text: string }): Promise<ApiResult<TicketMessage>> {
  if (!USE_MOCK) return request<TicketMessage>(`/tickets/${id}/messages`, { method: 'POST', body: JSON.stringify(body) })
  await sleep(150)
  const t = findStaffTicket(id)
  if (!t || !canSee(user, t)) return notFound()
  if (user.serviceRole === 'EMPLOYEE' || (user.serviceRole === 'AGENT' && t.assignee?.id !== user.id)) return fail('FORBIDDEN', '이 접수에 메시지를 보낼 수 없어요.')
  const text = maskSensitive(body.text.trim()).text
  if (!text) return fail('VALIDATION_ERROR', '내용을 입력해 주세요.')
  addMessage(id, { from: `${t.assignee?.name ?? user.name} 담당자`, kind: body.kind, text, at: nowIso() })
  const rec = recordOfTicket(id)
  if (rec) {
    rec.inquiry.unread += 1 // 문의자의 문의 내역에 새 답변으로 보인다
    notify()
  }
  const list = messagesOf(id)
  return ok(list[list.length - 1])
}
