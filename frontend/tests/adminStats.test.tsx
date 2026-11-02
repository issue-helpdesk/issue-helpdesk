/**
 * 관리자 통계 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다. 담당자(EMP-1004)는 기존 담당자 통계가 그대로 열린다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { getAdminStatsSource, listTeams } from '../src/api/adminStats'
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
    const all = await getAdminStatsSource(admin(), 'sum', 'm')
    expect(all.ok && all.data.items.length).toBeGreaterThan(40)
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
    const prog = sec('팀별·분류별 진행도')
    await waitFor(() => expect(within(prog).getByRole('button', { name: /^네트워크팀/ })).toBeInTheDocument(), SLOW)
    await userEvent.click(within(prog).getByRole('button', { name: /^네트워크팀/ }))
    expect(await within(prog).findByText('네트워크팀 · 구성원별 진행도', {}, SLOW)).toBeInTheDocument()
    await userEvent.click(within(prog).getByRole('button', { name: /^성민경/ }))
    expect(await within(prog).findByText('성민경 · 개인 현황')).toBeInTheDocument()
    await userEvent.click(within(prog).getByRole('button', { name: '분류별' }))
    expect(await within(prog).findByRole('button', { name: /^계정·로그인/ }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(within(sec('긴급도 분포 (P1~P4)')).getByRole('button', { name: /^P1 [0-9]+건/ })).toBeInTheDocument(), SLOW)
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
