/**
 * 관리자 통계 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다. 담당자(EMP-1004)는 기존 담당자 통계가 그대로 열린다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { getAdminStatsSource, listTeams } from '../src/api/adminStats'
import { loadOverview } from '../src/views/admin/statsOverview'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import type { User } from '../src/api/types'

const SLOW = { timeout: 4000 }

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
const sec = (name: string) => screen.getByRole('region', { name }) as HTMLElement

describe('관리자 통계 API (모의)', () => {
  it('전체 접수와 AI 상담 건수, 팀·구성원을 준다', async () => {
    const all = await loadOverview(admin(), 'm', 'd')
    const ov = all.ok ? (all.data.extra as import('../src/api/adminStats').StatsOverview) : null
    expect(ov?.total).toBeGreaterThan(40)
    expect(ov?.groups.find((g) => g.name === '네트워크팀')?.members.map((m) => m.name)).toContain('성민경')
    expect(ov?.trend?.labels.length).toBeGreaterThan(20)
    const ai = await getAdminStatsSource(admin(), 'ai', 'm')
    expect(ai.ok).toBe(true)
    const counts = ai.ok ? (ai.data.extra as Record<string, number>) : {}
    expect(counts.all).toBe(counts.ok + counts.pend + counts.unr)
    const teams = await listTeams(admin())
    expect(teams.ok && teams.data.map((t) => t.name)).toContain('네트워크팀')
    expect(teams.ok && teams.data.find((t) => t.name === '네트워크팀')?.members).toContain('성민경')
  })
})

describe('관리자 통계 화면', () => {
  it('AI 상담 결과·담당자 처리·추이·진행도·긴급도 구역이 보이고, 팀을 누르면 구성원별 진행도가 열린다', async () => {
    renderAs('EMP-1178', '/stats')
    expect(await screen.findByRole('heading', { name: '통계', level: 1 }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(within(sec('AI 상담 결과')).getByRole('button', { name: /^AI 해결 [1-9]/ })).toBeInTheDocument(), SLOW)
    await waitFor(() => expect(within(sec('담당자 처리 (티켓)')).getByRole('button', { name: /^배정 전 [1-9]/ })).toBeInTheDocument(), SLOW)
    expect(within(sec('담당자 처리 (티켓)')).getByText(/해결 완료 비율은/)).toBeInTheDocument()
    const prog = sec('팀별 진행도')
    await waitFor(() => expect(within(prog).getByRole('button', { name: /^네트워크팀/ })).toBeInTheDocument(), SLOW)
    await userEvent.click(within(prog).getByRole('button', { name: /^네트워크팀/ }))
    expect(await within(prog).findByText('네트워크팀 · 구성원별 진행도', {}, SLOW)).toBeInTheDocument()
    // 팀원 카드: 누르면 오른쪽 칸에 상태별 건수와 티켓 목록 버튼이 열린다 (개인별 분류 도넛·분류별 보기는 없다)
    await userEvent.click(within(prog).getByRole('button', { name: /^성민경 처리 상태/ }))
    expect(await within(prog).findByRole('button', { name: /티켓 목록/ })).toBeInTheDocument()
    expect(within(prog).getByText(/전체 \d+건 · 완료 \d+%/)).toBeInTheDocument()
    expect(within(prog).queryByRole('button', { name: '분류별' })).toBeNull()
    // 긴급도 분포 구역은 대시보드로 옮겼다
    expect(screen.queryByRole('region', { name: '긴급도 분포' })).toBeNull()
  })

  it('오늘을 고르면 추이 그래프 대신 오늘 접수·AI 해결 건수만 보인다', async () => {
    renderAs('EMP-1178', '/stats')
    await userEvent.click(await screen.findByRole('button', { name: '오늘' }, SLOW))
    const tr = sec('접수 추이')
    expect(await within(tr).findByText('오늘 AI 해결 (티켓 없음)', {}, SLOW)).toBeInTheDocument()
    expect(within(tr).getByText('오늘 접수 (담당자 처리)')).toBeInTheDocument()
  })

  it('담당자는 담당자 통계가 그대로 열린다', async () => {
    renderAs('EMP-1004', '/stats')
    expect(await screen.findByRole('button', { name: /내 통계/ }, SLOW)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'AI 상담 결과' })).toBeNull()
  })
})
