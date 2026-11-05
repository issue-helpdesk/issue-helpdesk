/**
 * 계정 변경 이력 (R-14): 서버 모드는 운영 기록(OP-04)의 `targetType=user` 기록을 읽는다.
 * 수행자(actor)와 변경 대상 사용자는 다른 사람이라 따로 둔다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../src/api/types'

const admin = { id: 3, employeeNo: 'EMP-1178', name: '이건우', serviceRole: 'ADMIN' } as User
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const log = (id: number, over: Record<string, unknown> = {}) => ({ id, eventType: 'USER_STATUS_CHANGE', targetType: 'user', targetId: 21, actorId: 3, actor: { id: 3, employeeNo: 'EMP-1178', name: '이건우' }, result: 'INACTIVE', reason: '퇴사 예정', createdAt: '2026-11-05T09:00:00+09:00', ...over })

describe('계정 변경 이력 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })
  async function load() {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_AUTH', 'false')
    vi.stubEnv('VITE_USE_MOCK_OPS', 'false')
    return import('../src/api/users')
  }

  it('대상이 사용자인 운영 기록을 최근순으로 읽어, 수행자와 대상을 구분해 화면 말로 바꾼다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(
      json(200, {
        items: [
          log(9),
          log(8, { eventType: 'USER_ROLE_CHANGE', targetId: 22, result: 'AGENT', reason: '담당자 전환' }),
          log(7, { eventType: 'ACCOUNT_LOCKED', targetId: 23, actor: null, actorId: null, result: null, reason: null }),
        ],
        page: 1,
        size: 12,
        totalCount: 3,
        totalPages: 1,
      }),
    )
    const r = await api.listAccountHistory(admin)
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/audit-logs?page=1&size=12&sort=createdAt%2Cdesc&targetType=user')
    expect(r.ok && r.data.map((h) => [h.what, h.who, h.targetId, h.why])).toEqual([
      ['계정 상태 변경', '이건우', 21, '상태 → 이용 제한 · 사유: 퇴사 예정'],
      ['역할 변경', '이건우', 22, '역할 → 담당자 · 사유: 담당자 전환'],
      ['계정 잠김', '시스템', 23, '연속 실패로 잠김'], // 시스템이 한 일은 수행자가 없다
    ])
    // 서버는 대상 이름을 주지 않아서(R-42) 화면이 목록에서 이름을 찾을 때까지 번호로 보인다. 색은 이벤트가 정한다
    expect(r.ok && r.data[0]).toMatchObject({ target: '사용자 #21', tone: 'warn' })
  })

  it('운영 기록을 못 읽으면 오류를 그대로 돌려준다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(403, { error: { code: 'FORBIDDEN', message: '관리자만 볼 수 있어요.', details: null, traceId: 't' } }))
    const r = await api.listAccountHistory(admin)
    expect(r).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
  })
})

describe('계정 변경 이력 (모의 모드)', () => {
  it('이 화면에서 한 일의 기록을 그대로 돌려준다', async () => {
    vi.resetModules()
    const api = await import('../src/api/users')
    api.recordAccountHistory({ who: '이건우', target: 'EMP-1001 · 김서연', what: '이용 제한', why: '테스트' })
    const r = await api.listAccountHistory(admin)
    expect(r.ok && r.data[0]).toMatchObject({ what: '이용 제한', who: '이건우', target: 'EMP-1001 · 김서연' })
  })
})
