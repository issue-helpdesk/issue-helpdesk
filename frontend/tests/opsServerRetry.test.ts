/**
 * 운영 현황의 ITSM 확인·재시도 서버 연결 (docs/api/03 TK-11·TK-12). 가짜 fetch 로 요청과 응답 처리를 확인한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const job = (id: number, over: Record<string, unknown> = {}) => ({ id, ticketId: 43, jobType: 'JIRA_CREATE', retryOfJobId: null, status: 'NEEDS_ADMIN', attempts: 3, nextRetryAt: null, lastError: 'ITSM 서버 오류입니다. (503)', createdAt: '2026-11-04T10:00:00+09:00', updatedAt: null, ...over })
const ticket = { id: 43, receiptNo: 'RCPT-0043', jiraKey: null, summary: '테스트', jiraSyncStatus: 'PENDING', assignStatus: 'PENDING', workStatus: null, transitionStatus: 'IDLE', needsAdmin: false }

describe('운영 현황 ITSM 확인·재시도 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const calls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0])}`)
  async function load(intake = true) {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
    vi.stubEnv('VITE_SERVER_INTAKE', intake ? 'true' : 'false')
    return import('../src/api/ops')
  }
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('접수를 서버로 보내지 않는 환경에서는 요청하지 않고 안내만 한다', async () => {
    const ops = await load(false)
    expect(await ops.retryJiraCreate(admin(), 43, '사유')).toMatchObject({ ok: false, error: { code: 'NOT_READY' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('실패한 생성 작업을 골라 재처리를 등록하고(201) 접수를 다시 읽는다', async () => {
    const ops = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(60, { jobType: 'JIRA_ASSIGN' }), job(61)] }))
    fetchMock.mockResolvedValueOnce(json(201, job(62, { retryOfJobId: 61, status: 'PENDING' })))
    fetchMock.mockResolvedValueOnce(json(200, ticket))
    const r = await ops.retryJiraCreate(admin(), 43, 'ITSM 장애 복구 후 재처리')
    expect(r.ok && r.data.outcome).toBe('REGISTERED')
    expect(calls()).toEqual(['GET /api/v1/tickets/43/integration-jobs', 'POST /api/v1/tickets/43/integration-jobs', 'GET /api/v1/tickets/43'])
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ retryOfJobId: 61, reason: 'ITSM 장애 복구 후 재처리' })
  })

  it('ITSM 에 이미 있어 연결만 했으면(200 LINKED_EXISTING) 접수를 다시 읽지 않는다', async () => {
    const ops = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(61)] }))
    fetchMock.mockResolvedValueOnce(json(200, { ticket: { ...ticket, jiraKey: 'ITHD-43', jiraSyncStatus: 'SYNCED' }, job: null, recoveryResult: 'LINKED_EXISTING' }))
    const r = await ops.retryJiraCreate(admin(), 43, '확인')
    expect(r.ok && [r.data.outcome, r.data.jiraKey]).toEqual(['LINKED_EXISTING', 'ITHD-43'])
    expect(calls()).toHaveLength(2)
  })

  it('상태 다시 반영은 상태 변경 작업을 고르고, 이미 반영돼 있으면 ALREADY_APPLIED', async () => {
    const ops = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(61), job(70, { jobType: 'JIRA_TRANSITION' })] }))
    fetchMock.mockResolvedValueOnce(json(200, { ticket: { ...ticket, workStatus: 'FIN' }, job: null, recoveryResult: 'ALREADY_APPLIED' }))
    const r = await ops.recheckTransition(admin(), 43, '확인')
    expect(r.ok && r.data.outcome).toBe('ALREADY_APPLIED')
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body)).retryOfJobId).toBe(70)
  })

  it('다시 처리할 실패 작업이 없거나 이미 재처리한 작업뿐이면 요청하지 않는다', async () => {
    const ops = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(61), job(62, { retryOfJobId: 61, status: 'DONE' })] }))
    expect(await ops.retryJiraCreate(admin(), 43, '사유')).toMatchObject({ ok: false, error: { code: 'INTEGRATION_RETRY_NOT_ALLOWED' } })
    expect(calls()).toEqual(['GET /api/v1/tickets/43/integration-jobs'])
  })

  it('서버가 거절하면(409·503) 그 오류를 그대로 돌려준다', async () => {
    const ops = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(61)] }))
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: 'INTEGRATION_JOB_IN_PROGRESS', message: '이미 연동 작업이 진행 중입니다.', details: [], traceId: 't' } }))
    expect(await ops.retryJiraCreate(admin(), 43, '사유')).toMatchObject({ ok: false, error: { code: 'INTEGRATION_JOB_IN_PROGRESS' } })
    fetchMock.mockResolvedValueOnce(json(200, { items: [job(61)] }))
    fetchMock.mockResolvedValueOnce(json(503, { error: { code: 'SERVICE_UNAVAILABLE', message: 'ITSM 결과를 확인할 수 없습니다.', details: [], traceId: 't' } }))
    expect(await ops.retryJiraCreate(admin(), 43, '사유')).toMatchObject({ ok: false, error: { code: 'SERVICE_UNAVAILABLE' } })
  })

  it('관리자가 아니면 요청하지 않는다', async () => {
    const ops = await load()
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    expect(await ops.retryJiraCreate(staff, 43, '사유')).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
