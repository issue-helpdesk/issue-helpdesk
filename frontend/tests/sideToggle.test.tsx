/**
 * 사이드바 도크: 로고 옆 ‹ 버튼으로 아이콘 레일로 접고, 접힌 레일에서 로고 자리의 › 버튼으로 펼친다. 접힘 상태는 브라우저에 기억한다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

afterEach(() => localStorage.clear())

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
const app = () => document.querySelector('.app') as HTMLElement

describe('사이드바 접기', () => {
  it('접으면 아이콘 레일이 되고, 로고 자리의 버튼으로 다시 펼친다', async () => {
    renderAs('EMP-1178', '/ops')
    await screen.findByRole('heading', { name: '운영 현황', level: 1 }, { timeout: 3000 })
    expect(app()).not.toHaveClass('side-off')
    await userEvent.click(screen.getByRole('button', { name: '사이드바 접기' }))
    expect(app()).toHaveClass('side-off')
    expect(localStorage.getItem('itssue-side')).toBe('off')
    const open = screen.getByRole('button', { name: '사이드바 펼치기' })
    expect(open).toHaveAttribute('aria-expanded', 'false')
    // 레일에서도 메뉴는 그대로 있고, 이름은 툴팁(data-tip)으로 보인다
    expect(within(screen.getByRole('navigation', { name: '주 메뉴' })).getByRole('button', { name: /^운영 현황/ })).toHaveAttribute('data-tip', '운영 현황')
    await userEvent.click(open)
    await waitFor(() => expect(app()).not.toHaveClass('side-off'))
    expect(localStorage.getItem('itssue-side')).toBe('on')
  })

  it('접어 둔 상태는 다음에 열어도 유지된다', async () => {
    localStorage.setItem('itssue-side', 'off')
    renderAs('EMP-1001', '/chat/new')
    await waitFor(() => expect(document.querySelector('.app')).toHaveClass('side-off'), { timeout: 3000 })
  })
})
