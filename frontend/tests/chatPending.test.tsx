/**
 * 새 문의를 보낸 직후 화면 (/chat/new). 서버 모드처럼 느린 응답을 흉내 낸다.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App'
import { beginChat, clearPending, getPending } from '../src/api/chat'
import type { Inquiry } from '../src/api/chatTypes'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { stageLabel } from '../src/views/inquiry/pendingStages'
import { fail, ok, type ApiResult } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const user = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1001')!

function renderAt(path: string, state?: unknown) {
  tokenStore.set('mock.EMP-1001')
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
/** 직접 열고 닫을 수 있는 느린 요청 */
function slow() {
  let done!: (r: ApiResult<Inquiry>) => void
  const p = new Promise<ApiResult<Inquiry>>((res) => (done = res))
  return { run: () => p, done }
}

beforeEach(() => clearPending())

describe('새 문의 직후 대기 화면', () => {
  it('보낸 글과 "찾고 있어요" 표시를 보여 준다', async () => {
    beginChat(user, 'VPN 이 안 돼요', slow().run)
    renderAt('/chat/new')
    expect(await screen.findByText('VPN 이 안 돼요')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('문의를 처리하고 있어요')
  })

  it('기다린 시간에 따라 문구가 바뀌지만 검색·정리 같은 단계 이름은 말하지 않는다', () => {
    expect(stageLabel(0)).toBe('문의를 처리하고 있어요.')
    expect(stageLabel(9)).toBe('문의를 처리하고 있어요.')
    // 답변을 만드는 중인 대화 화면의 입력 중 표시: 처음 문구만 다르고 이후 단계는 같다
    expect(stageLabel(0, '답변을 준비하고 있어요')).toBe('답변을 준비하고 있어요')
    expect(stageLabel(12, '답변을 준비하고 있어요')).toBe('답변을 준비하고 있어요. 잠시만 기다려 주세요.')
    expect(stageLabel(30, '답변을 준비하고 있어요')).toBe('답변 준비에 시간이 걸리고 있어요.')
    expect(stageLabel(10)).toBe('답변을 준비하고 있어요. 잠시만 기다려 주세요.')
    expect(stageLabel(25)).toBe('답변 준비에 시간이 걸리고 있어요.')
    for (const sec of [0, 5, 12, 30]) expect(stageLabel(sec)).not.toMatch(/찾고|읽고|정리|평소보다/)
  })

  it('보낸 글의 민감정보는 대기·오류·다시 시도 어디서도 말풍선에 보이지 않고, 요청에 쓰는 원래 글은 그대로다', async () => {
    const SECRET = 'Test1234!'
    const raw = `VPN이 안 돼요 비밀번호: ${SECRET}`
    const s = slow()
    beginChat(user, raw, s.run)
    renderAt('/chat/new')
    await screen.findByText(/VPN이 안 돼요/)
    expect(document.body.textContent).not.toContain(SECRET)
    expect(screen.getByText(/VPN이 안 돼요/)).toHaveTextContent('●●●')
    // 원래 글은 서버에 보낼 값으로 그대로 들고 있다
    expect(getPending()?.text).toBe(raw)
    await act(async () => s.done(fail('AI_UNAVAILABLE', '답변을 준비하지 못했어요. 잠시 뒤 다시 시도해 주세요.')))
    await screen.findByRole('alert')
    expect(document.body.textContent).not.toContain(SECRET)
    await userEvent.click(screen.getByRole('button', { name: /다시 시도/ }))
    expect(document.body.textContent).not.toContain(SECRET)
    expect(getPending()?.text).toBe(raw)
  })

  it('답이 오면 그 문의의 대화 화면으로 바꿔 끼운다', async () => {
    const s = slow()
    beginChat(user, '프린터가 안 돼요', s.run)
    renderAt('/chat/new')
    expect(await screen.findByText('프린터가 안 돼요')).toBeInTheDocument()
    await act(async () => s.done(ok({ id: 987654, title: '새 문의', messages: [] } as unknown as Inquiry)))
    // 없는 문의라 대화 화면은 "찾을 수 없어요"를 보여 주지만, 대기 화면은 사라진다
    expect(await screen.findByText(/문의를 찾을 수 없어요|찾을 수 없/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText('프린터가 안 돼요')).toBeNull()
  })

  it('실패하면 쓴 글을 보여 주고 다시 시도하거나 다시 쓸 수 있다', async () => {
    const s = slow()
    beginChat(user, '계정이 잠겼어요', s.run)
    renderAt('/chat/new')
    await screen.findByText('계정이 잠겼어요')
    await act(async () => s.done(fail('AI_UNAVAILABLE', '답변을 준비하지 못했어요. 잠시 뒤 다시 시도해 주세요.')))
    expect(await screen.findByRole('alert')).toHaveTextContent('답변을 준비하지 못했어요')
    expect(screen.getByText('계정이 잠겼어요')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /다시 시도/ }))
    expect(screen.getByRole('status')).toHaveTextContent('문의를 처리하고 있어요')
  })

  it('보낸 글이 없으면(새로고침 등) 새 문의 화면으로 돌아간다', async () => {
    renderAt('/chat/new')
    expect(await screen.findByRole('heading', { name: '무엇을 도와드릴까요?' }, { timeout: 3000 })).toBeInTheDocument()
  })
})
