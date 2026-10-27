/**
 * 실제 서버 모드(VITE_USE_MOCK_AUTH=false) 인증 API 테스트.
 * 서버는 띄우지 않고 가짜 fetch 로 서버 계약(docs/api/01, docs/07 5장)대로 응답을 만들어 준다.
 * 모듈은 환경 값을 읽은 뒤 고정되므로, 테스트마다 모듈을 새로 불러온다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const errorBody = (code: string, message = '서버 문구', details: unknown = null) => ({ error: { code, message, details, traceId: 't-1' } })

const ME = {
  id: 7,
  employeeNo: 'E2024017',
  name: '김서연',
  email: 'a@b.c',
  departmentId: 11,
  department: { id: 11, name: '개발1팀' },
  position: '팀원',
  serviceRole: 'EMPLOYEE',
  accountStatus: 'ACTIVE',
  passwordChangeRequired: true,
  lastLoginAt: null,
  supportGroups: [],
}
const TOKENS = (token: string) => ({ accessToken: token, tokenType: 'Bearer', expiresIn: 1800, user: ME })

let fetchMock: ReturnType<typeof vi.fn>

/** 서버 모드로 모듈을 새로 불러온다 */
async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_AUTH', 'false')
  const { authApi } = await import('../src/api/auth')
  const { setAuthLostHandler } = await import('../src/core/apiClient')
  const { tokenStore } = await import('../src/core/tokenStore')
  return { authApi, setAuthLostHandler, tokenStore }
}

const calls = () => fetchMock.mock.calls.map((c) => ({ url: String(c[0]), init: c[1] as RequestInit }))
const auth = (init: RequestInit) => new Headers(init.headers).get('Authorization')

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('서버 모드 로그인', () => {
  it('서버의 내 정보를 화면의 사용자로 바꾸고, 쿠키를 함께 보낸다', async () => {
    const { authApi } = await load()
    fetchMock.mockResolvedValueOnce(json(200, TOKENS('tok-1')))
    const r = await authApi.login({ employeeNo: 'E2024017', password: 'x' })
    expect(r).toMatchObject({ ok: true, data: { accessToken: 'tok-1', user: { employeeNo: 'E2024017', departmentName: '개발1팀', serviceRole: 'EMPLOYEE', passwordChangeRequired: true } } })
    const [c] = calls()
    expect(c.url).toBe('/api/v1/auth/login')
    expect(c.init.credentials).toBe('include')
  })

  it('소속이 없는 사용자도 부서 이름을 빈 값으로 받는다', async () => {
    const { authApi } = await load()
    fetchMock.mockResolvedValueOnce(json(200, { ...TOKENS('tok-1'), user: { ...ME, department: null, departmentId: null } }))
    const r = await authApi.login({ employeeNo: 'E2024017', password: 'x' })
    expect(r.ok && r.data.user.departmentName).toBe('')
  })

  it('잘못된 사번·비밀번호는 가이드 문구로 바꿔 알린다', async () => {
    const { authApi } = await load()
    fetchMock.mockResolvedValueOnce(json(401, errorBody('AUTH_INVALID_CREDENTIALS', '사번 또는 비밀번호가 올바르지 않습니다.')))
    const r = await authApi.login({ employeeNo: 'x', password: 'y' })
    expect(r).toMatchObject({ ok: false, error: { code: 'AUTH_INVALID_CREDENTIALS', message: '사번 또는 비밀번호를 확인해 주세요.' } })
  })

  it('잠긴 계정은 서버가 준 해제 시각으로 남은 분을 알린다', async () => {
    const { authApi } = await load()
    const until = new Date(Date.now() + 7 * 60_000 + 30_000).toISOString()
    fetchMock.mockResolvedValueOnce(json(403, errorBody('AUTH_ACCOUNT_LOCKED', '잠김', [{ reason: 'LOCKED_UNTIL', message: '잠금 해제 시각', value: until }])))
    const r = await authApi.login({ employeeNo: 'x', password: 'y' })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error.message).toContain('약 8분 후 자동으로 해제돼요')
      expect(r.error.lockedUntil).toBe(until)
    }
  })

  it('서버에 닿지 못하면 연결 실패로 알린다', async () => {
    const { authApi } = await load()
    fetchMock.mockRejectedValueOnce(new TypeError('failed'))
    const r = await authApi.login({ employeeNo: 'x', password: 'y' })
    expect(r).toMatchObject({ ok: false, error: { code: 'NETWORK_ERROR' } })
  })
})

