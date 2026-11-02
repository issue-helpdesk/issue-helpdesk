/**
 * 관리자 계정 관리 API 어댑터. (docs/api/01.인증_사용자.md 3장, 05.기준정보_운영.md RF-05)
 *   GET   /users                        US-01 사용자 목록
 *   POST  /users                        US-02 계정 생성 (임시 비밀번호는 이 응답에서만 볼 수 있다)
 *   PATCH /users/{id}                   US-04 정보·상태 변경 (역할·상태를 바꿀 때는 사유 필수)
 *   POST  /users/{id}/temporary-password US-05 임시 비밀번호 재발급
 *   GET   /departments                  RF-05 부서 목록
 * 사용자 관리는 인증 API 와 같은 묶음이라 `VITE_USE_MOCK_AUTH` 를 따른다. 모의 모드에서는 mock/users.ts 가 로그인용 가상 계정을 읽고 바꾼다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK_AUTH } from '../core/config'
import type { Page } from './inquiries'
import { mockCreateUser, mockDepartments, mockIssueTempPassword, mockListUsers, mockUpdateUser, historyLog, pushHistory } from './mock/users'
import { ok, type ApiResult, type User } from './types'
import type { AccountHistoryItem, Department, UserCreateRequest, UserCreateResult, UserListQuery, UserSummary, UserUpdateRequest } from './userTypes'

const toQueryString = (q: UserListQuery) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x))
    else p.set(k, String(v))
  }
  return p.toString()
}

export async function listUsers(actor: User, q: UserListQuery): Promise<ApiResult<Page<UserSummary>>> {
  if (USE_MOCK_AUTH) {
    await sleep(250)
    return mockListUsers(actor, q)
  }
  return request<Page<UserSummary>>(`/users?${toQueryString(q)}`)
}

export async function createUser(actor: User, req: UserCreateRequest): Promise<ApiResult<UserCreateResult>> {
  if (USE_MOCK_AUTH) {
    await sleep(350)
    return mockCreateUser(actor, req)
  }
  return request<UserCreateResult>('/users', { method: 'POST', body: JSON.stringify(req) })
}

export async function updateUser(actor: User, id: number, req: UserUpdateRequest): Promise<ApiResult<UserSummary>> {
  if (USE_MOCK_AUTH) {
    await sleep(350)
    return mockUpdateUser(actor, id, req)
  }
  return request<UserSummary>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(req) })
}

export async function issueTempPassword(actor: User, id: number, reason?: string): Promise<ApiResult<{ temporaryPassword: string }>> {
  if (USE_MOCK_AUTH) {
    await sleep(350)
    return mockIssueTempPassword(actor, id)
  }
  return request<{ temporaryPassword: string }>(`/users/${id}/temporary-password`, { method: 'POST', body: JSON.stringify(reason ? { reason } : {}) })
}

/**
 * 부서 목록 (RF-05). 서버에 아직 없으면 실패로 돌려주므로, 화면은 목록에서 본 부서로 대신한다.
 * 이름순이다.
 */
export async function listDepartments(): Promise<ApiResult<Department[]>> {
  if (USE_MOCK_AUTH) return ok(mockDepartments())
  const r = await request<{ items: Department[] }>('/departments')
  return r.ok ? ok(r.data.items) : r
}

/** 이 화면에서 처리한 일의 기록. 서버에 이력 조회 API 가 없어서 새로고침하면 비워진다. */
export const accountHistory = (): AccountHistoryItem[] => historyLog()
export const recordAccountHistory = pushHistory
