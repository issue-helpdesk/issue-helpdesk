/** 문의자·담당자의 가이드 열람 (/docs): 열람 범위 안의 현행 가이드만 분류별로 보이고, 보기로 본문 패널이 열린다. */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { listReadableGuides } from '../src/api/guides'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const as = (no: string) => MOCK_ACCOUNTS.find((u) => u.employeeNo === no)!

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

describe('열람용 가이드 목록 (모의)', () => {
  it('문의자는 전 직원용만, 담당자는 담당자 이상까지, 관리자는 모두 본다', async () => {
    const employee = await listReadableGuides(as('EMP-1001'))
    const agent = await listReadableGuides(as('EMP-1004'))
    const admin = await listReadableGuides(as('EMP-1178'))
    expect(employee.ok && employee.data.every((g) => g.current?.scope === '전 직원')).toBe(true)
    expect(agent.ok && admin.ok && agent.data.length >= (employee.ok ? employee.data.length : 0) && admin.data.length >= agent.data.length).toBe(true)
  })
})

describe('가이드 열람 화면', () => {
  it('분류를 펼쳐 가이드를 고르고 보기로 본문을 읽는다. 사이드바에 가이드 메뉴가 있다', async () => {
    renderAs('EMP-1001', '/docs')
    expect(await screen.findByRole('heading', { name: '사내 가이드를 찾아 읽어요', level: 1 }, SLOW)).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: '주 메뉴' })).getByRole('button', { name: '가이드' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /^VPN·네트워크/ }, SLOW))
    const see = (await screen.findAllByRole('button', { name: /본문 보기/ }))[0]
    await userEvent.click(see)
    const panel = await screen.findByRole('complementary', { name: '가이드 본문' })
    expect(await within(panel).findByText('1. 개요', undefined, SLOW)).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '가이드 본문' })).toBeNull())
  })
})
