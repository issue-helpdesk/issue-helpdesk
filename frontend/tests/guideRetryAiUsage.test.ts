/**
 * 가이드 적재 다시 시도(DC-10)와 AI 사용 현황(OP-03) 서버 연결. 가짜 fetch 로 요청과 응답 처리를 확인한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetGuideMock, retryGuideIngest } from '../src/api/guides'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('가이드 적재 다시 시도 (모의)', () => {
  it('검색 준비에 실패한 버전이 아니면 다시 시도할 수 없다', async () => {
    resetGuideMock()
    expect(await retryGuideIngest(admin(), 1, 12)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_RETRYABLE' } })
    expect(await retryGuideIngest(admin(), 1, 999)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_FOUND' } })
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    expect((await retryGuideIngest(staff, 1, 12)).ok).toBe(false)
  })
})

describe('서버 모드', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('적재 다시 시도는 retry 를 요청하고 검색 준비 중으로 바꾼다 (DC-10)', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_GUIDE', 'false')
    const api = await import('../src/api/guides')
    fetchMock.mockResolvedValueOnce(json(202, { id: 31, documentId: 3, version: 'v1.3', viewScope: 'ALL', transferPolicy: 'ALLOWED', isCurrent: false, versionState: 'DRAFT', ingestStatus: 'PENDING', ingestError: null }))
    const r = await api.retryGuideIngest(admin(), 3, 31)
    expect(r.ok && [r.data.version, r.data.ready, r.data.error]).toEqual(['v1.3', '준비 중', undefined])
    expect(`${(fetchMock.mock.calls[0][1] as RequestInit).method} ${String(fetchMock.mock.calls[0][0])}`).toBe('POST /api/v1/documents/3/versions/31/retry')
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: 'DOCUMENT_VERSION_NOT_RETRYABLE', message: '적재에 실패한 버전만 다시 시도할 수 있습니다.', details: [], traceId: 't' } }))
    expect(await api.retryGuideIngest(admin(), 3, 31)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_RETRYABLE' } })
  })

  it('AI 사용 현황은 응답 시간이 없어도(null) 값을 돌려준다 (OP-03)', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_OPS', 'false')
    const api = await import('../src/api/aiOps')
    fetchMock.mockResolvedValueOnce(
      json(200, {
        period: { from: '2026-10-22', to: '2026-11-04', interval: 'DAY' },
        totals: { aiConsultationCount: 10, aiResolvedCount: 6, aiResolvedRate: 0.6, callCount: 0, failedCount: 0, avgLatencyMs: null, inputTokens: 0, outputTokens: 0, estimatedCost: 1.5, unpricedModels: [], budget: 20, budgetUsageRate: 0.075 },
        byPurpose: [],
        byModel: [],
        trend: [{ date: '2026-11-04', aiConsultationCount: 10, aiResolvedCount: 6, callCount: 0, estimatedCost: 1.5 }],
      }),
    )
    const r = await api.getAiUsage(admin(), 'day')
    expect(r.ok && [r.data.sum.tot, r.data.sum.ai, r.data.calls?.avgLatencyMs, r.data.budget?.budget]).toEqual([10, 6, null, 20])
    expect(await api.getAiUsage(admin(), 'year')).toMatchObject({ ok: false, error: { code: 'UNSUPPORTED_RANGE' } })
  })
})
