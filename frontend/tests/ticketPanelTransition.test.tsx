/** 서버 응답을 대체하여 요청·확정·Jira 직접 변경·실패의 화면 계약을 검증한다. */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TicketDetailPanel } from '../src/views/staff/TicketDetailPanel'
import { TicketWorkActions } from '../src/views/staff/TicketWorkActions'
import type { TicketDetail, StatusHistory } from '../src/api/ticketTypes'
import { ok, fail, type User } from '../src/api/types'

const api = vi.hoisted(() => ({
  getTicket: vi.fn(), syncTicket: vi.fn(), getTicketHistory: vi.fn(), getAssignmentLogs: vi.fn(),
  changeTicketStatus: vi.fn(), refreshTickets: vi.fn(),
}))
const auth = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../src/api/tickets', () => api)
vi.mock('../src/core/session', () => ({ useAuth: () => auth }))
vi.mock('../src/core/config', async (original) => ({ ...await original<object>(), USE_MOCK_TICKET: false }))
vi.mock('../src/api/notifications', () => ({ markTicketRead: async () => ok({ updatedCount: 0 }), refreshUnread: vi.fn() }))
vi.mock('../src/views/staff/AssessmentHistory', () => ({ AssessmentHistory: () => null }))
vi.mock('../src/views/staff/QueueView', () => ({ UrgencyChip: () => null }))
vi.mock('../src/views/admin/ReassignDialog', () => ({ ReassignDialog: () => null }))
vi.mock('../src/ui/useToast', () => ({ useToast: () => ({ say: vi.fn() }) }))

const agent: User = { id: 2, employeeNo: 'EMP-2', name: '담당자', serviceRole: 'AGENT', departmentId: 1, departmentName: '서비스데스크', accountStatus: 'ACTIVE' }
const base: TicketDetail = {
  id: 7, inquiryId: 1, receiptNo: 'RCPT-0007', jiraKey: 'ITHD-7', summary: '계정 잠금 문의',
  requester: { id: 3, employeeNo: 'EMP-3', name: '문의자' }, assignee: agent,
  category: null, urgency: 'P3', group: { id: 1, name: '서비스데스크' },
  jiraSyncStatus: 'SYNCED', assignStatus: 'ASSIGNED', workStatus: 'RDY',
  requestedWorkStatus: null, transitionStatus: 'IDLE', workStatusConfirmedAt: null,
  needsAdmin: false, displayStatus: 'progress', createdAt: '2026-11-06T09:00:00+09:00',
  targetSystem: null, symptom: null, occurredAt: null, inquiryType: null, urgencyReason: null,
  businessImpact: null, triedActions: null, jiraUrl: null, resolutionNote: null, finishedAt: null, closedAt: null,
}
let latest: TicketDetail
let history: StatusHistory[]
const panel = (tick = 0) => <MemoryRouter><TicketDetailPanel id={7} tick={tick} onClose={() => {}} /></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  latest = { ...base }
  history = []
  auth.user = agent
  api.getTicket.mockImplementation(async () => ok({ ...latest }))
  api.syncTicket.mockImplementation(async () => ok({ ...latest }))
  api.getTicketHistory.mockImplementation(async () => ok({ items: history }))
  api.getAssignmentLogs.mockResolvedValue(ok({ items: [] }))
})
afterEach(() => vi.useRealTimers())

