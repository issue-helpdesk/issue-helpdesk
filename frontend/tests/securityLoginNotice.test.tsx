import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { SecurityLoginNotice } from '../src/ui/SecurityLoginNotice'
import { countSecurityAlerts } from '../src/api/security'

let auth = { user: { id: 1, serviceRole: 'ADMIN', passwordChangeRequired: false }, loginSequence: 1 }
const failures: never[] = []
vi.mock('../src/core/session', () => ({ useAuth: () => auth }))
vi.mock('../src/api/security', () => ({ countSecurityAlerts: vi.fn() }))
vi.mock('../src/api/guideWatch', () => ({ watchIngest: () => () => {}, getIngestFailures: () => failures }))
function Location() { const l = useLocation(); return <span data-testid="location">{l.pathname}{l.search}</span> }
beforeEach(() => {
  auth = { user: { id: 1, serviceRole: 'ADMIN', passwordChangeRequired: false }, loginSequence: 1 }
  vi.mocked(countSecurityAlerts).mockReset().mockResolvedValue({ 신규: 3, '확인 중': 2, 종결: 1, high: 2, total: 6 })
})
it('로그인 직후 신규 건수 안내, 이동 후에는 반복하지 않는다', async () => {
  render(<MemoryRouter><SecurityLoginNotice /><Location /></MemoryRouter>)
  expect(await screen.findByRole('dialog')).toHaveTextContent('3건')
  await userEvent.click(screen.getByRole('button', { name: '신규 알림 확인' }))
  expect(screen.getByTestId('location')).toHaveTextContent('/security?status=NEW')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(countSecurityAlerts).toHaveBeenCalledTimes(1)
})
it('나중에 보기는 안내만 닫고 같은 로그인에서 반복하지 않는다', async () => {
  const { rerender } = render(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  await userEvent.click(await screen.findByRole('button', { name: '나중에 볼게요' }))
  rerender(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  expect(screen.queryByRole('dialog')).toBeNull()
  auth = { ...auth, loginSequence: 2 }
  rerender(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
})
it('신규가 없고 확인 중만 있으면 띄우지 않는다', async () => {
  vi.mocked(countSecurityAlerts).mockResolvedValue({ 신규: 0, '확인 중': 5, 종결: 0, high: 2, total: 5 })
  render(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  await waitFor(() => expect(countSecurityAlerts).toHaveBeenCalledOnce())
  expect(screen.queryByRole('dialog')).toBeNull()
})
it('세션 복원과 담당자 로그인에서는 조회하지 않는다', () => {
  auth = { ...auth, loginSequence: 0 }
  const { rerender } = render(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  auth = { ...auth, user: { ...auth.user, serviceRole: 'AGENT' }, loginSequence: 1 }
  rerender(<MemoryRouter><SecurityLoginNotice /></MemoryRouter>)
  expect(countSecurityAlerts).not.toHaveBeenCalled()
})
