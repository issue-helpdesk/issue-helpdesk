/**
 * 운영 기록 (관리자, OP-04 GET /audit-logs): 모의 필터·관리자 전용·서버 요청 모양·화면.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { listAuditLogs } from '../src/api/auditLogs'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const agent = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!

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

describe('운영 기록 API (모의)', () => {
  it('관리자가 아니면 막는다', async () => {
    expect(await listAuditLogs(agent())).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
  })

  it('이벤트·대상·기간으로 거르고 최근 것부터 준다', async () => {
    const all = await listAuditLogs(admin())
    expect(all.ok && all.data.totalCount).toBe(24)
    expect(all.ok && all.data.items[0].id).toBeGreaterThan(all.ok ? all.data.items[1].id : 0)
    const re = await listAuditLogs(admin(), { eventType: 'REASSIGN' })
    expect(re.ok && re.data.items.every((x) => x.eventType === 'REASSIGN')).toBe(true)
    const doc = await listAuditLogs(admin(), { targetType: 'document' })
    expect(doc.ok && doc.data.items.length).toBe(5)
    expect(doc.ok && doc.data.items.every((x) => x.targetType === 'document')).toBe(true)
    const today = await listAuditLogs(admin(), { days: 0 })
    expect(today.ok && today.data.totalCount).toBeLessThan(all.ok ? all.data.totalCount : 0)
    const paged = await listAuditLogs(admin(), { page: 2, size: 5 })
    expect(paged.ok && paged.data.items).toHaveLength(5)
  })
})

describe('운영 기록 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('조건을 쿼리로 보낸다 (eventType·targetType·createdFrom/To, 최근 것부터)', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_OPS', 'false')
    const api = await import('../src/api/auditLogs')
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [], page: 1, size: 50, totalCount: 0, totalPages: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await api.listAuditLogs(admin(), { eventType: 'REASSIGN', targetType: 'ticket', days: 7 })
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://x')
    expect(url.pathname).toBe('/api/v1/audit-logs')
    expect(url.searchParams.get('eventType')).toBe('REASSIGN')
    expect(url.searchParams.get('targetType')).toBe('ticket')
    expect(url.searchParams.get('sort')).toBe('createdAt,desc')
    expect(url.searchParams.get('createdFrom')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(url.searchParams.get('createdTo')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('운영 기록 화면', () => {
  it('기록을 한글로 보여 주고(이벤트 이름 + 서버 코드), 구분·이벤트로 거른다', async () => {
    renderAs('EMP-1178', '/audit')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(within(nav).getByRole('button', { name: '운영 기록' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '운영 기록을 확인해요' }, SLOW)).toBeInTheDocument()
    // 칼럼 순서: 시각 → 구분 → 이벤트 → 처리자 → 결과 · 사유
    const heads = await screen.findAllByRole('columnheader', undefined, SLOW)
    expect(heads.map((h) => h.textContent)).toEqual(['시각', '구분', '이벤트', '처리자', '결과 · 사유'])
    // 결과는 서버 코드(QUEUED)가 아니라 한글로, 이벤트는 한글 이름 아래에 서버 코드가 같이 보인다
    expect(await screen.findByText('재처리 예약', undefined, SLOW)).toBeInTheDocument()
    expect(screen.getAllByText('INTEGRATION_RETRY').length).toBeGreaterThan(0)
    expect(screen.queryByText('QUEUED')).toBeNull()
    expect(screen.getAllByText('시스템').length).toBeGreaterThan(0) // 처리자가 없으면 시스템
    // 접수번호는 구분 칸 둘째 줄에 (종류가 첫 줄)
    expect(screen.getAllByText('RCPT-0881')[0].closest('td')).toHaveTextContent('접수RCPT-0881')
    // 구분 탭: 문서만
    await userEvent.click(screen.getByRole('button', { name: '문서' }))
    expect(await screen.findByText('현행 v1 → v2', undefined, SLOW)).toBeInTheDocument()
    expect(screen.queryByText('배정 실패')).toBeNull()
    // 이벤트 선택 상자로 거른다 (구분: 전체로 돌린 뒤)
    await userEvent.click(screen.getByRole('button', { name: '전체' }))
    await userEvent.click(screen.getByRole('combobox', { name: '이벤트' }))
    await userEvent.click(await screen.findByRole('option', { name: '재배정' }))
    expect(await screen.findByText('배정 실패', undefined, SLOW)).toBeInTheDocument()
    expect(screen.queryByText('근거 전체 차단, 담당자 연결 제안')).toBeNull()
  })

  it('접수번호를 누르면 화면은 그대로 두고 오른쪽에 접수 상세 패널이 열리고, 다른 접수번호를 누르면 패널만 바뀐다', async () => {
    renderAs('EMP-1178', '/audit')
    const first = (await screen.findAllByRole('button', { name: /접수 RCPT-0881 상세 보기/ }, SLOW))[0]
    expect(screen.queryByRole('complementary', { name: '티켓 상세' })).toBeNull()
    await userEvent.click(first)
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    expect(await within(panel).findByText('RCPT-0881', undefined, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '운영 기록을 확인해요' })).toBeInTheDocument() // 화면은 그대로
    // 다른 접수(재배정 기록)를 누르면 패널은 하나인 채로 내용만 바뀐다
    await userEvent.click(screen.getAllByRole('button', { name: /상세 보기/ }).find((b) => !/RCPT-0881/.test(b.getAttribute('aria-label') ?? ''))!)
    await waitFor(() => expect(within(screen.getByRole('complementary', { name: '티켓 상세' })).queryByText('RCPT-0881')).toBeNull(), SLOW)
    expect(screen.getAllByRole('complementary', { name: '티켓 상세' })).toHaveLength(1)
  })

  it('사용자 대상 기록(로그인 차단 등)은 계정 목록에서 찾은 이름·사번을 구분 칸 둘째 줄에 보인다', async () => {
    const { MOCK_ACCOUNTS } = await import('../src/api/mock/accounts')
    const who = MOCK_ACCOUNTS.find((u) => u.id === 6)
    expect(who).toBeTruthy()
    renderAs('EMP-1178', '/audit')
    expect((await screen.findAllByRole('button', { name: `${who!.name} 계정 관리에서 보기` }, SLOW)).length).toBeGreaterThan(0)
  })

  it('사용자 이름을 누르면 계정 관리가 그 사번으로 검색된 채 열린다', async () => {
    const { MOCK_ACCOUNTS } = await import('../src/api/mock/accounts')
    const who = MOCK_ACCOUNTS.find((u) => u.id === 6)!
    renderAs('EMP-1178', '/audit')
    await userEvent.click((await screen.findAllByRole('button', { name: `${who.name} 계정 관리에서 보기` }, SLOW))[0])
    expect(await screen.findByRole('textbox', { name: '계정 검색' }, SLOW)).toHaveValue(who.employeeNo)
  })

  it('담당자는 들어올 수 없다', async () => {
    renderAs('EMP-1004', '/audit')
    await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(screen.queryByRole('heading', { name: '운영 기록을 확인해요' })).toBeNull()
  })
})
