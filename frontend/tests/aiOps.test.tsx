/**
 * 관리자 AI 운영 (EMP-1178 이건우). 모의 모드 화면·API 테스트와, 가짜 fetch 로 OP-03 서버 계약(docs/api/05)을 확인하는 서버 모드 테스트.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { getAiUsage, listGoldenSet } from '../src/api/aiOps'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
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

describe('AI 운영 API (모의)', () => {
  it('기간별 상담·AI 해결·비용을 주고 AI 해결은 전체 상담을 넘지 않는다', async () => {
    for (const range of ['day', 'month', 'year'] as const) {
      const r = await getAiUsage(admin(), range)
      expect(r.ok).toBe(true)
      if (!r.ok) continue
      expect(r.data.labels).toHaveLength(range === 'day' ? 14 : range === 'month' ? 12 : 3)
      expect(r.data.ai.every((a, i) => a <= r.data.tot[i])).toBe(true)
      expect(r.data.sum.tot).toBe(r.data.tot.reduce((a, b) => a + b, 0))
      expect(r.data.budget?.scope).toBe('last')
    }
  })

  it('관리자만 볼 수 있다', async () => {
    expect((await getAiUsage(staff(), 'day')).ok).toBe(false)
    expect((await listGoldenSet(staff())).ok).toBe(false)
  })

  it('답변 품질 평가는 보완 필요 → 검토 필요 → 통과 순이다', async () => {
    const r = await listGoldenSet(admin())
    expect(r.ok && r.data.map((g) => g.st).slice(0, 3)).toEqual(['보완 필요', '보완 필요', '검토 필요'])
    expect(r.ok && r.data).toHaveLength(12)
  })
})

describe('AI 운영 화면', () => {
  it('KPI·그래프는 유지하고 품질 평가는 숨긴다. 담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/ai')
    expect(await screen.findByRole('heading', { name: 'AI 사용량과 비용을 살펴봐요', level: 1 }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('기간 내 AI 상담').closest('.kpi')!.querySelector('b')!.textContent).not.toBe('-'), SLOW)
    expect(screen.getByText('오늘 예산 사용')).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /상담 건수와 AI 해결 곡선/ }, SLOW)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '월' }))
    expect(await screen.findByText('이번 달 예산 사용', {}, SLOW)).toBeInTheDocument()
    expect(screen.queryByText(/답변 품질 평가/)).toBeNull()
    expect(screen.queryByRole('button', { name: '보완 필요' })).toBeNull()
    unmount()
    renderAs('EMP-1004', '/ai')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })


})

/* ------------------------------------------------------------------ 서버 모드 */
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const USAGE = {
  period: { from: '2026-10-20', to: '2026-11-02', interval: 'DAY' },
  totals: { aiConsultationCount: 160, aiResolvedCount: 92, aiResolvedRate: 0.575, callCount: 812, failedCount: 6, avgLatencyMs: 2140, inputTokens: 1532000, outputTokens: 214000, estimatedCost: 7.81, budget: 30, budgetUsageRate: 0.26 },
  byPurpose: [],
  byModel: [],
  trend: [
    { date: '2026-10-31', aiConsultationCount: 9, aiResolvedCount: 5, callCount: 44, estimatedCost: 0.41 },
    { date: '2026-11-01', aiConsultationCount: 12, aiResolvedCount: 7, callCount: 51, estimatedCost: 0.52 },
  ],
}

describe('서버 모드 AI 사용 현황 (VITE_USE_MOCK_OPS=false)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  async function load() {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_OPS', 'false')
    return import('../src/api/aiOps')
  }
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('OP-03 응답을 화면의 값으로 바꾸고 기간·단위를 쿼리로 보낸다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(200, USAGE))
    const r = await api.getAiUsage(admin(), 'day')
    expect(r.ok && r.data).toMatchObject({ labels: ['10.31', '11.1'], tot: [9, 12], ai: [5, 7], cost: [0.41, 0.52], sum: { tot: 160, ai: 92, cost: 7.81 }, budget: { cost: 7.81, budget: 30, scope: 'period' }, calls: { callCount: 812, failedCount: 6, avgLatencyMs: 2140 } })
    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toMatch(/^\/api\/v1\/dashboard\/ai-usage\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&interval=DAY$/)
  })

  it('월별은 MONTH 단위로, 예산이 없으면 null 로 두며, 연도별은 요청하지 않는다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(200, { ...USAGE, totals: { ...USAGE.totals, budget: null }, trend: [{ date: '2026-10-01', aiConsultationCount: 100, aiResolvedCount: 60, callCount: 1, estimatedCost: 3 }] }))
    const r = await api.getAiUsage(admin(), 'month')
    expect(r.ok && r.data.labels).toEqual(['26.10'])
    expect(r.ok && r.data.budget).toBeNull()
    expect(String(fetchMock.mock.calls[0][0])).toContain('interval=MONTH')
    expect(await api.getAiUsage(admin(), 'year')).toMatchObject({ ok: false, error: { code: 'UNSUPPORTED_RANGE' } })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('서버가 아직 없으면(404) 오류를 그대로 돌려준다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(404, { error: { code: 'NOT_FOUND', message: '찾을 수 없어요.', details: null, traceId: 't' } }))
    expect(await api.getAiUsage(admin(), 'day')).toMatchObject({ ok: false, error: { code: 'NOT_FOUND' } })
  })
})