describe('서버 모드 비밀번호 변경 · 로그아웃', () => {
  it('204 는 성공이고, 규칙 위반의 상세 문구를 그대로 전달한다', async () => {
    const { authApi, tokenStore } = await load()
    tokenStore.set('tok-1')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    expect(await authApi.changePassword({ currentPassword: 'a', newPassword: 'b' })).toEqual({ ok: true, data: null })
    expect(calls()[0].url).toBe('/api/v1/users/me/password')
    expect(calls()[0].init.method).toBe('PUT')
    expect(auth(calls()[0].init)).toBe('Bearer tok-1')

    const detail = { field: 'newPassword', reason: 'TOO_SHORT', message: '8자 이상 입력해 주세요.' }
    fetchMock.mockResolvedValueOnce(json(422, errorBody('AUTH_PASSWORD_POLICY_VIOLATION', '규칙', [detail])))
    const r = await authApi.changePassword({ currentPassword: 'a', newPassword: 'b' })
    expect(r).toMatchObject({ ok: false, error: { code: 'AUTH_PASSWORD_POLICY_VIOLATION', details: [detail] } })
  })

  it('로그아웃은 서버에 알린다', async () => {
    const { authApi, tokenStore } = await load()
    tokenStore.set('tok-1')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    authApi.logout()
    expect(calls()[0].url).toBe('/api/v1/auth/logout')
    expect(calls()[0].init.method).toBe('POST')
    expect(auth(calls()[0].init)).toBe('Bearer tok-1')
  })
})

describe('토큰 만료와 재발급', () => {
  it('만료되면 재발급을 한 번 하고, 새 토큰으로 같은 요청을 다시 보낸다', async () => {
    const { authApi, tokenStore } = await load()
    tokenStore.set('old')
    fetchMock
      .mockResolvedValueOnce(json(401, errorBody('TOKEN_EXPIRED')))
      .mockResolvedValueOnce(json(200, TOKENS('new')))
      .mockResolvedValueOnce(json(200, ME))
    const r = await authApi.me()
    expect(r.ok && r.data.employeeNo).toBe('E2024017')
    const c = calls()
    expect(c.map((x) => x.url)).toEqual(['/api/v1/users/me', '/api/v1/auth/refresh', '/api/v1/users/me'])
    expect(auth(c[0].init)).toBe('Bearer old')
    expect(auth(c[2].init)).toBe('Bearer new')
    expect(tokenStore.get()).toBe('new')
  })

  it('동시에 만료된 요청이 여러 개여도 재발급은 한 번만 한다', async () => {
    const { authApi, tokenStore } = await load()
    tokenStore.set('old')
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (String(url).endsWith('/auth/refresh')) return json(200, TOKENS('new'))
      return auth(init) === 'Bearer new' ? json(200, ME) : json(401, errorBody('TOKEN_EXPIRED'))
    })
    const [a, b] = await Promise.all([authApi.me(), authApi.me()])
    expect(a.ok && b.ok).toBe(true)
    expect(calls().filter((x) => x.url.endsWith('/auth/refresh'))).toHaveLength(1)
  })

  it('재발급이 실패하면 로그인이 끊겼다고 알리고, 원래 실패를 돌려준다', async () => {
    const { authApi, tokenStore, setAuthLostHandler } = await load()
    const lost = vi.fn()
    setAuthLostHandler(lost)
    tokenStore.set('old')
    fetchMock.mockResolvedValueOnce(json(401, errorBody('TOKEN_EXPIRED'))).mockResolvedValueOnce(json(401, errorBody('AUTH_REFRESH_TOKEN_INVALID')))
    const r = await authApi.me()
    expect(r).toMatchObject({ ok: false, error: { code: 'TOKEN_EXPIRED' } })
    expect(lost).toHaveBeenCalledTimes(1)
    expect(calls()).toHaveLength(2) // 재시도는 하지 않는다
  })

  it('폐기된 토큰(UNAUTHORIZED)은 재발급 없이 로그인이 끊긴 것으로 본다', async () => {
    const { authApi, tokenStore, setAuthLostHandler } = await load()
    const lost = vi.fn()
    setAuthLostHandler(lost)
    tokenStore.set('old')
    fetchMock.mockResolvedValueOnce(json(401, errorBody('UNAUTHORIZED')))
    await authApi.me()
    expect(lost).toHaveBeenCalledTimes(1)
    expect(calls()).toHaveLength(1)
  })

  it('로그인 자체의 401 은 재발급이나 끊김 처리를 하지 않는다', async () => {
    const { authApi, setAuthLostHandler } = await load()
    const lost = vi.fn()
    setAuthLostHandler(lost)
    fetchMock.mockResolvedValueOnce(json(401, errorBody('AUTH_INVALID_CREDENTIALS')))
    await authApi.login({ employeeNo: 'x', password: 'y' })
    expect(lost).not.toHaveBeenCalled()
    expect(calls()).toHaveLength(1)
  })
})
