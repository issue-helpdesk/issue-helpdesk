/**
 * 서버 모드(VITE_USE_MOCK_TICKET=false)의 담당 그룹 구성원·부재·업무량.
 * 서버는 띄우지 않고 가짜 fetch 로 서버 계약(docs/api/05 RF-03·04, TO-01, docs/api/03 TK-05)대로 응답을 만들어 준다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../src/api/types'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const admin = { id: 1, employeeNo: 'EMP-1178', name: '이건우', serviceRole: 'ADMIN' } as User

const member = (id: number, name: string, over: Record<string, unknown> = {}) => ({
  userId: id,
  user: { id, employeeNo: `EMP-${id}`, name },
  position: '팀원',
  memberRole: 'AGENT',
  assignable: true,
  hasJiraAccount: true,
  jiraAccountId: null,
  isActive: true,
  skills: [],
  openTicketCount: 0,
  onLeave: false,
  ...over,
})
const ticket = (id: number, assignee: number | null, workStatus: string, urgency: string) => ({
  id,
  receiptNo: `RCPT-${id}`,
  jiraKey: null,
  inquiryId: id,
  requester: { id: 9, employeeNo: 'EMP-9', name: '문의자' },
  summary: `접수 ${id}`,
  category: { code: 'NET', name: 'VPN·네트워크' },
  urgency,
  group: { id: 3, name: '네트워크팀' },
  assignee: assignee ? { id: assignee, employeeNo: `EMP-${assignee}`, name: `담당 ${assignee}` } : null,
  jiraSyncStatus: 'SYNCED',
  assignStatus: 'ASSIGNED',
  workStatus,
  requestedWorkStatus: null,
  transitionStatus: 'IDLE',
  workStatusConfirmedAt: null,
  needsAdmin: false,
  displayStatus: 'progress',
  createdAt: '2026-11-02T09:00:00+09:00',
})
const page = (items: unknown[]) => ({ items, page: 1, size: 100, totalCount: items.length, totalPages: 1 })

let fetchMock: ReturnType<typeof vi.fn>
const urls = () => fetchMock.mock.calls.map((c) => String(c[0]))

/** 주소를 보고 서버처럼 답한다 */
const server = (over: { timeOff?: Response } = {}) =>
  fetchMock.mockImplementation(async (u: string) => {
    if (u.startsWith('/api/v1/support-groups/3/members')) return json(200, { items: [member(10, '성민경'), member(11, '정서현', { onLeave: true }), member(12, '황진혁', { hasJiraAccount: false }), member(13, '퇴사자', { isActive: false })] })
    if (u.startsWith('/api/v1/support-groups/1/members')) return json(200, { items: [member(20, '박서연')] })
    if (u.startsWith('/api/v1/support-groups')) return json(200, { items: [{ id: 1, name: '서비스데스크' }, { id: 3, name: '네트워크팀' }] })
    if (u.startsWith('/api/v1/time-off')) return over.timeOff ?? json(200, page([{ id: 1, userId: 11, timeOffType: 'HALF_PM' }]))
    if (u.startsWith('/api/v1/tickets')) return json(200, page([ticket(1, 10, 'RDY', 'P2'), ticket(2, 10, 'WIP', 'P2'), ticket(3, 10, 'WIP', 'P1'), ticket(4, 20, 'WIP', 'P4'), ticket(5, null, 'RDY', 'P3')]))
    return json(404, { error: { code: 'NOT_FOUND', message: 'x', details: null, traceId: 't' } })
  })

