/** 패널이 사용하는 상태 변경 API가 서버 모드에서 TK-07 계약대로 전송되는지 검증한다. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../src/api/types'
const user = { id: 2, serviceRole: 'AGENT' } as User
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })

async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  return { fetch, ...await import('../src/api/tickets') }
}

describe('상태 변경 서버 요청', () => {
  it.each([
    { workStatus: 'WIP' as const },
    { workStatus: 'FIN' as const, resolutionNote: '계정 잠금 해제 및 로그인 확인' },
  ])('PATCH 요청과 202의 미확정 상태를 그대로 전달한다: %j', async (body) => {
    const { fetch, changeTicketStatus } = await load()
    const pending = { id: 7, workStatus: body.workStatus === 'WIP' ? 'RDY' : 'WIP', requestedWorkStatus: body.workStatus, transitionStatus: 'PENDING' }
    fetch.mockResolvedValue(json(202, pending))
    expect(await changeTicketStatus(user, 7, body)).toEqual({ ok: true, data: pending })
    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/tickets/7')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(String(init.body))).toEqual(body)
  })
  it('권한·충돌 오류를 성공으로 바꾸거나 자동 재전송하지 않는다', async () => {
    const { fetch, changeTicketStatus } = await load()
    fetch.mockResolvedValue(json(409, { error: { code: 'TICKET_INVALID_TRANSITION', message: '이미 상태가 변경됐습니다.' } }))
    expect(await changeTicketStatus(user, 7, { workStatus: 'WIP' })).toMatchObject({ ok: false, error: { code: 'TICKET_INVALID_TRANSITION' } })
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
