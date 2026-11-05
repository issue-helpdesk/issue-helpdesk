/**
 * http 로 운영하는 서버(보안 컨텍스트가 아님)에서 `crypto.randomUUID` 가 없어도 문의가 나가고,
 * 요청을 만들다 예외가 나도 무한 대기가 아니라 오류 문구와 "다시 시도"가 보이는지 확인한다.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { beginChat, clearPending } from '../src/api/chat'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { uuid } from '../src/core/uuid'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const user = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1001')!

const realCrypto = globalThis.crypto
/** 실제 브라우저의 http 접속처럼 randomUUID 만 없다 (getRandomValues 는 있다) */
function withoutRandomUuid() {
  vi.stubGlobal('crypto', { getRandomValues: <T extends ArrayBufferView>(a: T) => realCrypto.getRandomValues(a as unknown as Uint8Array<ArrayBuffer>) as unknown as T })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  clearPending()
})

describe('uuid()', () => {
  it('randomUUID 가 없어도 UUID v4 모양을 만들고, 매번 다르다', () => {
    withoutRandomUuid()
    const ids = Array.from({ length: 50 }, () => uuid())
    ids.forEach((x) => expect(x).toMatch(UUID_V4))
    expect(new Set(ids).size).toBe(50)
  })

  it('randomUUID·getRandomValues 가 모두 없으면 예측 가능한 값으로 대신하지 않고 예외를 던진다', () => {
    vi.stubGlobal('crypto', {})
    expect(() => uuid()).toThrow()
    vi.stubGlobal('crypto', undefined)
    expect(() => uuid()).toThrow()
  })

  it('randomUUID 가 있으면 그것을 쓴다', () => {
    vi.stubGlobal('crypto', { randomUUID: () => '11111111-1111-4111-8111-111111111111' })
    expect(uuid()).toBe('11111111-1111-4111-8111-111111111111')
  })
})

describe('서버 모드 문의 보내기 (http: randomUUID 없음)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('Idempotency-Key 를 직접 만들어 요청을 보낸다 (재시도에는 같은 키)', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    withoutRandomUuid()
    const api = await import('../src/api/inquiryServer')
    // 응답을 못 받는 오류(네트워크)는 같은 키로 다시 보내야 서버가 같은 요청으로 알아본다
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const r1 = await api.serverStart('VPN 이 안 돼요')
    expect(r1.ok).toBe(false)
    await api.serverStart('VPN 이 안 돼요')
    expect(fetchMock).toHaveBeenCalledTimes(2) // 요청이 실제로 나갔다 (예전에는 fetch 전에 예외로 0번)
    const key = (i: number) => new Headers((fetchMock.mock.calls[i][1] as RequestInit).headers).get('Idempotency-Key')
    expect(key(0)).toMatch(UUID_V4)
    expect(key(1)).toBe(key(0))
  })

  it('상담 중 추가 질문 답변(IQ-08)과 해결·미해결(IQ-09)도 randomUUID 없이 요청이 나간다', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    withoutRandomUuid()
    const api = await import('../src/api/inquiryServer')
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await api.serverSend(7, '재접속은 해 봤어요')
    await api.serverResolve(7, 'RESOLVED')
    await api.serverResolve(7, 'UNRESOLVED')
    const calls = fetchMock.mock.calls.map((c) => ({ method: (c[1] as RequestInit).method, url: String(c[0]).replace(/^https?:\/\/[^/]+/, ''), key: new Headers((c[1] as RequestInit).headers).get('Idempotency-Key') }))
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['POST /api/v1/inquiries/7/messages', 'PUT /api/v1/inquiries/7/resolution', 'PUT /api/v1/inquiries/7/resolution'])
    calls.forEach((c) => expect(c.key).toMatch(UUID_V4))
    // 해결과 미해결은 다른 요청이므로 다른 키를 쓴다
    expect(new Set(calls.map((c) => c.key)).size).toBe(3)
  })

  it('요청 키를 만들 수 없으면(randomUUID·getRandomValues 없음) 요청 없이 오류 결과로 안내한다', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    vi.stubGlobal('crypto', {})
    const api = await import('../src/api/inquiryServer')
    const r = await api.serverStart('VPN 이 안 돼요')
    expect(r).toMatchObject({ ok: false, error: { code: 'CLIENT_ERROR' } })
    expect(r.ok ? '' : r.error.message).toContain('요청을 보내지 못했어요')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('대기 화면의 예외 처리', () => {
  it('보내던 중 예외가 나도 오류 문구와 "다시 시도"가 보이고, 다시 시도하면 대기로 돌아간다', async () => {
    tokenStore.set('mock.EMP-1001')
    // 요청을 만들다 예외로 끝나는 경우 (예전에는 거절된 약속을 아무도 받지 않아 대기 문구에서 멈췄다)
    beginChat(user, '계정이 잠겼어요', () => Promise.reject(new Error('crypto.randomUUID is not a function')) as Promise<never>)
    render(
      <MemoryRouter initialEntries={['/chat/new']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('alert', {}, { timeout: 3000 })).toHaveTextContent('문의를 보내지 못했어요')
    expect(screen.getByText('계정이 잠겼어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /다시 시도/ })).toBeInTheDocument()
    expect(screen.queryByRole('status')).toBeNull() // 무한 대기 문구가 아니다
    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /다시 시도/ }))
    })
    // 다시 보내는 동안 대기 문구가 돌아오고(오류 문구는 사라진다)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('계정이 잠겼어요')).toBeInTheDocument()
    // 재요청이 성공하면 대기 화면이 사라지고 그 문의의 대화 화면(입력창)으로 넘어간다
    expect(await screen.findByLabelText('메시지 입력', {}, { timeout: 8000 })).toBeInTheDocument()
  }, 15_000)
})

