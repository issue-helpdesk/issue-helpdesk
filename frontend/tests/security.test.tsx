/**
 * 관리자 보안·감사 알림 (EMP-1178 이건우). 시연 데이터(mock)로 동작한다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { closeSecurityAlert, listSecurityAlerts, resetSecurityMock, startSecurityReview, viewSecurityRaw } from '../src/api/security'
import type { User } from '../src/api/types'
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
const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const staff = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
const rows = () => [...document.querySelectorAll('.tbl tbody tr')] as HTMLElement[]

beforeEach(() => resetSecurityMock())

describe('보안·감사 알림 API (시연)', () => {
  it('미종결(신규→확인 중) 먼저, 같은 상태에서는 심각도 높은 것 먼저, 종결은 맨 아래', async () => {
    const r = await listSecurityAlerts(admin())
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data.counts).toMatchObject({ 신규: 3, '확인 중': 1, 종결: 2, high: 2, total: 6 })
    const order = r.data.items.map((a) => a.status)
    expect(order.indexOf('종결')).toBeGreaterThan(order.lastIndexOf('확인 중'))
    expect(r.data.items[0]).toMatchObject({ status: '신규', severity: '높음' })
    expect(r.data.items.every((a) => !('raw' in a))).toBe(true)
  })

  it('관리자만 볼 수 있다', async () => {
    expect((await listSecurityAlerts(staff())).ok).toBe(false)
  })

  it('원문은 사유가 있어야 열리고 열람 기록이 남는다', async () => {
    expect((await viewSecurityRaw(admin(), 'SEC-29', ' ')).ok).toBe(false)
    const r = await viewSecurityRaw(admin(), 'SEC-29', '정상 문의 여부 확인')
    expect(r.ok && r.data.raw).toContain('피싱')
    expect(r.ok && r.data.alert.log[0].what).toBe('원문 열람 · 사유: 정상 문의 여부 확인')
  })

  it('신규만 확인을 시작하고, 확인 중만 사유와 함께 종결한다', async () => {
    expect((await closeSecurityAlert(admin(), 'SEC-29', '사유')).ok).toBe(false) // 신규는 바로 종결할 수 없다
    expect((await startSecurityReview(admin(), 'SEC-29')).ok).toBe(true)
    expect((await startSecurityReview(admin(), 'SEC-29')).ok).toBe(false)
    expect((await closeSecurityAlert(admin(), 'SEC-29', '')).ok).toBe(false)
    const r = await closeSecurityAlert(admin(), 'SEC-29', '정상 문의로 확인')
    expect(r.ok && r.data.status).toBe('종결')
  })
})

describe('보안·감사 알림 화면', () => {
  it('건수 카드와 목록이 보이고, 상태·유형으로 거르며, 담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/security')
    expect(await screen.findByRole('heading', { name: /보안·감사 알림을 확인해요/, level: 1 }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(rows()).toHaveLength(6), SLOW)
    await userEvent.click(screen.getByRole('button', { name: '종결' }))
    await waitFor(() => expect(rows()).toHaveLength(2), SLOW)
    await userEvent.click(screen.getByRole('button', { name: '전체' }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '유형' }), '민감정보 입력')
    await waitFor(() => expect(rows()).toHaveLength(1), SLOW)
    unmount()
    renderAs('EMP-1004', '/security')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('상세에서 원문 열람 사유를 요구하고, 확인 시작 → 종결(사유 필수)까지 처리한다', async () => {
    renderAs('EMP-1178', '/security')
    await waitFor(() => expect(rows()).toHaveLength(6), SLOW)
    await userEvent.click(screen.getAllByRole('button', { name: '긴급 징후 후 접수 없이 종료' })[0])
    const dlg = await screen.findByRole('dialog', {}, SLOW)
    expect(within(dlg).queryByText('원문 (열람 기록 남음)')).toBeNull()
    await userEvent.click(within(dlg).getByRole('button', { name: '원문 보기' }))
    expect(await within(dlg).findByText('열람 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('원문 열람 사유 (필수)'), '정상 문의 확인')
    await userEvent.click(within(dlg).getByRole('button', { name: '원문 보기' }))
    expect(await within(dlg).findByText('원문 (열람 기록 남음)')).toBeInTheDocument()
    expect(within(dlg).getByText(/원문 열람 · 사유: 정상 문의 확인/)).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('button', { name: '확인 시작' }))
    await userEvent.click(await within(dlg).findByRole('button', { name: '종결 (사유 입력)' }))
    const end = await screen.findByRole('dialog', { name: '알림 종결' })
    await userEvent.click(within(end).getByRole('button', { name: '종결' }))
    expect(await within(end).findByText('종결 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(end).getByLabelText('종결 사유 (필수)'), '정상 문의로 확인')
    await userEvent.click(within(end).getByRole('button', { name: '종결' }))
    expect(await screen.findByText('종결했어요.', {}, SLOW)).toBeInTheDocument()
  })

  it('대시보드에 보안·감사 알림 띠가 보인다', async () => {
    renderAs('EMP-1178', '/dash')
    expect(await screen.findByRole('region', { name: '보안·감사 알림' }, SLOW)).toBeInTheDocument()
  })
})
