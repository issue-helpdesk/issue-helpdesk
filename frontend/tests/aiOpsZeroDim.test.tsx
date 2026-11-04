/**
 * AI 운영 "상담 건수와 비용" 표: 값이 0 인 칸(전체 상담·AI 해결·추정 비용)을 흐리게(.zero) 해서 값이 있는 칸과 구분한다.
 * 모의 데이터에는 0 이 거의 없어서, 사용 현황 응답을 직접 만들어 확인한다. 통계 화면의 표는 영향받지 않는다.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

vi.mock('../src/api/aiOps', async (orig) => {
  const real = await orig<typeof import('../src/api/aiOps')>()
  return {
    ...real,
    getAiUsage: async () => ({
      ok: true,
      data: {
        range: 'month',
        labels: ['10.28', '10.29', '11.2'],
        tot: [0, 1, 5],
        ai: [0, 0, 1],
        cost: [0, 0, 0.2],
        sum: { tot: 6, ai: 1, cost: 0.2 },
        budget: { cost: 0.2, budget: 100, scope: 'period' },
      },
    }),
  }
})

describe('AI 운영 표: 0 인 칸은 흐리게', () => {
  it('값이 0 인 칸만 흐리고, 값이 있는 칸은 그대로다', async () => {
    tokenStore.set('mock.EMP-1178')
    const { container } = render(
      <MemoryRouter initialEntries={['/ai']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: '표' }, { timeout: 3000 }))
    const rows = await waitFor(() => {
      const r = [...container.querySelectorAll('table.hvt tbody tr')]
      expect(r).toHaveLength(3)
      return r
    })
    const flags = rows.map((r) => [...r.querySelectorAll('td')].map((td) => td.classList.contains('zero')))
    // [전체 상담, AI 해결, 추정 비용]
    expect(flags).toEqual([
      [true, true, true], // 10.28: 모두 0
      [false, true, true], // 10.29: 상담 1건, AI 해결 0, 비용 $0.0
      [false, false, false], // 11.2: 값이 모두 있음
    ])
  })
})
