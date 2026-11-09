/**
 * 화면 알림(NT-01~04)과 새로고침 동기화(TK-14) 연결 (서버 모드, 가짜 fetch).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
let fetchMock: ReturnType<typeof vi.fn>
const calls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0])}`)

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_NOTIFY', 'false')
  vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
  vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('알림 API', () => {
  it('안 읽은 개수·목록·접수 단위 읽음을 서버 경로로 부른다', async () => {
    const api = await import('../src/api/notifications')
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes('unread-count')) return json({ count: 2, ticketIds: [42, 57] })
      if (String(url).includes('/notifications/read')) return json({ updatedCount: 2 })
      return json({ items: [{ id: 1, kind: 'FIN', ticketId: 42, inquiryId: 7, receiptNo: 'RCPT-0042', summary: null, readAt: null, createdAt: 't' }], page: 1, size: 100, totalCount: 1, totalPages: 1 })
    })
    expect((await api.getUnreadCount()).ok && 'ok').toBe('ok')
    const list = await api.listUnread()
    expect(list.ok && list.data[0].inquiryId).toBe(7)
    const read = await api.markTicketRead(42)
    expect(read.ok && read.data.updatedCount).toBe(2)
    expect(calls()).toEqual(['GET /api/v1/notifications/unread-count', 'GET /api/v1/notifications?unreadOnly=true&size=100', 'POST /api/v1/notifications/read'])
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toEqual({ ticketId: 42 })
  })

  it('개수가 바뀔 때만 알리고, 1분마다 읽는다', async () => {
    const api = await import('../src/api/notifications')
    let n = 1
    fetchMock.mockImplementation(async () => json({ count: n, ticketIds: [n] }))
    const seen: number[] = []
    const off = api.watchUnread((c) => seen.push(c.count))
    await vi.advanceTimersByTimeAsync(10)
    await vi.advanceTimersByTimeAsync(60_000) // 같은 값
    expect(seen).toEqual([1])
    n = 2
    await vi.advanceTimersByTimeAsync(60_000)
    expect(seen).toEqual([1, 2])
    off()
  })
})

describe('사이드바 최근 문의의 새 소식 표시', () => {
  it('처리 완료 알림이 안 읽힌 문의에는 unread 가 켜진다', async () => {
    const { listMyInquiries } = await import('../src/api/inquiries')
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).startsWith('/api/v1/notifications')) {
        return json({ items: [{ id: 1, kind: 'FIN', ticketId: 42, inquiryId: 7, receiptNo: 'RCPT-0042', summary: null, readAt: null, createdAt: 't' }], page: 1, size: 100, totalCount: 1, totalPages: 1 })
      }
      return json({
        items: [
          { id: 7, title: '문의 7', displayStatus: 'awaiting_confirm', updatedAt: '2026-11-03T10:00:00+09:00' },
          { id: 8, title: '문의 8', displayStatus: 'in_progress', updatedAt: '2026-11-03T09:00:00+09:00' },
        ],
        page: 1, size: 5, totalCount: 2, totalPages: 1,
      })
    })
    const r = await listMyInquiries('EMP-1001')
    expect(r.ok && r.data.map((i) => [i.id, i.unread])).toEqual([[7, 1], [8, 0]])
  })
})

describe('새로고침 동기화 (TK-14)', () => {
  it('POST /tickets/{id}/sync 로 부른다', async () => {
    const { syncTicket } = await import('../src/api/tickets')
    fetchMock.mockResolvedValueOnce(json({ id: 42, workStatus: 'FIN' }))
    const r = await syncTicket({ id: 1, employeeNo: 'EMP-1', name: 'x', serviceRole: 'AGENT' } as never, 42)
    expect(r.ok && (r.data as { workStatus: string }).workStatus).toBe('FIN')
    expect(calls()).toEqual(['POST /api/v1/tickets/42/sync'])
  })
})
