import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ClassificationSection } from '../src/views/staff/ClassificationSection'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { findStaffTicket } from '../src/api/mock/staffTickets'
import type { ClassificationReport } from '../src/api/ticketTypes'

vi.mock('../src/core/config', async (original) => ({ ...await original<object>(), USE_MOCK_TICKET: false, SERVER_INTAKE: true }))
vi.mock('../src/core/session', () => ({ useAuth: () => ({ user: actor }) }))
let actor = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'ADMIN')!
const ticket = { ...findStaffTicket(5004)!, workStatus: 'RDY' as const }
const type = { id: 27, code: 'ACC-01', name: '비밀번호 만료·초기화', categoryCode: 'ACC', defaultGroup: { id: 1, name: '서비스데스크' }, isActive: true }
const report: ClassificationReport = { id: 91, ticketId: ticket.id, reporter: ticket.assignee!, reason: '계정 인증 문제로 보여요.', suggestedInquiryType: type, status: 'OPEN', resolvedBy: null, resolvedAt: null, resolutionNote: null, createdAt: '2026-11-10T12:00:00+09:00' }
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200 })
const onUpdated = vi.fn()
let fetcher: ReturnType<typeof vi.fn>
beforeEach(() => {
  actor = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'ADMIN')!
  onUpdated.mockReset()
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/inquiry-types')) return json({ items: [type] })
    if (init?.method === 'PATCH') return json({ ...report, status: 'REJECTED', resolutionNote: '현재 분류 유지' })
    if (init?.method === 'POST') return json(report)
    return json({ items: [] })
  })
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => vi.unstubAllGlobals())
const show = (reports: ClassificationReport[] | null, reportError = '') => render(<ClassificationSection ticket={ticket} reports={reports} reportError={reportError} onReload={() => {}} onUpdated={onUpdated} />)

it('서버 신고 사유·제안 유형·신고자를 표시하고 신고 ID로 반려한다', async () => {
  show([report])
  expect(screen.getByText(report.reason)).toBeInTheDocument()
  expect(screen.getByText(`제안 유형: ${type.name}`)).toBeInTheDocument()
  expect(screen.getByText(new RegExp(report.reporter.name))).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '담당자 변경' })).toHaveClass('sec')
  await userEvent.click(screen.getByRole('button', { name: '재분류 반려' }))
  const modal = screen.getByRole('dialog')
  const field = within(modal).getByLabelText('반려 사유 (필수)')
  expect(field).toHaveAttribute('maxlength', '1000')
  expect(field).toHaveAccessibleDescription('0/1000')
  await userEvent.type(field, '현재 분류 유지')
  expect(field).toHaveAccessibleDescription('8/1000')
  await userEvent.click(within(modal).getByRole('button', { name: '반려' }))
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ classificationReportOpen: false, openClassificationReport: null })))
  expect(fetcher.mock.calls.some(([url, init]) => url.endsWith('/classification-reports/91') && init?.method === 'PATCH')).toBe(true)
})

it('담당자가 선택한 세부 유형과 사유를 서버로 전송한다', async () => {
  actor = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'AGENT')!
  show([])
  await userEvent.click(screen.getByRole('button', { name: '재분류 요청' }))
  const modal = screen.getByRole('dialog')
  const combo = within(modal).getByRole('combobox')
  await waitFor(() => expect(combo).toBeEnabled())
  await userEvent.click(combo)
  await userEvent.click(screen.getByRole('option', { name: /비밀번호 만료/ }))
  await userEvent.type(within(modal).getByLabelText('요청 사유 (필수)'), '인증 문제 확인')
  await userEvent.click(within(modal).getByRole('button', { name: '재분류 요청' }))
  await waitFor(() => expect(onUpdated).toHaveBeenCalled())
  const post = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toEqual({ reason: '인증 문제 확인', suggestedInquiryTypeId: 27 })
})

it('반려 이력이 있거나 이력을 못 읽으면 새 요청을 열지 않는다', () => {
  actor = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'AGENT')!
  const { unmount } = show([{ ...report, status: 'REJECTED', resolutionNote: '현재 분류 유지' }])
  expect(screen.getByRole('button', { name: '재분류 요청 반려됨' })).toBeDisabled()
  unmount()
  show(null, '이력을 읽지 못했어요.')
  expect(screen.getByRole('button', { name: '재분류 요청' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeInTheDocument()
  expect(fetcher).not.toHaveBeenCalled()
})
