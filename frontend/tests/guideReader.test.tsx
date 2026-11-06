/**
 * 가이드 본문 읽기: 가이드 관리의 버전마다 "보기"를 누르면 오른쪽 패널로 본문이 열리고, "크게 보기"로 화면 전체로 넓힌다.
 * 열람 범위 배지는 범위마다 색 톤이 다르다 (전 직원=하늘, 담당자 이상=보라, 관리자만=중립).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { ScopeBadge } from '../src/ui/ScopeBadge'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

describe('열람 범위 배지', () => {
  it('범위마다 다른 색 톤을 쓴다', () => {
    const { container } = render(
      <>
        <ScopeBadge scope="전 직원" />
        <ScopeBadge scope="담당자 이상" />
        <ScopeBadge scope="관리자만" />
      </>,
    )
    const tones = [...container.querySelectorAll('.badge')].map((b) => [...b.classList].find((c) => c.startsWith('b-')))
    expect(tones).toEqual(['b-info', 'b-prog', 'b-adm'])
  })
})

describe('가이드 본문 보기 (관리자)', () => {
  it('버전의 보기를 누르면 오른쪽 패널에 본문이 열리고, 크게 보기로 넓힌 뒤 닫을 수 있다', async () => {
    tokenStore.set('mock.EMP-1178')
    render(
      <MemoryRouter initialEntries={['/guides']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /^VPN·네트워크/ }, SLOW))
    await userEvent.click(await screen.findByRole('button', { name: /^IT-NET-001 VPN 접속 장애 대응 가이드\s*현행/ }))
    const see = (await screen.findAllByRole('button', { name: /본문 보기/ }, SLOW))[0]
    await userEvent.click(see)
    const panel = await screen.findByRole('complementary', { name: '가이드 본문' }, SLOW)
    expect(await within(panel).findByText('1. 개요', undefined, SLOW)).toBeInTheDocument()
    expect(panel).not.toHaveClass('wide')
    await userEvent.click(within(panel).getByRole('button', { name: '크게 보기' }))
    expect(panel).toHaveClass('wide')
    await userEvent.click(within(panel).getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '가이드 본문' })).toBeNull())
  })
})
