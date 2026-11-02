/**
 * 담당 그룹·담당자 목록 (관리자의 전체 문의 필터, 재배정). (docs/api/05 RF-03·04, docs/api/01 US-01)
 *   GET /support-groups          RF-03 담당 그룹 목록
 *   GET /users?serviceRole=AGENT US-01 담당자(서비스 권한 AGENT) 목록 — 관리자만
 * 접수 영역(VITE_USE_MOCK_TICKET)을 따른다. 모의 모드에서는 mock/staffTickets.ts 의 그룹·구성원을 쓴다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_TICKET } from '../core/config'
import type { Urgency } from './chatTypes'
import { notReady } from './inquiryServer'
import { GROUP_ID, GROUP_STAFF, workloadOf } from './mock/staffTickets'
import { ok, type ApiResult, type User } from './types'
import { listUsers } from './users'

export interface SupportGroupRef {
  id: number
  name: string
}
export interface StaffRef {
  id: number
  name: string
  /** 소속 담당 그룹(팀) 이름 */
  group: string
}

export async function listSupportGroups(): Promise<ApiResult<SupportGroupRef[]>> {
  if (USE_MOCK_TICKET) return ok(Object.keys(GROUP_STAFF).map((name) => ({ id: GROUP_ID[name], name })))
  const r = await request<{ items: SupportGroupRef[] }>('/support-groups')
  return r.ok ? ok(r.data.items.map((g) => ({ id: g.id, name: g.name }))) : r
}

export async function listStaff(actor: User): Promise<ApiResult<StaffRef[]>> {
  if (USE_MOCK_TICKET) return ok(Object.entries(GROUP_STAFF).flatMap(([group, list]) => list.map((m) => ({ id: m.id, name: m.name, group }))))
  const r = await listUsers(actor, { serviceRole: ['AGENT'], size: 100, sort: 'name,asc' })
  return r.ok ? ok(r.data.items.map((u) => ({ id: u.id, name: u.name, group: u.department?.name ?? '' }))) : r
}

/** 재배정 후보 한 명: 오늘 상태, 업무량(처리 대기·처리 중), 긴급도 분포, Jira 계정 연결 */
export interface Candidate {
  id: number
  name: string
  avail: boolean
  /** 부재 사유 (연차·반차) */
  leave?: string
  jira: boolean
  rdy: number
  wip: number
  pri: Record<Urgency, number>
}

/**
 * 담당 그룹 구성원과 업무량 (재배정 후보). 서버는 RF-04(구성원·배정 가능 여부), TO-01~04(부재), TK-05(업무량)를 합쳐야 하는데
 * 재배정은 Jira 실행기가 배포되기 전에는 요청하지 않으므로 서버 모드에서는 안내만 한다.
 */
export async function listCandidates(groupName: string): Promise<ApiResult<Candidate[]>> {
  if (!USE_MOCK_TICKET) return notReady('담당자 재배정')
  return ok((GROUP_STAFF[groupName] ?? []).map((m) => ({ id: m.id, name: m.name, avail: m.avail, leave: m.leave, jira: m.jira, ...workloadOf(m.id) })))
}
