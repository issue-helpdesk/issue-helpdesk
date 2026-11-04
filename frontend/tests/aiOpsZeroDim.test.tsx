/**
 * AI 운영 숫자 카드: 값이 0 이면 숫자를 흐리게(.zero) 해서 값이 있는 카드와 구분한다.
 * 모의 데이터에는 0 인 기간이 없어서, 사용 현황 응답을 직접 만들어 확인한다.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const usage = vi.hoisted(() => ({ zero: true }))

vi.mock('../src/api/aiOps', async (orig) => {
  const real = await orig<typeof import('../src/api/aiOps')>()
  return {
    ...real,
    getAiUsage: async () => ({
      ok: true,
      data: usage.zero
        ? { range: 'day', labels: ['9시'], tot: [0], ai: [0], cost: [0], sum: { tot: 0, ai: 0, cost: 0 }, budget: { cost: 0, budget: 100, scope: 'last' } }
        : { range: 'day', labels: ['9시'], tot: [10], ai: [7], cost: [1.5], sum: { tot: 10, ai: 7, cost: 1.5 }, budget: { cost: 1.5, budget: 100, scope: 'last' } },
    }),
  }
})

function renderAdmin() {
  tokenStore.set(`mock.${MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!.employeeNo}`)
  return render(
    <MemoryRouter initialEntries={['/ai']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AI 운영: 0 인 숫자 카드는 흐리게', () => {
  it('상담·해결률·비용·예산 사용이 모두 0 이면 네 카드 모두 흐리다', async () => {
    usage.zero = true
    const { container } = renderAdmin()
    await screen.findByText('기간 내 AI 상담', {}, { timeout: 3000 })
    await waitFor(() => expect(container.querySelectorAll('.kpis .kpi.zero')).toHaveLength(4))
  })

  it('값이 있으면 흐리지 않다', async () => {
    usage.zero = false
    const { container } = renderAdmin()
    await screen.findByText('기간 내 AI 상담', {}, { timeout: 3000 })
    await waitFor(() => expect(container.querySelectorAll('.kpis .kpi').length).toBe(4))
    expect(container.querySelectorAll('.kpis .kpi.zero')).toHaveLength(0)
  })
})
