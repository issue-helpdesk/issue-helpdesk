/**
 * 인증 API 어댑터.
 *
 * 화면은 이 파일의 `authApi` 만 부른다. 백엔드가 확정되면 경로·필드명은 여기서만 맞추고,
 * 화면 코드는 고치지 않는다. (시스템 설계서 9.1: POST /auth/login, GET /users/me)
 * `VITE_USE_MOCK` 이 true(기본)이면 서버 없이 가짜 계정으로 동작한다.
 */
import { request, sleep } from '../core/apiClient'
import { SERVICEDESK, USE_MOCK } from '../core/config'
import { tokenStore } from '../core/tokenStore'
import {
  addFail,
  clearFails,
  lockAccount,
  lockExpired,
  MAX_FAILS,
  minutesLeft,
  MOCK_ACCOUNTS,
  MOCK_PASSWORD,
  unlockAccount,
} from './mock/accounts'
import { fail, ok, type ApiResult, type LoginData, type LoginRequest, type User } from './types'

/** 가짜 토큰의 접두어. 'mock.HS1001' 처럼 사번을 담아 me() 에서 사용자를 찾는다. */
const MOCK_PREFIX = 'mock.'

/** 사번으로 가짜 계정을 찾는다 (대소문자·앞뒤 공백 무시). */
function findAccount(id: string) {
  return MOCK_ACCOUNTS.find((a) => a.id.toLowerCase() === id.trim().toLowerCase())
}

/** 가짜 로그인. 실제 서버처럼 계정 상태에 따라 실패 사유를 다르게 돌려준다. */
async function mockLogin(req: LoginRequest, skipPassword = false): Promise<ApiResult<LoginData>> {
  await sleep(350) // 서버 응답 지연 흉내

  const acc = findAccount(req.employeeId)

  // 잠김은 10분이 지나면 다음 로그인 시도 때 자동으로 풀린다
  if (acc && acc.status === '잠김' && lockExpired(acc.id)) unlockAccount(acc)

  // 잠긴 동안에는 올바른 비밀번호여도 로그인할 수 없다
  if (acc && acc.status === '잠김') {
    return fail(
      'ACCOUNT_LOCKED',
      `로그인 ${MAX_FAILS}회 실패로 잠긴 계정이에요. 약 ${minutesLeft(acc.id)}분 후 자동으로 해제돼요. 급하면 서비스데스크로 문의해 주세요. (${SERVICEDESK})`,
    )
  }

  if (!acc || (!skipPassword && req.password !== MOCK_PASSWORD)) {
    // 정상 계정이 연속으로 5회 틀리면 잠근다
    if (acc && acc.status === '정상' && addFail(acc.id) >= MAX_FAILS) {
      lockAccount(acc)
      return fail('ACCOUNT_LOCKED', `로그인 ${MAX_FAILS}회 실패로 계정이 잠겼어요. 10분 후 자동으로 해제돼요. 급하면 서비스데스크로 문의해 주세요. (${SERVICEDESK})`)
    }
    return fail('INVALID_CREDENTIALS', '사번 또는 비밀번호를 확인해 주세요.')
  }

  if (acc.status === '이용 제한') {
    return fail('ACCOUNT_RESTRICTED', `이용이 제한된 계정이에요. 서비스데스크로 문의해 주세요. (${SERVICEDESK})`)
  }

  clearFails(acc.id) // 로그인에 성공하면 연속 실패 기록을 지운다
  return ok({ accessToken: MOCK_PREFIX + acc.id, user: acc })
}

/** 가짜 사용자 조회: 저장된 가짜 토큰에서 사번을 읽어 계정을 돌려준다. */
async function mockMe(): Promise<ApiResult<User>> {
  const token = tokenStore.get()
  const acc = token?.startsWith(MOCK_PREFIX) ? findAccount(token.slice(MOCK_PREFIX.length)) : undefined
  return acc ? ok(acc) : fail('UNAUTHORIZED', '로그인이 필요해요.')
}

export const authApi = {
  /** 사번·비밀번호 로그인 */
  login(req: LoginRequest): Promise<ApiResult<LoginData>> {
    if (USE_MOCK) return mockLogin(req)
    return request<LoginData>('/auth/login', { method: 'POST', body: JSON.stringify(req) })
  },

  /** SSO 로그인. 실제 SSO 연동 방식이 미확정이라 시연(mock)에서만 동작한다. */
  loginSso(): Promise<ApiResult<LoginData>> {
    if (USE_MOCK) return mockLogin({ employeeId: 'HS1001', password: MOCK_PASSWORD }, true)
    return Promise.resolve(fail('SSO_NOT_READY', 'SSO 로그인은 준비 중이에요. 사번으로 로그인해 주세요.'))
  },

  /** 시연 전용: 비밀번호 없이 계정을 골라 로그인 */
  mockQuickLogin(id: string): Promise<ApiResult<LoginData>> {
    return mockLogin({ employeeId: id, password: MOCK_PASSWORD }, true)
  },

  /** 현재 로그인한 사용자 조회 (새로고침 후 로그인 유지 확인에 사용) */
  me(): Promise<ApiResult<User>> {
    if (USE_MOCK) return mockMe()
    return request<User>('/users/me')
  },
}
