/**
 * 실서버 테스트에서 나온 문제: ITSM 에서 직접 담당자를 지정해 배정 상태가 NEEDS_ADMIN 으로 남아도
 * 처리 중·해결 확인 대기·해결 완료 접수는 진행 단계·상태가 업무 상태를 따르고, 해결된 접수는 운영 확인 목록에서 빠진다.
 */
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Inquiry, Ticket } from '../src/api/chatTypes'
import { inquiryState } from '../src/api/inquiryState'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'
import { TicketCard } from '../src/views/inquiry/TicketCard'

const base = (extra: Partial<Ticket> = {}): Ticket => ({
  id: 4,
  receiptNo: 'RCPT-0004',
  jiraKey: 'ITHD-369',
  title: '네트워크 속도 문의',
  categoryCode: 'NET',
  urgency: 'P2',
  groupId: 1,
  groupName: '네트워크팀',
  assigneeId: 9,
  assigneeName: '조민재',
  workStatus: 'FIN',
  assignStatus: 'NEEDS_ADMIN',
  jiraSyncStatus: 'SYNCED',
  createdAt: '2026-11-03T16:43:00+09:00',
  resolutionNote: 'test 처리 완료',
  needReply: false,
  ...extra,
})

describe('배정 상태가 확인 필요로 남은 접수의 진행 단계', () => {
  it('해결 확인 대기: 해결 완료 단계가 현재이고 "운영자 확인 중"이 아니다', () => {
    render(<TicketCard ticket={base()} onResolve={() => {}} onReject={() => {}} />)
    const steps = within(screen.getByRole('list', { name: '접수 진행 단계' })).getAllByRole('listitem')
    expect(steps[3]).toHaveAttribute('aria-current', 'step')
    expect(steps[1]).toHaveTextContent('조민재 담당')
    expect(screen.queryByText(/운영자 확인 중/)).toBeNull()
    expect(screen.getByText(/처리 결과를 등록했어요/)).toBeInTheDocument()
  })

  it('처리 중(WIP): 처리 중 단계가 현재', () => {
    render(<TicketCard ticket={base({ workStatus: 'WIP' })} onResolve={() => {}} onReject={() => {}} />)
    const steps = within(screen.getByRole('list', { name: '접수 진행 단계' })).getAllByRole('listitem')
    expect(steps[2]).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText(/조민재 담당자가 처리하고 있어요/)).toBeInTheDocument()
  })

  it('처리 대기(RDY)만이면 아직 담당자 확인 중으로 본다', () => {
    render(<TicketCard ticket={base({ workStatus: 'RDY' })} onResolve={() => {}} onReject={() => {}} />)
    const steps = within(screen.getByRole('list', { name: '접수 진행 단계' })).getAllByRole('listitem')
    expect(steps[1]).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText(/운영자가 담당자 연결을 확인하고 있어요/)).toBeInTheDocument()
  })

  it('문의 상태 이름도 업무 상태를 따른다', () => {
    const inq = (t: Ticket) => ({ id: 1, status: 'IN_PROGRESS', step: 'handoff', ticket: t, messages: [] }) as unknown as Inquiry
    expect(inquiryState(inq(base())).label).toBe('해결 확인 대기')
    expect(inquiryState(inq(base({ workStatus: 'CLS' }))).label).toBe('해결 완료')
    expect(inquiryState(inq(base({ workStatus: 'RDY' }))).label).toBe('담당자 확인 중')
  })
})

describe('운영 확인 목록에서 해결 완료 접수 제외 (서버 모드)', () => {
  const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const sum = (id: number, over: Record<string, unknown>) => ({ id, receiptNo: `RCPT-000${id}`, jiraKey: null, summary: `접수 ${id}`, category: {code:'NET',name:'VPN·네트워크'}, requester: { id: 1, employeeNo: 'E', name: '문의자' }, urgency: 'P3', group: { id: 1, name: '네트워크팀' }, assignee: null, jiraSyncStatus: 'SYNCED', assignStatus: 'NEEDS_ADMIN', workStatus: 'RDY', transitionStatus: 'IDLE', needsAdmin: true, createdAt: '2026-11-03T10:00:00+09:00', ...over })
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('담당자 배정 확인·배지 건수에서 해결 완료 접수는 빠진다', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
    const items = [sum(3, {}), sum(4, { workStatus: 'CLS' })]
    const page = { items, page: 1, size: 100, totalCount: 2, totalPages: 1 }
    const fetchMock = vi.fn().mockImplementation(async (url) => json(String(url).includes('classificationReportOpen=true') ? {...page,items:[],totalCount:0} : page))
    vi.stubGlobal('fetch', fetchMock)
    const ops = await import('../src/api/ops')
    const snap = await ops.getOpsSnapshot(admin())
    expect(snap.ok && snap.data.assign.map((t) => t.id)).toEqual([3])
    expect(await ops.countOpsAttention(admin())).toBe(1)
  })
})
