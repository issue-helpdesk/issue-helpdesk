/**
 * API 호출의 단일 진입점.
 *
 * - 서버 응답 형식 `{ ok, data | error }` 를 그대로 돌려준다.
 * - 네트워크 오류·형식 오류도 같은 모양의 실패 응답으로 바꿔서, 화면이 한 가지 방식으로만 처리하게 한다.
 * - 로그인 토큰이 있으면 `Authorization: Bearer <토큰>` 헤더를 붙인다. (세션 쿠키는 쓰지 않는다)
 */
import { fail, ok, type ApiResult } from '../api/types'
import { API_BASE_URL, SERVICEDESK } from './config'
import { tokenStore } from './tokenStore'

export async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers)

  // 본문이 있으면 JSON 으로 보낸다
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  try {
    const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
    // 204 No Content (예: 비밀번호 변경)는 본문이 없으므로 성공으로 본다
    if (res.status === 204) return ok(null as T)
    const body: unknown = await res.json().catch(() => null)

    // 약속한 형식({ ok: ... })이면 그대로 전달한다
    if (body && typeof body === 'object' && 'ok' in body) return body as ApiResult<T>

    return fail('BAD_RESPONSE', '서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.')
  } catch {
    // 서버에 닿지 못한 경우 (오프라인, 서버 중지 등)
    return fail('NETWORK_ERROR', `서버에 연결하지 못했어요. 잠시 후 다시 시도하거나 IT 헬프데스크 ${SERVICEDESK}로 문의해 주세요.`)
  }
}

/** 가짜 응답(mock)에서 서버 지연을 흉내 낼 때 쓴다. */
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
