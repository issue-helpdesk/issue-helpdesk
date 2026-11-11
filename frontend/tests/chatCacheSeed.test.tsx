/**
 * 대화 화면: 이미 받아 둔 문의는 서버 응답을 기다리는 동안에도 그 내용으로 바로 보인다 (서버 모드).
 * 새로 읽는 요청이 느리거나 화면이 다시 시작되더라도 「불러오는 중이에요…」 빈 화면으로 되돌아가지 않아야 한다.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const inquiry = (id: number, title: string) => ({
  id, title, status: 'IN_PROGRESS', displayStatus: 'unconfirmed', categoryCode: 'NET', urgency: 'P2', action: 'ANSWER',
  recommendedGroup: { id: 5, name: '네트워크팀' }, resolutionResult: null, activeDraftId: null, ticket: null, lastAiMessageId: 900 + id,
  createdAt: '2026-10-21T10:12:03+09:00', updatedAt: '2026-10-21T10:12:09+09:00',
})
const msg = (id: number, sender: string, content: string) => ({ id, sessionId: 140, seq: id, sender, content, sources: [], createdAt: '2026-10-21T10:12:03+09:00' })

let slow = false
beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
  slow = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    // 느린 서버: 새로 읽는 요청이 끝나지 않는다
    if (slow && (u.endsWith('/inquiries/128') || u.includes('/inquiries/128/messages'))) return new Promise<Response>(() => {})
    if (u.endsWith('/inquiries/128')) return json(200, inquiry(128, '기존 문의'))
    if (u.includes('/inquiries/128/messages')) return json(200, { items: [msg(11, 'USER', '기존 질문'), msg(12, 'AI', '기존 답변입니다')] })
    if (u.includes('/inquiries')) return json(200, { items: [inquiry(128, '기존 문의')], page: 1, size: 20, totalCount: 1, totalPages: 1, statusCounts: {} })
    return json(404, { error: { code: 'NOT_FOUND', message: 'x', details: null, traceId: 't' } })
  }))
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

async function app(path: string) {
  const { tokenStore } = await import('../src/core/tokenStore')
  const { AuthProvider } = await import('../src/core/session')
  const { default: App } = await import('../src/App')
  tokenStore.set('mock.EMP-1001')
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

it('전에 읽은 문의는 새로 읽는 요청이 끝나기 전에도 내용이 바로 보이고, 불러오는 중 화면으로 돌아가지 않는다', async () => {
  const chat = await import('../src/api/chat')
  expect((await chat.getChat(128, 'EMP-1001')).ok).toBe(true) // 한 번 읽어 둔다
  slow = true // 이제부터 서버가 느리다
  await app('/chat/128')
  expect(await screen.findByText('기존 답변입니다')).toBeInTheDocument()
  expect(screen.queryByText('불러오는 중이에요…')).not.toBeInTheDocument()
})

it('읽어 둔 적 없는 문의는 처음 한 번 불러오는 중 화면을 보인다', async () => {
  slow = true
  await app('/chat/128')
  expect(await screen.findByText('불러오는 중이에요…')).toBeInTheDocument()
})