describe('패널의 서버 상태 변경', () => {
  it('202 이후에도 기존 상태를 유지하고, 조회로 확정된 뒤 이력과 목록을 갱신한다', async () => {
    api.changeTicketStatus.mockImplementation(async () => {
      latest = { ...latest, requestedWorkStatus: 'WIP', transitionStatus: 'PENDING' }
      return ok(latest)
    })
    const view = render(panel())
    await userEvent.click(await screen.findByRole('button', { name: '처리 시작' }))
    expect(api.changeTicketStatus).toHaveBeenCalledExactlyOnceWith(agent, 7, { workStatus: 'WIP' })
    expect(screen.getByRole('button', { name: '처리 시작' })).toBeDisabled()
    expect(screen.queryByLabelText(/처리 결과/)).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('ITSM 시스템 반영을 확인하고 있어요')
    const refreshes = api.refreshTickets.mock.calls.length
    latest = { ...latest, workStatus: 'WIP', requestedWorkStatus: null, transitionStatus: 'IDLE' }
    history = [{ id: 1, ticketId: 7, fromStatus: 'RDY', toStatus: 'WIP', source: 'ITSSUE', actor: agent, reason: null, changedAt: '2026-11-06T09:01:00+09:00' }]
    view.rerender(panel(1))
    expect(await screen.findByRole('button', { name: '처리 완료' })).toBeEnabled()
    expect(await screen.findByText('처리 대기 → 처리 중')).toBeInTheDocument()
    await waitFor(() => expect(api.refreshTickets.mock.calls.length).toBeGreaterThan(refreshes))
  })

  it('요청 전에 시작한 조회가 늦게 도착해도 반영 중 상태를 되돌리지 않는다', async () => {
    const view = render(panel())
    await screen.findByRole('button', { name: '처리 시작' })
    let finishOldRead!: (value: ReturnType<typeof ok<TicketDetail>>) => void
    api.getTicket.mockImplementationOnce(() => new Promise((done) => { finishOldRead = done }))
    view.rerender(panel(1))
    await waitFor(() => expect(api.getTicket).toHaveBeenCalledTimes(2))
    api.changeTicketStatus.mockImplementation(async () => {
      latest = { ...latest, transitionStatus: 'PENDING', requestedWorkStatus: 'WIP' }
      return ok(latest)
    })
    await userEvent.click(screen.getByRole('button', { name: '처리 시작' }))
    await act(async () => finishOldRead(ok(base)))
    expect(screen.getByRole('button', { name: '처리 시작' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('ITSM 시스템 반영을 확인하고 있어요')
  })

  it('반영 중에는 3초마다 확인하고, 확인 필요 상태가 되면 잠금을 유지하고 조회 주기를 멈춘다', async () => {
    latest = { ...base, transitionStatus: 'PENDING', requestedWorkStatus: 'WIP' }
    vi.useFakeTimers()
    await act(async () => { render(panel()) })
    expect(screen.getByRole('button', { name: '처리 시작' })).toBeDisabled()
    const reads = api.getTicket.mock.calls.length
    latest = { ...latest, transitionStatus: 'NEEDS_ADMIN', needsAdmin: true }
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(api.getTicket.mock.calls.length).toBeGreaterThan(reads)
    expect(screen.getByRole('button', { name: '처리 시작' })).toBeDisabled()
    expect(screen.getByText('ITSM 동기화 확인 필요')).toBeInTheDocument()
    const stopped = api.getTicket.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(api.getTicket).toHaveBeenCalledTimes(stopped)
  })

  it('Jira에서 직접 완료한 상태와 처리 결과도 재조회로 표시한다', async () => {
    latest = { ...base, workStatus: 'WIP' }
    const view = render(panel())
    expect(await screen.findByRole('button', { name: '처리 완료' })).toBeInTheDocument()
    latest = { ...latest, workStatus: 'FIN', resolutionNote: 'Jira에서 잠금 해제 완료', displayStatus: 'awaiting_confirm' }
    view.rerender(panel(1))
    expect(await screen.findByText('Jira에서 잠금 해제 완료')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '처리 완료' })).toBeNull()
    expect(api.changeTicketStatus).not.toHaveBeenCalled()
  })

  it('요청 실패 시 상태를 확정하지 않고 오류와 입력한 처리 결과를 유지한다', async () => {
    latest = { ...base, workStatus: 'WIP' }
    api.changeTicketStatus.mockResolvedValue(fail('INTEGRATION_JOB_IN_PROGRESS', '다른 변경이 진행 중입니다.'))
    render(panel())
    await userEvent.click(await screen.findByRole('button', { name: '처리 완료' }))
    const note = await screen.findByRole('textbox', { name: /처리 결과/ })
    await userEvent.type(note, '계정 잠금을 해제했습니다.')
    await userEvent.click(screen.getByRole('button', { name: '등록하고 해결 확인 요청' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 변경이 진행 중')
    expect(note).toHaveValue('계정 잠금을 해제했습니다.')
    expect(api.changeTicketStatus).toHaveBeenCalledWith(agent, 7, { workStatus: 'FIN', resolutionNote: '계정 잠금을 해제했습니다.' })
    expect(api.refreshTickets).toHaveBeenCalled()
  })
})

describe('긴급도 표시', () => {
  it('담당자에게는 긴급도와 사유(P1 같은 코드는 한글 이름으로)를 보이고, 문의자에게는 긴급도 칸이 없다', async () => {
    latest = { ...base, urgency: 'P1', urgencyReason: '통합 로그인(SSO) 장애 기본 긴급도 P1에서 시작해요.' }
    const staff = render(panel())
    expect(await screen.findByText('긴급도')).toBeInTheDocument()
    expect(screen.getByText('통합 로그인(SSO) 장애 기본 긴급도 긴급에서 시작해요.')).toBeInTheDocument()
    expect(screen.queryByText(/P1/)).toBeNull()
    staff.unmount()
    auth.user = { ...agent, serviceRole: 'EMPLOYEE' }
    render(panel())
    await screen.findByText('계정 잠금 문의', undefined, { timeout: 3000 }).catch(() => undefined)
    await waitFor(() => expect(api.getTicket).toHaveBeenCalled())
    await screen.findByText('접수번호')
    expect(screen.queryByText('긴급도')).toBeNull()
    expect(screen.queryByText(/기본 긴급도/)).toBeNull()
  })
})

describe('처리 동작의 노출·입력 제한', () => {
  it.each(['EMPLOYEE', 'ADMIN'] as const)('%s에게 담당자 처리 버튼을 표시하지 않는다', (serviceRole) => {
    render(<TicketWorkActions ticket={base} user={{ ...agent, serviceRole }} onRequested={vi.fn()} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
  it('다른 담당자에게 처리 버튼을 표시하지 않는다', () => {
    render(<TicketWorkActions ticket={base} user={{ ...agent, id: 99 }} onRequested={vi.fn()} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
  it.each([
    { jiraSyncStatus: 'PENDING' }, { assignStatus: 'PENDING' },
    { transitionStatus: 'PENDING' }, { transitionStatus: 'NEEDS_ADMIN' },
  ] as const)('연동·배정·상태 변경이 미확정이면 실행할 수 없다: %j', (over) => {
    render(<TicketWorkActions ticket={{ ...base, ...over }} user={agent} onRequested={vi.fn()} />)
    expect(screen.getByRole('button', { name: '처리 시작' })).toBeDisabled()
  })
  it('공백 결과는 전송하지 않고, 전송 중 재클릭을 차단한다', async () => {
    let resolve!: (value: ReturnType<typeof ok<TicketDetail>>) => void
    api.changeTicketStatus.mockImplementation(() => new Promise((done) => { resolve = done }))
    const onRequested = vi.fn()
    render(<TicketWorkActions ticket={{ ...base, workStatus: 'WIP' }} user={agent} onRequested={onRequested} />)
    await userEvent.click(screen.getByRole('button', { name: '처리 완료' }))
    await userEvent.type(screen.getByRole('textbox', { name: /처리 결과/ }), '   ')
    await userEvent.click(screen.getByRole('button', { name: '등록하고 해결 확인 요청' }))
    expect(api.changeTicketStatus).not.toHaveBeenCalled()
    await userEvent.type(screen.getByRole('textbox', { name: /처리 결과/ }), '잠금 해제 완료')
    await userEvent.click(screen.getByRole('button', { name: '등록하고 해결 확인 요청' }))
    await userEvent.click(screen.getByRole('button', { name: '요청 중…' }))
    expect(api.changeTicketStatus).toHaveBeenCalledTimes(1)
    await act(async () => resolve(ok({ ...base, workStatus: 'WIP', transitionStatus: 'PENDING', requestedWorkStatus: 'FIN' })))
    expect(onRequested).toHaveBeenCalledWith(expect.objectContaining({ workStatus: 'WIP', transitionStatus: 'PENDING' }))
  })
})
