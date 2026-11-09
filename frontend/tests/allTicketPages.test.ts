import { afterEach, expect, it, vi } from 'vitest'
import type { User } from '../src/api/types'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

it('전체 조회는 조건을 유지하고 다음 페이지를 합치며 중복 접수를 한 번만 센다', async () => {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
  const fetcher = vi.fn(async (url: string) => {
    const q = new URL(url, 'http://test').searchParams
    expect(q.get('needsAdmin')).toBe('true')
    const items = q.get('page') === '1' ? [{ id: 1 }] : [{ id: 1 }, { id: 2 }]
    return new Response(JSON.stringify({ items, totalPages: 2, totalCount: 2 }), { status: 200 })
  })
  vi.stubGlobal('fetch', fetcher)
  const { listAllTickets } = await import('../src/api/tickets')
  const r = await listAllTickets({} as User, { view: 'ALL', needsAdmin: true })
  expect(r.ok && r.data.items.map((t) => t.id)).toEqual([1, 2])
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('다음 페이지가 실패하면 부분 집계를 반환하지 않는다', async () => {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 1 }], totalPages: 2 }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'FORBIDDEN', message: '거절' } }), { status: 403 })))
  const { listAllTickets } = await import('../src/api/tickets')
  expect((await listAllTickets({} as User)).ok).toBe(false)
})
