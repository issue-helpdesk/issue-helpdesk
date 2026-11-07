/**
 * 오른쪽 상세 패널은 X 뿐 아니라 패널 밖의 빈 곳(본문의 글자·여백)을 눌러도 닫힌다.
 * 단추·표의 행처럼 눌러서 일하는 곳을 누르면 닫히지 않는다 (행을 눌러 다른 건으로 바꾸는 흐름을 방해하지 않는다).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

function renderAs(employeeNo: string, path: string) {
  tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('상세 패널 바깥 누르기', () => {
  it('접수 상세 패널(담당자): 본문의 빈 곳을 누르면 닫히고, 패널 안을 누르면 닫히지 않는다', async () => {
    renderAs('EMP-1004', '/queue/5004')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await within(panel).findByRole('heading', { name: '재택 VPN 인증 오류' }, SLOW)
    // 패널 안의 글자를 눌러도 닫히지 않는다
    await userEvent.click(within(panel).getByRole('heading', { name: '재택 VPN 인증 오류' }))
    expect(screen.getByRole('complementary', { name: '티켓 상세' })).toBeInTheDocument()
    // 본문의 제목 글자를 누르면 닫힌다
    await userEvent.click(screen.getByRole('heading', { name: '처리할 문의를 확인해요', level: 1 }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '티켓 상세' })).toBeNull(), SLOW)
  })

  it('접수 상세 패널(관리자): 목록의 행을 누르면 닫히지 않고 다른 건으로 바뀐다', async () => {
    renderAs('EMP-1178', '/tickets')
    const rows = await screen.findAllByRole('row', undefined, SLOW)
    const body = rows.filter((r) => r.closest('tbody'))
    await userEvent.click(within(body[0]).getAllByRole('button')[0])
    await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await userEvent.click(within(body[1]).getAllByRole('button')[0])
    // 닫혔다 다시 열리지 않고 패널이 계속 열려 있다
    await new Promise((r) => setTimeout(r, 700))
    expect(screen.getAllByRole('complementary', { name: '티켓 상세' })).toHaveLength(1)
  })
})
