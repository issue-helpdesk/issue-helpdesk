/**
 * 가짜 계정이 서버 시드(dataset/data/employees.csv)의 실제 직원과 같은지 확인한다.
 * 모의와 서버에서 같은 사번이 같은 사람(이름·부서·역할)으로 보이게 하려는 것이다. 시연용 상태(이용 제한·잠김·임시 비밀번호)만 모의에서 따로 둔다.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { TEAM_MEMBERS } from '../src/api/mock/staffTickets'

const ROLE = { '일반 임직원': 'EMPLOYEE', 'IT 운영 담당자': 'AGENT', 관리자: 'ADMIN' } as const

/** employees.csv: emp_id,name,division,team,job_title,itssue_role,... (값 안에 쉼표나 따옴표는 없다) */
function seed() {
  const csv = readFileSync(resolve(__dirname, '../../dataset/data/employees.csv'), 'utf-8')
  const [, ...rows] = csv.replace(/^﻿/, '').split(/\r?\n/).filter(Boolean)
  return new Map(rows.map((r: string) => r.split(',')).map((c: string[]) => [c[0], { name: c[1], team: c[3], role: ROLE[c[5] as keyof typeof ROLE] }]))
}

describe('가짜 계정과 서버 시드', () => {
  it('모든 가짜 계정이 서버 시드의 같은 사번·이름·부서·역할이다', () => {
    const emp = seed()
    expect(emp.size).toBeGreaterThan(300)
    for (const a of MOCK_ACCOUNTS) {
      const e = emp.get(a.employeeNo)
      expect(e, `${a.employeeNo} 가 서버 시드에 없어요`).toBeDefined()
      expect({ name: a.name, team: a.departmentName, role: a.serviceRole }, a.employeeNo).toEqual({ name: e!.name, team: e!.team, role: e!.role })
    }
  })

  it('담당 그룹의 모의 팀원도 서버 시드의 같은 팀 직원이다', () => {
    const byName = new Map([...seed()].map(([id, v]) => [v.name, { id, ...v }]))
    for (const [team, members] of Object.entries(TEAM_MEMBERS)) {
      for (const { name } of members) expect(byName.get(name)?.team, `${name} 은 서버 시드의 ${team} 직원이어야 해요`).toBe(team)
    }
  })
})
