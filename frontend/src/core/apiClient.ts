/**
 * API 호출의 단일 진입점.
 *
 * - 서버 계약(docs/07 5장): 성공은 본문 그대로(204 는 본문 없음), 실패는 `{ error: { code, message, details, traceId } }`.
 *   화면은 `{ ok, data | error }` 한 가지 모양만 다루도록 여기서 바꿔 준다.
 * - Access Token 은 `Authorization: Bearer <토큰>` 헤더로, Refresh Token 은 httpOnly 쿠키로 보낸다. (`credentials: 'include'`)
 * - 401 `TOKEN_EXPIRED` 면 토큰 재발급(AU-05)을 한 번 하고 같은 요청을 다시 보낸다.
 *   동시에 여러 요청이 만료돼도 재발급은 한 번만 하고, 재발급이 실패하면 로그인이 끊긴 것으로 알린다. (docs/07 2.8)
 * - 네트워크 오류·형식 오류도 같은 모양의 실패 응답으로 바꿔서, 화면이 한 가지 방식으로만 처리하게 한다.
 */
import { fail, ok, type ApiResult, type ErrorDetail } from '../api/types'
import { BAD_RESPONSE_TEXT, NETWORK_READ, NETWORK_WRITE, displayMessage } from '../api/errorText'
import { API_BASE_URL } from './config'
import { tokenStore } from './tokenStore'

/** 토큰 재발급을 하는 함수. 성공하면 새 토큰을 저장하고 true 를 돌려준다. (api/auth.ts 가 등록한다) */
let refresher: (() => Promise<boolean>) | null = null
/** 로그인이 끊겼을 때(재발급 실패·무효 토큰) 부르는 함수. (core/session.tsx 가 등록한다) */
let authLost: (() => void) | null = null

export const setTokenRefresher = (fn: (() => Promise<boolean>) | null) => {
  refresher = fn
}
export const setAuthLostHandler = (fn: (() => void) | null) => {
  authLost = fn
}

/** 진행 중인 재발급. 동시에 만료된 요청들이 함께 기다린다. */
let inflight: Promise<boolean> | null = null
function refreshOnce(): Promise<boolean> {
  if (!refresher) return Promise.resolve(false)
  inflight ??= refresher().finally(() => {
    inflight = null
  })
  return inflight
}

/** 요청을 한 번 보내고 결과를 `{ ok, data | error }` 로 바꾼다. (재시도 없음) */
async function send<T>(path: string, init: RequestInit): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers)

  // 본문이 있으면 JSON 으로 보낸다
  // (파일 업로드(FormData)는 브라우저가 경계값이 든 Content-Type 을 정해야 하므로 건드리지 않는다)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  try {
    const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers, credentials: 'include' })
    // 204 No Content (예: 비밀번호 변경, 로그아웃)는 본문이 없으므로 성공으로 본다
    if (res.status === 204) return ok(null as T)

    const body: unknown = await res.json().catch(() => null)
    if (res.ok) {
      if (body === null) return fail('BAD_RESPONSE', BAD_RESPONSE_TEXT)
      return ok(body as T)
    }

    // 약속한 실패 형식이면 코드·문구·상세를 그대로 전달한다
    const e = (body as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error
    if (e && typeof e.code === 'string') {
      const details = Array.isArray(e.details) ? (e.details as ErrorDetail[]) : undefined
      // 화면 문구는 코드별 사전(api/errorText.ts)에서 정한다. 없는 코드는 서버 문구를 쓰되 용어만 맞춘다
      return fail(e.code, displayMessage(e.code, typeof e.message === 'string' ? e.message : '', details), { details })
    }
    return fail('BAD_RESPONSE', BAD_RESPONSE_TEXT)
  } catch {
    // 서버에 닿지 못한 경우 (오프라인, 서버 중지 등)
    // 읽기는 다시 불러오면 되고, 변경 요청은 서버가 이미 처리했을 수 있어서 실패로 단정하지 않고 처리 상태를 확인하게 한다
    const read = !init.method || init.method.toUpperCase() === 'GET'
    return fail('NETWORK_ERROR', read ? NETWORK_READ : NETWORK_WRITE)
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  const r = await send<T>(path, init)
  // 로그인·재발급·로그아웃 자체의 401 은 아래 처리 대상이 아니다
  if (r.ok || path.startsWith('/auth/')) return r

  if (r.error.code === 'TOKEN_EXPIRED') {
    // 만료된 Access Token: 한 번 재발급한 뒤 같은 요청을 다시 보낸다
    if (await refreshOnce()) return send<T>(path, init)
    authLost?.()
  } else if (r.error.code === 'UNAUTHORIZED') {
    // 폐기됐거나 잘못된 토큰: 다시 로그인해야 한다
    authLost?.()
  }
  return r
}

/**
 * 파일(그림 등)을 받는다. 토큰을 헤더로 보내야 해서 `<img src>` 에 주소를 바로 넣을 수 없고, 이렇게 받아 blob 으로 보여 준다.
 * 만료된 토큰은 한 번 재발급해 다시 시도하고, 못 받으면 null 이다 (화면이 대체 표시를 쓴다).
 */
export async function requestBlob(path: string): Promise<Blob | null> {
  const go = () => {
    const headers = new Headers()
    const token = tokenStore.get()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(`${API_BASE_URL}${path}`, { headers, credentials: 'include' })
  }
  try {
    let res = await go()
    if (res.status === 401 && (await refreshOnce())) res = await go()
    return res.ok ? await res.blob() : null
  } catch {
    return null
  }
}

/** 가짜 응답(mock)에서 서버 지연을 흉내 낼 때 쓴다. */
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
