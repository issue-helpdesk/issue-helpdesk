/**
 * 대화 화면의 요청이 예외로 끝나도(예: http 서버에서 요청 키를 만들다 난 오류) 오류 문구가 보이고,
 * 잠겨 있던 버튼이 다시 눌리는지 확인한다. (예전에는 `setBusy(false)` 가 실행되지 않아 버튼이 계속 잠겼다)
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { advanceChat } from '../src/api/chat'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

// 해결·미해결 요청만 예외로 끝나게 바꾼다 (나머지는 그대로)
vi.mock('../src/api/chat', async (orig) => ({
  ...(await orig<typeof import('../src/api/chat')>()),
  resolveChat: vi.fn(() => Promise.reject(new Error('crypto.randomUUID is not a function'))),
  rejectChat: vi.fn(() => Promise.reject(new Error('crypto.randomUUID is not a function'))),
}))

const SLOW = { timeout: 3000 }
function renderChat() {
  tokenStore.set('mock.EMP-1001')
  return render(
    <MemoryRouter initialEntries={['/chat/101']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
/** 눌러 볼 수 있는(잠기지 않은) 버튼. 지난 안내에 남은 같은 이름의 버튼은 잠겨 있다 */
const enabled = (name: string) =>
  waitFor(() => {
    const b = screen.getAllByRole('button', { name }).find((x) => !(x as HTMLButtonElement).disabled)
    if (!b) throw new Error(`${name} 버튼 없음`)
    return b
  }, SLOW)

describe('대화 화면의 요청이 예외로 끝날 때', () => {
  it('"해결"이 예외로 끝나도 오류 문구가 보이고 버튼이 다시 눌린다', async () => {
    const user = userEvent.setup()
    renderChat()
    await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    await advanceChat(101, 'EMP-1001') // 처리 중 → 해결 확인 대기
    await user.click(await enabled('해결'))
    expect(await screen.findByRole('alert', {}, SLOW)).toHaveTextContent('요청을 보내지 못했어요')
    // 버튼 잠금이 풀려 있다 (다시 눌러 볼 수 있다)
    expect(await enabled('해결')).toBeEnabled()
    expect(await enabled('미해결')).toBeEnabled()
  })

  it('"미해결" 사유 보내기가 예외로 끝나도 오류 문구가 보이고 창의 버튼이 다시 눌린다', async () => {
    const user = userEvent.setup()
    renderChat()
    await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    await advanceChat(101, 'EMP-1001')
    await user.click(await enabled('미해결'))
    const dlg = await screen.findByRole('dialog', { name: '미해결' })
    await user.type(within(dlg).getByLabelText('남은 증상'), '같은 오류가 나요')
    await user.click(within(dlg).getByRole('button', { name: '다시 확인 요청' }))
    // 오류 문구는 대화 화면 쪽에 뜨고, 창은 닫히지 않은 채 버튼 잠금만 풀린다
    expect(await screen.findByRole('alert', {}, SLOW)).toHaveTextContent('요청을 보내지 못했어요')
    expect(screen.getByRole('dialog', { name: '미해결' })).toBeInTheDocument()
    expect(within(dlg).getByRole('button', { name: '다시 확인 요청' })).toBeEnabled()
    expect(within(dlg).getByRole('button', { name: '취소' })).toBeEnabled()
  })
})
