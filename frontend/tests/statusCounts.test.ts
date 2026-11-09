/**
 * 목록 응답의 상태별 건수 (R-46): 상태 조건만 빼고 나머지 조건을 목록과 같게 센다. 모의가 서버와 같은 모양으로 주는지 확인한다.
 */
import { describe, expect, it } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { listUsers } from '../src/api/users'
import { listTickets } from '../src/api/tickets'
import type { User } from '../src/api/types'

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')! as unknown as User

describe('상태별 건수 (모의)', () => {
  it('접수 목록: 상태를 걸어도 statusCounts 는 상태 조건을 빼고 센다', async () => {
    const all = await listTickets(admin(), { view: 'ALL', size: 1 })
    const wip = await listTickets(admin(), { view: 'ALL', size: 1, workStatus: ['WIP'] })
    expect(all.ok && wip.ok).toBe(true)
    if (!all.ok || !wip.ok) return
    expect(wip.data.statusCounts).toEqual(all.data.statusCounts)
    expect(wip.data.totalCount).toBe(all.data.statusCounts?.WIP)
    expect(Object.keys(all.data.statusCounts ?? {}).sort()).toEqual(['CLS', 'FIN', 'RDY', 'WIP'])
  })

  it('접수 목록: 긴급도 같은 다른 조건은 건수에도 적용된다', async () => {
    const p1 = await listTickets(admin(), { view: 'ALL', size: 1, urgency: ['P1'] })
    const all = await listTickets(admin(), { view: 'ALL', size: 1 })
    expect(p1.ok && all.ok).toBe(true)
    if (!p1.ok || !all.ok) return
    const sum = (c?: Record<string, number>) => Object.values(c ?? {}).reduce((a, b) => a + b, 0)
    expect(sum(p1.data.statusCounts)).toBeLessThan(sum(all.data.statusCounts))
  })

  it('계정 목록: 상태를 걸어도 statusCounts 는 그대로이고 합이 전체와 맞다', async () => {
    const all = await listUsers(admin(), { size: 1 })
    const locked = await listUsers(admin(), { size: 1, accountStatus: ['LOCKED'] })
    expect(all.ok && locked.ok).toBe(true)
    if (!all.ok || !locked.ok) return
    expect(locked.data.statusCounts).toEqual(all.data.statusCounts)
    const c = all.data.statusCounts!
    expect(c.ACTIVE + c.LOCKED + c.INACTIVE).toBe(all.data.totalCount)
  })
})
