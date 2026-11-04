/**
 * FAQ 분류 칩: 있는 분류만 건수와 함께 보이고, 누르면 그 분류만 남는다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

describe('FAQ 분류 칩', () => {
  it('전체와 있는 분류만 건수와 함께 보이고, 분류를 누르면 그 분류의 FAQ만 남는다', async () => {
    tokenStore.set('mock.EMP-1001')
    render(
      <MemoryRouter initialEntries={['/faq']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    const grp = await screen.findByRole('group', { name: '분류' }, { timeout: 3000 })
    const all = within(grp).getByRole('button', { name: /^전체\s*\d+/ })
    expect(all).toHaveAttribute('aria-pressed', 'true')
    const total = document.querySelectorAll('details.faq').length
    expect(total).toBeGreaterThan(1)
    // 분류 칩 건수의 합 = 전체
    const chips = within(grp).getAllByRole('button').slice(1)
    const sum = chips.reduce((n, b) => n + Number(b.querySelector('em')!.textContent), 0)
    expect(sum).toBe(total)
    // 분류 칩마다 그 분류의 포인트 색 막대가 붙고, 전체 칩에는 없다
    chips.forEach((b) => expect(b.querySelector('.tag.gcbar')?.className).toMatch(/c-[A-Z]+/))
    expect(all.querySelector('.tag.gcbar')).toBeNull()
    await userEvent.click(chips[0])
    expect(chips[0]).toHaveAttribute('aria-pressed', 'true')
    expect(document.querySelectorAll('details.faq').length).toBe(Number(chips[0].querySelector('em')!.textContent))
    await userEvent.click(within(grp).getByRole('button', { name: /^전체\s*\d+/ }))
    expect(document.querySelectorAll('details.faq').length).toBe(total)
  })
})
