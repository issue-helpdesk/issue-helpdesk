/**
 * 관리자 통계: 서버 운영 집계(OP-01 GET /dashboard/overview) 연결과 상태별 건수 툴팁·팀원 카드. 가짜 fetch 로 요청과 값 변환을 확인한다.
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { bucketLabel } from '../src/api/adminStats'
import { MemberCards } from '../src/views/admin/MemberCards'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

const overview = {
  period: { from: '2026-10-06', to: '2026-11-04', interval: 'WEEK' },
  totals: { ticketCount: 60 },
  byUrgency: [
    { urgency: 'P1', ticketCount: 3 },
    { urgency: 'P2', ticketCount: 10 },
    { urgency: 'P3', ticketCount: 30 },
    { urgency: 'P4', ticketCount: 12 },
  ],
  byGroup: [
    { groupId: 5, name: '네트워크팀', rdy: 2, wip: 5, fin: 3, cls: 40 },
    { groupId: 6, name: '서비스데스크', rdy: 1, wip: 1, fin: 0, cls: 4 },
  ],
  byMember: [
    { userId: 9, name: '조민재', groupId: 5, rdy: 1, wip: 2, fin: 1, cls: 10 },
    { userId: 8, name: '성민경', groupId: 5, rdy: 1, wip: 3, fin: 2, cls: 30 },
    { userId: 3, name: '김수아', groupId: 6, rdy: 1, wip: 1, fin: 0, cls: 4 },
  ],
  trend: [
    { date: '2026-10-06', ticketCount: 20, closedCount: 15 },
    { date: '2026-10-13', ticketCount: 25, closedCount: 20 },
    { date: '2026-10-20', ticketCount: 15, closedCount: 9 },
  ],
}

describe('운영 집계 읽기 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('기간·단위를 쿼리로 보내고, 팀·구성원·긴급도·추이를 화면 값으로 바꾼다', async () => {
    vi.resetModules()
    const api = await import('../src/api/adminStats')
    fetchMock.mockResolvedValueOnce(json(overview))
    const r = await api.getAdminOverview('m', 'w')
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/dashboard\/overview\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&interval=WEEK$/)
    if (!r.ok) throw new Error('읽기 실패')
    const o = r.data
    expect(o.total).toBe(60)
    expect(o.states).toEqual({ RDY: 3, WIP: 6, FIN: 3, CLS: 44 })
    expect(o.none).toBe(4) // 접수 60 − 팀이 정해진 상태별 합 56
    expect(o.urgency).toEqual({ P1: 3, P2: 10, P3: 30, P4: 12 })
    expect(o.groups.map((g) => [g.name, g.members.map((m) => m.name)])).toEqual([
      ['네트워크팀', ['조민재', '성민경']],
      ['서비스데스크', ['김수아']],
    ])
    expect(o.trend?.recv).toEqual([20, 25, 15])
    expect(o.trend?.done).toEqual([15, 20, 9])
    expect(o.trend?.labels[0]).toBe('10.6~10.12')
  })

  it('오늘은 추이를 그리지 않고, 하루만 요청한다', async () => {
    vi.resetModules()
    const api = await import('../src/api/adminStats')
    fetchMock.mockResolvedValueOnce(json({ ...overview, period: { from: '2026-11-04', to: '2026-11-04', interval: 'DAY' } }))
    const r = await api.getAdminOverview('d', 'd')
    const url = String(fetchMock.mock.calls[0][0])
    expect(new URL(`http://x${url.replace('/api/v1', '')}`).searchParams.get('from')).toBe(new URL(`http://x${url.replace('/api/v1', '')}`).searchParams.get('to'))
    expect(r.ok && r.data.trend).toBeNull()
  })

  it('막대 이름: 일별은 월.일, 주별은 시작~끝(기간 끝에서 자름), 월별은 연.월', () => {
    expect(bucketLabel('2026-11-04', 'DAY', '2026-11-04')).toBe('11.4')
    expect(bucketLabel('2026-10-29', 'WEEK', '2026-11-04')).toBe('10.29~11.4')
    expect(bucketLabel('2026-11-01', 'WEEK', '2026-11-04')).toBe('11.1~11.4')
    expect(bucketLabel('2026-10-01', 'MONTH', '2026-11-04')).toBe('26.10')
  })
})

describe('팀원 카드', () => {
  const members = [
    { id: 1, name: '조민재', v: { RDY: 1, WIP: 2, FIN: 1, CLS: 10 } },
    { id: 2, name: '성민경', v: { RDY: 0, WIP: 0, FIN: 0, CLS: 0 } },
  ]

  it('카드에 올리면 상태별 건수 카드가 뜨고, 누르면 오른쪽 칸에 상태별 건수·완료율·티켓 목록이 열린다', async () => {
    let open: string | null = null
    const onList = vi.fn()
    const { rerender } = render(<MemberCards members={members} open={open} onOpen={(n) => (open = n)} onList={onList} />)
    fireEvent.mouseMove(screen.getByRole('button', { name: /^조민재 처리 상태 14건/ }), { clientX: 100, clientY: 100 })
    const tip = document.querySelector('.stip') as HTMLElement
    expect(tip).toHaveTextContent('조민재')
    expect(tip).toHaveTextContent('전체 14건')
    expect(within(tip).getByText('해결 완료').nextSibling).toHaveTextContent('10건')
    await userEvent.click(screen.getByRole('button', { name: /^조민재 처리 상태/ }))
    expect(open).toBe('조민재')
    rerender(<MemberCards members={members} open="조민재" onOpen={() => {}} onList={onList} />)
    expect(screen.getByText('전체 14건 · 완료 71%')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /티켓 목록/ }))
    expect(onList).toHaveBeenCalledWith('조민재')
    // 건수가 없는 팀원은 완료율 대신 - 를 보인다
    expect(screen.getByRole('button', { name: /^성민경 처리 상태 0건/ })).toBeInTheDocument()
  })
})
