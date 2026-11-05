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

  it('getRandomValues 도 없으면 Math.random 으로 대신한다', () => {
    vi.stubGlobal('crypto', {})
    expect(uuid()).toMatch(UUID_V4)
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
    expect(screen.getByText('계정이 잠겼어요')).toBeInTheDocument()
  })
})

