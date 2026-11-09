/**
 * 추가 질문 답을 보내다 실패하면 고른 것·직접 입력·추가 내용이 그대로 남고, 다시 보내면 성공한다.
 * (sendChat 만 한 번 실패하게 감싼다)
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { startChat } from '../src/api/chat'
import { fail } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const gate = vi.hoisted(() => ({ failNext: false, calls: 0 }))
vi.mock('../src/api/chat', async (importActual) => {
  const actual = await importActual<typeof import('../src/api/chat')>()
  return {
    ...actual,
    sendChat: (...args: Parameters<typeof actual.sendChat>) => {
      gate.calls++
      if (gate.failNext) {
        gate.failNext = false
        return Promise.resolve(fail('NETWORK_ERROR', '연결이 불안정해요. 잠시 뒤 다시 시도해 주세요.'))
      }
      return actual.sendChat(...args)
    },
  }
})

const SLOW = { timeout: 3000 }

describe('질문 답 전송 실패', () => {
  it('실패하면 선택값·직접 입력·추가 내용을 유지하고, 다시 보내면 한 번 더 가서 성공한다', async () => {
    const user = userEvent.setup()
    const r = await startChat({ employeeNo: 'EMP-1003', name: '김민지' }, 'VPN이 끊겨요')
    if (!r.ok) throw new Error('시작')
    tokenStore.set('mock.EMP-1003')
    render(
      <MemoryRouter initialEntries={[`/chat/${r.data.id}`]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    const groups = within(grp).getAllByRole('radiogroup')
    // 첫 질문은 직접 입력, 나머지는 선택
    await user.click(within(groups[0]).getByRole('radio', { name: /직접 입력/ }))
    await user.type(within(grp).getByLabelText(/직접 입력$/), '모르겠어요')
    for (const g of groups.slice(1)) await user.click(within(g).getAllByRole('radio')[0])
    await user.type(screen.getByLabelText('메시지 입력'), '보충 설명')
    const chosen = within(groups[1]).getAllByRole('radio')[0]

    gate.failNext = true
    const before = gate.calls
    await user.click(within(grp).getByRole('button', { name: '답변 보내기' }))
    expect(await screen.findByText(/연결이 불안정해요/, undefined, SLOW)).toBeInTheDocument()
    expect(gate.calls).toBe(before + 1)
    // 모두 그대로
    expect(within(grp).getByLabelText(/직접 입력$/)).toHaveValue('모르겠어요')
    expect(chosen).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByLabelText('메시지 입력')).toHaveValue('보충 설명')
    expect(document.querySelectorAll('.msg.u')).toHaveLength(1)
    expect(screen.getByRole('group', { name: '추가 질문' })).toBeInTheDocument() // 아직 답할 수 있다

    await user.click(within(screen.getByRole('group', { name: '추가 질문' })).getByRole('button', { name: '답변 보내기' }))
    await waitFor(() => expect(document.querySelectorAll('.msg.u').length).toBe(2), SLOW)
    expect(gate.calls).toBe(before + 2) // 성공한 전송은 한 번뿐
    expect(screen.getByLabelText('메시지 입력')).toHaveValue('')
  })
})
