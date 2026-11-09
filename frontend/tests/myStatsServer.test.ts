/**
 * 담당자 통계의 서버 집계 연결 (OP-02 GET /dashboard/me). 가짜 fetch 로 요청과 값 변환을 확인한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const staff = (): User => ({ ...MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!, departmentName: '네트워크팀' })

describe('내 접수·팀 통계 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('기간을 쿼리로 보내고, 내 접수와 내 팀(소속 이름이 같은 그룹)·팀원 건수로 바꾼다', async () => {
    vi.resetModules()
    const api = await import('../src/api/myStats')
    fetchMock.mockResolvedValueOnce(
      json({
        period: { from: '2026-10-06', to: '2026-11-04' },
        me: { rdy: 1, wip: 2, fin: 0, cls: 7 },
        groups: [
          { groupId: 6, name: '서비스데스크', rdy: 0, wip: 1, fin: 0, cls: 3, members: [{ userId: 3, name: '김수아', rdy: 0, wip: 1, fin: 0, cls: 3 }] },
          { groupId: 5, name: '네트워크팀', rdy: 2, wip: 5, fin: 3, cls: 40, members: [{ userId: 8, name: '성민경', rdy: 1, wip: 2, fin: 0, cls: 7 }, { userId: 9, name: '조민재', rdy: 1, wip: 3, fin: 3, cls: 33 }] },
        ],
      }),
    )
    const r = await api.getMyOverview(staff(), 'm')
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/dashboard\/me\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/)
    if (!r.ok) throw new Error('읽기 실패')
    expect(r.data.me).toEqual({ RDY: 1, WIP: 2, FIN: 0, CLS: 7 })
    expect(r.data.group?.name).toBe('네트워크팀')
    expect(r.data.group?.v).toEqual({ RDY: 2, WIP: 5, FIN: 3, CLS: 40 })
    expect(r.data.group?.members.map((m) => [m.name, m.v.CLS])).toEqual([['성민경', 7], ['조민재', 33]])
    expect(r.data.none).toBeUndefined() // 배정 전 건수는 서버 집계에 없다
  })

  it('소속 팀을 못 찾으면 첫 그룹을, 그룹이 없으면 null 을 쓴다', async () => {
    vi.resetModules()
    const api = await import('../src/api/myStats')
    fetchMock.mockResolvedValueOnce(json({ me: {}, groups: [{ groupId: 6, name: '서비스데스크', members: [] }] }))
    const a = await api.getMyOverview({ ...staff(), departmentName: '없는팀' }, 'd')
    expect(a.ok && a.data.group?.name).toBe('서비스데스크')
    fetchMock.mockResolvedValueOnce(json({ me: { wip: 1 }, groups: [] }))
    const b = await api.getMyOverview(staff(), 'y')
    expect(b.ok && [b.data.group, b.data.me.WIP]).toEqual([null, 1])
  })
})
