/**
 * 관리자도 본인이 쓴 문의만 사이드바·문의 내역에 보인다(서버는 사용자를 지정하지 않으면 모든 사용자의 문의를 준다)와,
 * 해결·미해결 버튼이 같은 기본 모양인지 확인한다.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Ticket } from '../src/api/chatTypes'
import { TicketCard } from '../src/views/inquiry/TicketCard'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const page = { items: [], page: 1, size: 5, totalCount: 0, totalPages: 0 }

describe('내 문의 목록 요청 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const urls = () => fetchMock.mock.calls.map((c) => String(c[0]))
  async function load() {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    vi.stubEnv('VITE_USE_MOCK_NOTIFY', 'true')
    return import('../src/api/inquiries')
  }
  beforeEach(() => {
    fetchMock = vi.fn().mockImplementation(async () => json(page))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('관리자는 본인 번호를 보내 내 문의만 받고, 관리자가 아니면 보내지 않는다', async () => {
    const api = await load()
    await api.listMyInquiries('EMP-1178', 7)
    await api.listMyInquiries('EMP-1001')
    await api.listInquiries('EMP-1178', { userId: 7, q: '프린터' })
    await api.listInquiries('EMP-1001', { q: '프린터' })
    const u = urls()
    expect(u[0]).toContain('userId=7')
    expect(u[1]).not.toContain('userId')
    expect(u[2]).toContain('userId=7')
    expect(u[3]).not.toContain('userId')
  })
})

const fin = (): Ticket => ({
  id: 7,
  receiptNo: 'RCPT-0007',
  jiraKey: 'ITHD-7',
  title: '네트워크 속도 문의',
  categoryCode: 'NET',
  urgency: 'P3',
  groupId: 1,
  groupName: '네트워크팀',
  assigneeId: 2,
  assigneeName: '김담당',
  workStatus: 'FIN',
  assignStatus: 'ASSIGNED',
  jiraSyncStatus: 'SYNCED',
  createdAt: '2026-11-03T09:00:00+09:00',
  resolutionNote: '조치했어요.',
  needReply: false,
})

describe('해결·미해결 버튼', () => {
  it('둘 다 같은 기본 버튼 모양이다 (해결만 분홍 상자로 선택된 것처럼 보이지 않는다)', () => {
    render(<TicketCard ticket={fin()} onResolve={() => {}} onReject={() => {}} />)
    expect(screen.getByRole('button', { name: '해결' }).className).toBe(screen.getByRole('button', { name: '미해결' }).className)
    expect(screen.getByRole('button', { name: '해결' })).not.toHaveClass('on')
  })
})
