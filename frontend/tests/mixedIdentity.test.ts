/**
 * 로그인은 서버, 접수는 모의로 섞어 쓸 때: 서버가 정한 사용자 번호가 모의 담당자의 번호와 달라도 내 접수가 보여야 한다.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { GROUP_STAFF, bindMockUser, clearBoundUsers } from '../src/api/mock/staffTickets'
import { listBoard } from '../src/api/reference'
import { getTeamStatus, listTickets } from '../src/api/tickets'
import type { User } from '../src/api/types'

/** 서버가 정한 번호(4)를 가진 성민경. 모의의 성민경 번호는 2이다 */
const server = { id: 4, employeeNo: 'EMP-1004', name: '성민경', serviceRole: 'AGENT', departmentName: '네트워크팀' } as User

afterEach(() => clearBoundUsers())

describe('서버 로그인 + 모의 접수', () => {
  it('번호를 맞추기 전에는 내 접수가 비어 보인다', async () => {
    const r = await listTickets(server, { view: 'ASSIGNED', assigneeId: server.id, size: 100 })
    expect(r.ok && r.data.totalCount).toBe(0)
  })

  it('사번이 같은 모의 담당자의 번호를 로그인한 사용자의 번호로 맞추면 내 접수가 보인다', async () => {
    bindMockUser(server.employeeNo, server.id)
    const r = await listTickets(server, { view: 'ASSIGNED', assigneeId: server.id, size: 100 })
    expect(r.ok && r.data.totalCount).toBeGreaterThan(5)
    expect(r.ok && r.data.items.every((t) => t.assignee?.id === 4 && t.assignee.employeeNo === 'EMP-1004')).toBe(true)
  })

  it('구성원·업무량 표와 후보도 같은 번호를 쓴다', async () => {
    bindMockUser(server.employeeNo, server.id)
    const b = await listBoard(server, ['네트워크팀'])
    const me = b.ok ? b.data['네트워크팀'].find((c) => c.name === '성민경') : undefined
    expect(me?.id).toBe(4)
    expect((me?.rdy ?? 0) + (me?.wip ?? 0)).toBeGreaterThan(5)
    expect(GROUP_STAFF['네트워크팀'][0].id).toBe(4)
  })

  it('팀 현황은 이름·그룹으로 세어 번호와 상관없이 동작한다', async () => {
    const r = await getTeamStatus(server)
    expect(r.ok && r.data.groupName).toBe('네트워크팀')
  })

  it('지우면 모의의 원래 번호로 돌아온다', () => {
    bindMockUser(server.employeeNo, server.id)
    clearBoundUsers()
    expect(GROUP_STAFF['네트워크팀'][0].id).toBe(2)
  })
})
