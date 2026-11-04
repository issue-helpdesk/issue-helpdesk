/**
 * 담당자 지정·재배정 서버 연결 (docs/api/03 TK-09 PUT /tickets/{id}/assignment). 가짜 fetch 로 요청과 응답 처리를 확인한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const ticket = (over: Record<string, unknown> = {}) => ({ id: 4, receiptNo: 'RCPT-0004', group: { id: 5, name: '네트워크팀' }, assignee: null, assignStatus: 'NEEDS_ADMIN', workStatus: 'RDY', transitionStatus: 'IDLE', ...over })

describe('담당자 지정·재배정 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const calls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0])}`)
  async function load(intake = true) {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
    vi.stubEnv('VITE_SERVER_INTAKE', intake ? 'true' : 'false')
    return import('../src/api/tickets')
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
    const t = await load(false)
    expect(await t.reassignTicket(admin(), 4, { assigneeId: 9, reason: '업무량' })).toMatchObject({ ok: false, error: { code: 'NOT_READY' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('접수의 현재 그룹과 함께 배정을 예약하고(PENDING) 응답을 그대로 돌려준다', async () => {
    const t = await load()
    fetchMock.mockResolvedValueOnce(json(200, ticket()))
    fetchMock.mockResolvedValueOnce(json(200, ticket({ assignStatus: 'PENDING', assignee: { id: 9, name: '조민재' } })))
    const r = await t.reassignTicket(admin(), 4, { assigneeId: 9, reason: '자동배정 실패' })
    expect(r.ok && r.data.assignStatus).toBe('PENDING')
    expect(calls()).toEqual(['GET /api/v1/tickets/4', 'PUT /api/v1/tickets/4/assignment'])
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ groupId: 5, assigneeId: 9, reason: '자동배정 실패' })
  })

  it('담당 그룹이 없거나 관리자가 아니면 요청하지 않는다', async () => {
    const t = await load()
    fetchMock.mockResolvedValueOnce(json(200, ticket({ group: null })))
    expect(await t.reassignTicket(admin(), 4, { assigneeId: 9, reason: '사유' })).toMatchObject({ ok: false, error: { code: 'VALIDATION_ERROR' } })
    expect(calls()).toEqual(['GET /api/v1/tickets/4'])
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    expect(await t.reassignTicket(staff, 4, { assigneeId: 9, reason: '사유' })).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
  })

  it('서버가 거절하면(배정 불가·진행 중) 그 오류를 돌려준다', async () => {
    const t = await load()
    fetchMock.mockResolvedValueOnce(json(200, ticket()))
    fetchMock.mockResolvedValueOnce(json(422, { error: { code: 'ASSIGNEE_NOT_ASSIGNABLE', message: 'Jira 계정이 연결되지 않은 담당자입니다.', details: [], traceId: 't' } }))
    expect(await t.reassignTicket(admin(), 4, { assigneeId: 9, reason: '사유' })).toMatchObject({ ok: false, error: { code: 'ASSIGNEE_NOT_ASSIGNABLE' } })
    fetchMock.mockResolvedValueOnce(json(200, ticket()))
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: 'INTEGRATION_JOB_IN_PROGRESS', message: '이미 연동 작업이 진행 중입니다.', details: [], traceId: 't' } }))
    expect(await t.reassignTicket(admin(), 4, { assigneeId: 9, reason: '사유' })).toMatchObject({ ok: false, error: { code: 'INTEGRATION_JOB_IN_PROGRESS' } })
  })
})
