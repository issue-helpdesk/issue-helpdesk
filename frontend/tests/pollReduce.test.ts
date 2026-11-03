/**
 * 쓸데없는 주기 조회 줄이기 (서버 모드).
 * - 바뀔 일이 없는 문의(종료됨·접수 없음)는 대화 화면을 열어 둬도 계속 읽지 않는다.
 * - 대화 화면이 열려 있으면 사이드바 목록은 드물게만 읽고, 화면이 먼저 안 변화는 바로 알려 준다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.doUnmock('../src/api/inquiryServer')
})

const inquiry = (over: Record<string, unknown>) => ({ ok: true, data: { id: 1, title: 't', status: 'IN_PROGRESS', step: 'collect', unread: 0, messages: [], ticket: null, ...over } })

async function chatWith(result: ReturnType<typeof inquiry>) {
  const loadInquiry = vi.fn().mockResolvedValue(result)
  vi.doMock('../src/api/inquiryServer', async (orig) => ({ ...(await orig<object>()), loadInquiry }))
  const chat = await import('../src/api/chat')
  return { chat, loadInquiry }
}

describe('대화 화면 주기 조회 (watchChat)', () => {
  it('종료됐고 접수가 없는 문의는 처음 한 번 읽은 뒤 더 읽지 않는다', async () => {
    const { chat, loadInquiry } = await chatWith(inquiry({ step: 'closed', status: 'CLOSED_UNRESOLVED' }))
    const off = chat.watchChat(1, 'EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(120_000)
    expect(loadInquiry).toHaveBeenCalledTimes(1)
    off()
  })

  it('접수 전 문의는 10초마다가 아니라 1분에 한 번만 읽는다', async () => {
    const { chat, loadInquiry } = await chatWith(inquiry({ step: 'collect' }))
    const off = chat.watchChat(1, 'EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(120_000)
    // 처음 한 번 + 1분마다 한 번 (예전에는 12번)
    expect(loadInquiry.mock.calls.length).toBeLessThanOrEqual(3)
    expect(loadInquiry.mock.calls.length).toBeGreaterThanOrEqual(2)
    off()
  })

  it('접수가 있는 처리 중 문의는 10초마다 읽는다', async () => {
    const ticket = { receiptNo: 'RCPT-1', workStatus: 'WIP' }
    const { chat, loadInquiry } = await chatWith(inquiry({ step: 'submitted', ticket }))
    const off = chat.watchChat(1, 'EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(60_000)
    expect(loadInquiry.mock.calls.length).toBeGreaterThanOrEqual(6)
    off()
  })

  it('pollMode: 해결 완료·종료는 멈추고, 접수 전은 느리게, 처리 중은 그대로', async () => {
    const { chat } = await chatWith(inquiry({}))
    const base = inquiry({}).data as never
    expect(chat.pollMode({ ...(base as object), step: 'closed', ticket: null } as never)).toBe('stop')
    expect(chat.pollMode({ ...(base as object), step: 'closed', ticket: { workStatus: 'CLS' } } as never)).toBe('stop')
    expect(chat.pollMode({ ...(base as object), step: 'answering', ticket: null } as never)).toBe('normal')
    expect(chat.pollMode({ ...(base as object), step: 'draft', ticket: null } as never)).toBe('slow')
    expect(chat.pollMode({ ...(base as object), step: 'submitted', ticket: { workStatus: 'FIN' } } as never)).toBe('normal')
    expect(chat.pollMode({ ...(base as object), step: 'collect', ticket: null, paused: true } as never)).toBe('slow')
  })
})

describe('사이드바 문의 목록 주기 조회 (watchMyInquiries)', () => {
  const page = { items: [], page: 1, size: 100, totalCount: 0, totalPages: 1 }

  it('주기 조회는 2분에 한 번뿐이고, 대화 화면이 열려 있으면 처음 한 번 뒤로는 읽지 않는다', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => json(page))
    vi.stubGlobal('fetch', fetchMock)
    const { watchMyInquiries } = await import('../src/api/inquiries')
    const { pollHints } = await import('../src/core/poll')

    const off1 = watchMyInquiries('EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(240_000)
    const alone = fetchMock.mock.calls.length // 처음 1번 + 2분마다 2번
    off1()

    fetchMock.mockClear()
    pollHints.chatViews = 1
    const off2 = watchMyInquiries('EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(240_000)
    const withChat = fetchMock.mock.calls.length // 처음 1번뿐
    off2()
    pollHints.chatViews = 0

    expect(alone).toBeGreaterThanOrEqual(3)
    expect(alone).toBeLessThanOrEqual(6) // 예전(20초)에는 13번이었다
    expect(withChat).toBeLessThan(alone)
  })

  it('대화 화면이 먼저 안 변화는 목록을 곧바로 다시 읽게 한다', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => json(page))
    vi.stubGlobal('fetch', fetchMock)
    const { watchMyInquiries } = await import('../src/api/inquiries')
    const { refreshInquiryList } = await import('../src/core/poll')
    const off = watchMyInquiries('EMP-1001', () => {})
    await vi.advanceTimersByTimeAsync(10)
    const n = fetchMock.mock.calls.length
    refreshInquiryList()
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock.mock.calls.length).toBeGreaterThan(n)
    off()
  })
})
