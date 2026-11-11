import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'

const admin = MOCK_ACCOUNTS.find((user) => user.serviceRole === 'ADMIN')!
const counts = { new: 2, inReview: 1, closed: 0, openHigh: 1, total: 3 }
const json = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
let fetchMock: ReturnType<typeof vi.fn>
let cleanup: (() => void)[]
beforeEach(() => {
  vi.resetModules(); vi.useFakeTimers(); vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
  fetchMock = vi.fn().mockImplementation(async () => json(counts))
  vi.stubGlobal('fetch', fetchMock)
  cleanup = []
})
afterEach(() => { cleanup.forEach((stop) => stop()); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers() })

describe('보안 자동 조회', () => {
  it('사이드바와 대시보드는 건수 조회 한 번을 공유한다', async () => {
    const api = await import('../src/api/security')
    const a = vi.fn(), b = vi.fn()
    cleanup.push(api.watchSecurityCounts(admin, a), api.watchSecurityCounts(admin, b))
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(a).toHaveBeenCalledWith({ 신규: 2, '확인 중': 1, 종결: 0, high: 1, total: 3 })
    expect(b).toHaveBeenCalledTimes(1)
  })

  it('느린 목록 조회는 중첩하지 않고 탭 복귀 뒤 최신 조회를 예약한다', async () => {
    const api = await import('../src/api/security')
    let done!: () => void
    const first = new Promise<void>((resolve) => { done = resolve })
    const load = vi.fn().mockReturnValueOnce(first).mockResolvedValue(undefined)
    let visibility = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility as DocumentVisibilityState)
    cleanup.push(api.watchSecurity(load))
    await vi.advanceTimersByTimeAsync(90_000)
    expect(load).toHaveBeenCalledTimes(1)
    visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(90_000)
    expect(load).toHaveBeenCalledTimes(1)
    visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange'))
    done(); await vi.advanceTimersByTimeAsync(0)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('목록과 로그인 안내의 동시 건수 요청도 진행 중 응답을 공유한다', async () => {
    const api = await import('../src/api/security')
    let done!: (response: Response) => void
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { done = resolve }))
    const a = api.countSecurityAlerts(admin), b = api.countSecurityAlerts(admin)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    done(json(counts))
    expect(await a).toEqual(await b)
  })
})
