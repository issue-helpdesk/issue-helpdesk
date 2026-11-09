/**
 * 작은 수정 모음: 긴급도 사유의 P1~P4 한글화, 문의자 상세에서 긴급도 숨김, 전체 문의의 "확인 필요" 필터,
 * 임시 비밀번호 상태에서 조회 요청 중단, 문의를 오래 못 불러올 때의 안내.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { urgencyReasonText } from '../src/api/urgencyReason'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

describe('긴급도 사유 글의 코드 이름', () => {
  it('P1~P4 를 긴급·높음·보통·낮음으로 바꾸고, 다른 글자에 붙은 P1 은 건드리지 않는다', () => {
    expect(urgencyReasonText('세부 유형 SSO 기본 긴급도 P1에서 시작해요.')).toBe('세부 유형 SSO 기본 긴급도 긴급에서 시작해요.')
    expect(urgencyReasonText('설치 요청이며 기본 긴급도 P4입니다.')).toBe('설치 요청이며 기본 긴급도 낮음입니다.')
    expect(urgencyReasonText('P2 → P3')).toBe('높음 → 보통')
    expect(urgencyReasonText('XP1 문서 P10')).toBe('XP1 문서 P10')
  })
})

describe('전체 문의의 확인 필요 필터', () => {
  it('확인 필요만 보면 관리자 확인이 필요한 접수만 나온다', async () => {
    tokenStore.set('mock.EMP-1178')
    render(
      <MemoryRouter initialEntries={['/tickets?needs=1']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    const rows = await screen.findAllByRole('row', undefined, SLOW)
    const body = rows.filter((r) => r.closest('tbody'))
    expect(body.length).toBeGreaterThan(0)
    expect(body.length).toBeLessThan(20)
    expect(body.every((r) => /확인 필요|확인 중/.test(r.textContent ?? ''))).toBe(true)
    expect(screen.getByRole('button', { name: /^확인 필요\s*확인 필요만/ })).toBeInTheDocument()
  })
})

describe('임시 비밀번호 상태에서는 조회 요청을 보내지 않는다', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('잠겨 있는 동안 목록 요청은 서버로 가지 않고, 내 정보·비밀번호 변경·인증은 나간다', async () => {
    const { request, setPasswordGate } = await import('../src/core/apiClient')
    setPasswordGate(true)
    const blocked = await request('/inquiries?size=5')
    expect(blocked).toMatchObject({ ok: false, error: { code: 'AUTH_PASSWORD_CHANGE_REQUIRED' } })
    expect(fetchMock).not.toHaveBeenCalled()
    await request('/users/me')
    await request('/users/me/password', { method: 'PUT', body: '{}' })
    await request('/auth/login', { method: 'POST', body: '{}' })
    expect(fetchMock.mock.calls.map((c) => String(c[0]).replace(/^.*\/api\/v1/, ''))).toEqual(['/users/me', '/users/me/password', '/auth/login'])
    setPasswordGate(false)
    await request('/inquiries?size=5')
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })
})

describe('문의를 오래 못 불러올 때', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.doUnmock('../src/api/chat')
    vi.resetModules()
  })

  it('빈 화면으로 두지 않고 오류 안내와 다시 불러오기를 보인다', async () => {
    vi.resetModules()
    vi.doMock('../src/api/chat', async (original) => ({
      ...(await original<object>()),
      getChat: () => new Promise(() => {}),
      watchChat: () => () => {},
    }))
    const { ChatView } = await import('../src/views/inquiry/ChatView')
    const { AuthProvider: Provider } = await import('../src/core/session')
    tokenStore.set('mock.EMP-1001')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(
      <MemoryRouter initialEntries={['/chat/101']}>
        <Provider>
          <Routes>
            <Route path="/chat/:id" element={<ChatView />} />
          </Routes>
        </Provider>
      </MemoryRouter>,
    )
    expect(await screen.findByText('불러오는 중이에요…', undefined, SLOW)).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(13_000)
    })
    expect(await screen.findByText('문의를 불러오지 못했어요')).toBeInTheDocument()
    expect(within(screen.getByRole('main')).getByRole('button', { name: '다시 불러오기' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('불러오는 중이에요…')).toBeNull())
  })
})
