/**
 * 관리자 대시보드 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { getDashSnapshot, searchTickets } from '../src/api/dash'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import type { User } from '../src/api/types'

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

describe('대시보드 API (모의)', () => {
  it('상태별 건수, 연동·배정 확인 원인별 건수, 긴급·높음 미해결 상위 3건을 준다', async () => {
    const r = await getDashSnapshot(admin())
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data.rdy).toBeGreaterThan(0)
    expect(r.data.wip).toBeGreaterThan(0)
    expect(r.data.fin).toBeGreaterThan(0)
    const a = r.data.attention
    expect(a.total).toBe(a.jira + a.sync + a.assign)
    expect(a.sync).toBe(1)
    expect(a.assign).toBe(2)
    const u = r.data.unresolved
    expect(u.total).toBe(u.p1 + u.p2)
    expect(u.top).toHaveLength(3)
    // P1 이 먼저
    expect(u.top[0].urgency).toBe('P1')
    expect(u.top.every((t) => t.workStatus !== 'CLS')).toBe(true)
  })

  it('검색은 접수번호·제목으로 최근 10건까지 찾는다', async () => {
    const r = await searchTickets(admin(), 'VPN')
    expect(r.ok && r.data.items.length).toBeGreaterThan(0)
    expect(r.ok && r.data.items.length).toBeLessThanOrEqual(10)
  })
})

describe('대시보드 화면', () => {
  it('처리 현황·연동 확인 띠·긴급 미해결이 보이고, 담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/dash')
    expect(await screen.findByRole('heading', { name: '대시보드', level: 1 }, SLOW)).toBeInTheDocument()
    const pipe = await screen.findByRole('group', { name: '처리 현황' })
    await waitFor(() => expect(within(pipe).getByRole('button', { name: /^처리 대기 [1-9]/ })).toBeInTheDocument(), SLOW)
    expect(within(pipe).getByRole('button', { name: /^연동·배정 확인 [1-9]/ })).toHaveClass('al')
    expect(await screen.findByRole('region', { name: '연동·배정 확인 필요' }, SLOW)).toBeInTheDocument()
    // ITSM 댓글·멘션 알림은 이번 기능에서 제외했다
    expect(screen.queryByRole('region', { name: '확인할 ITSM 알림' })).toBeNull()
    const urg = screen.getByRole('region', { name: '긴급·높음 미해결' })
    await waitFor(() => expect(urg.querySelectorAll('.orow')).toHaveLength(3), SLOW)
    // 긴급도 분포는 긴급·높음 미해결 카드 바로 위에 있다
    const dist = await screen.findByRole('region', { name: '긴급도 분포' }, SLOW)
    expect(dist.compareDocumentPosition(urg) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(await within(dist).findByRole('button', { name: /^긴급 [0-9]+건/ }, SLOW)).toBeInTheDocument()
    unmount()
    renderAs('EMP-1004', '/dash')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('검색하면 결과만 보이고, 지우면 대시보드로 돌아온다', async () => {
    renderAs('EMP-1178', '/dash')
    const box = await screen.findByRole('searchbox', { name: '전체 문의 검색' }, SLOW)
    await userEvent.type(box, 'VPN')
    const res = await screen.findByRole('region', { name: '검색 결과' }, SLOW)
    await waitFor(() => expect(res.querySelectorAll('.dtr').length).toBeGreaterThan(0), SLOW)
    expect(screen.queryByRole('group', { name: '처리 현황' })).toBeNull()
    await userEvent.click(within(res).getByRole('button', { name: '검색 지우기' }))
    expect(await screen.findByRole('group', { name: '처리 현황' })).toBeInTheDocument()
  })
})