async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_TICKET', 'false')
  const api = await import('../src/api/reference')
  api.resetReferenceCache()
  return api
}

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('서버 모드 담당 그룹 구성원', () => {
  it('접수가 100건을 넘으면 다음 쪽까지 읽어 팀원별 상태와 긴급도를 합산한다', async () => {
    const api = await load()
    server()
    const base = fetchMock.getMockImplementation()! as (url: string) => Promise<Response>
    fetchMock.mockImplementation(async (url: string) => {
      if (!url.startsWith('/api/v1/tickets')) return base(url)
      const n = Number(new URL(url, 'http://test').searchParams.get('page'))
      return json(200, { items: n === 1 ? Array.from({ length: 100 }, (_, i) => ticket(i + 1, 10, 'RDY', 'P2')) : [ticket(101, 10, 'WIP', 'P1')], page: n, size: 100, totalCount: 101, totalPages: 2 })
    })
    const r = await api.listBoard(admin)
    expect(r.ok && r.data['네트워크팀'][0]).toMatchObject({ rdy: 100, wip: 1, pri: { P1: 1, P2: 100 } })
    expect(urls().filter((url) => url.startsWith('/api/v1/tickets')).map((url) => new URL(url, 'http://test').searchParams.get('page'))).toEqual(['1', '2'])
  })

  it('다음 쪽 조회가 실패하면 일부 집계를 전체 건수나 0건으로 표시하지 않는다', async () => {
    const api = await load()
    server()
    const base = fetchMock.getMockImplementation()! as (url: string) => Promise<Response>
    fetchMock.mockImplementation(async (url: string) => {
      if (!url.startsWith('/api/v1/tickets')) return base(url)
      return new URL(url, 'http://test').searchParams.get('page') === '2'
        ? json(500, { error: { code: 'INTERNAL_ERROR', message: '다음 쪽 조회 실패' } })
        : json(200, { ...page([ticket(1, 10, 'RDY', 'P2')]), totalPages: 2 })
    })
    expect(await api.listBoard(admin)).toMatchObject({ ok: false, error: { code: 'INTERNAL_ERROR' } })
  })

  it('RF-04·TO-01·TK-05 를 합쳐 부재 사유·ITSM 연결·업무량·긴급도 분포를 만든다', async () => {
    const api = await load()
    server()
    const r = await api.listBoard(admin)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    const net = r.data['네트워크팀']
    // 비활성(퇴사자)은 뺀다
    expect(net.map((c) => c.name)).toEqual(['성민경', '정서현', '황진혁'])
    expect(net[0]).toMatchObject({ avail: true, jira: true, rdy: 1, wip: 2, pri: { P1: 1, P2: 2, P3: 0, P4: 0 } })
    expect(net[1]).toMatchObject({ avail: false, leave: '오후 반차', rdy: 0, wip: 0 })
    expect(net[2]).toMatchObject({ jira: false })
    expect(r.data['서비스데스크'][0]).toMatchObject({ name: '박서연', rdy: 0, wip: 1, pri: { P4: 1 } })
    // 담당자가 없는 접수는 누구의 업무량에도 넣지 않는다
    expect(net.reduce((n, c) => n + c.rdy + c.wip, 0) + r.data['서비스데스크'][0].wip).toBe(4)
  })

  it('요청은 그룹별 구성원 1번씩, 연차 1번, 접수 1번만 보낸다 (그룹마다 반복하지 않는다)', async () => {
    const api = await load()
    server()
    await api.listBoard(admin)
    const u = urls()
    expect(u.filter((x) => x.includes('/members'))).toHaveLength(2)
    expect(u.filter((x) => x.startsWith('/api/v1/time-off'))).toHaveLength(1)
    expect(u.filter((x) => x.startsWith('/api/v1/tickets'))).toHaveLength(1)
    expect(u.find((x) => x.startsWith('/api/v1/tickets'))).toContain('workStatus=RDY')
    await api.listBoard(admin) // 잠시 동안은 구성원을 다시 부르지 않는다
    expect(urls().filter((x) => x.includes('/members'))).toHaveLength(2)
  })

  it('한 그룹의 후보만 달라고 할 수 있다', async () => {
    const api = await load()
    server()
    const r = await api.listCandidates(admin, '서비스데스크')
    expect(r.ok && r.data.map((c) => c.name)).toEqual(['박서연'])
  })

  it('연차 조회가 안 되면 사유 없이 "연차"로 보이고, 접수 조회가 안 되도 구성원은 나온다', async () => {
    const api = await load()
    server({ timeOff: json(403, { error: { code: 'FORBIDDEN', message: 'x', details: null, traceId: 't' } }) })
    const r = await api.listBoard(admin, ['네트워크팀'])
    expect(r.ok && r.data['네트워크팀'][1]).toMatchObject({ avail: false, leave: '연차' })
  })

  it('구성원 조회가 실패하면 서버 오류를 그대로 돌려준다', async () => {
    const api = await load()
    fetchMock.mockImplementation(async (u: string) => (u.startsWith('/api/v1/support-groups/') ? json(500, { error: { code: 'INTERNAL_ERROR', message: '일시적인 오류', details: null, traceId: 't' } }) : json(200, { items: [{ id: 1, name: '서비스데스크' }] })))
    expect(await api.listBoard(admin)).toMatchObject({ ok: false, error: { code: 'INTERNAL_ERROR' } })
  })

  it('담당자 목록(필터용)은 그룹 구성원에서 만든다', async () => {
    const api = await load()
    server()
    const r = await api.listStaff(admin)
    expect(r.ok && r.data.map((s) => [s.name, s.group])).toEqual([['박서연', '서비스데스크'], ['성민경', '네트워크팀'], ['정서현', '네트워크팀'], ['황진혁', '네트워크팀']])
  })
})
