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
  lockedUntilIso,
  lockExpired,
  MAX_FAILS,
  minutesLeft,
  MOCK_ACCOUNTS,
  MOCK_PASSWORD,
  passwordOf,
  sessionUser,
  setPassword,
  unlockAccount,
} from './mock/accounts'
import { checkPassword } from '../core/password'
import { fail, ok, type ApiResult, type LoginData, type LoginRequest, type PasswordChangeRequest, type User } from './types'

/** 가짜 토큰의 접두어. 'mock.EMP-1001' 처럼 사번을 담아 me() 에서 사용자를 찾는다. */
const MOCK_PREFIX = 'mock.'

/** 사번으로 가짜 계정을 찾는다 (대소문자·앞뒤 공백 무시). */
function findAccount(id: string) {
  return MOCK_ACCOUNTS.find((a) => a.employeeNo.toLowerCase() === id.trim().toLowerCase())
}

/** 가짜 로그인. 실제 서버처럼 계정 상태에 따라 실패 사유를 다르게 돌려준다. */
async function mockLogin(req: LoginRequest, skipPassword = false): Promise<ApiResult<LoginData>> {
  await sleep(350) // 서버 응답 지연 흉내

  const acc = findAccount(req.employeeNo)

  // 잠김은 10분이 지나면 다음 로그인 시도 때 자동으로 풀린다
  if (acc && acc.accountStatus === 'LOCKED' && lockExpired(acc.employeeNo)) unlockAccount(acc)

  // 잠긴 동안에는 올바른 비밀번호여도 로그인할 수 없다
  if (acc && acc.accountStatus === 'LOCKED') {
    return fail(
      'ACCOUNT_LOCKED',
      `로그인 ${MAX_FAILS}회 실패로 잠긴 계정이에요. 약 ${minutesLeft(acc.employeeNo)}분 후 자동으로 해제돼요. 급하면 서비스데스크로 문의해 주세요. (${SERVICEDESK})`,
      { lockedUntil: lockedUntilIso(acc.employeeNo) },
    )
  }

  if (!acc || (!skipPassword && req.password !== passwordOf(acc.employeeNo))) {
    // 정상 계정이 연속으로 5회 틀리면 잠근다
    if (acc && acc.accountStatus === 'ACTIVE' && addFail(acc.employeeNo) >= MAX_FAILS) {
      lockAccount(acc)
      return fail('ACCOUNT_LOCKED', `로그인 ${MAX_FAILS}회 실패로 계정이 잠겼어요. 10분 후 자동으로 해제돼요. 급하면 서비스데스크로 문의해 주세요. (${SERVICEDESK})`, {
        lockedUntil: lockedUntilIso(acc.employeeNo),
      })
    }
    return fail('INVALID_CREDENTIALS', '사번 또는 비밀번호를 확인해 주세요.')
  }

  if (acc.accountStatus === 'INACTIVE') {
    return fail('ACCOUNT_INACTIVE', `이용이 제한된 계정이에요. 서비스데스크로 문의해 주세요. (${SERVICEDESK})`)
  }

  clearFails(acc.employeeNo) // 로그인에 성공하면 연속 실패 기록을 지운다
  return ok({ accessToken: MOCK_PREFIX + acc.employeeNo, user: sessionUser(acc) })
}

/** 가짜 사용자 조회: 저장된 가짜 토큰에서 사번을 읽어 계정을 돌려준다. */
async function mockMe(): Promise<ApiResult<User>> {
  const token = tokenStore.get()
  const acc = token?.startsWith(MOCK_PREFIX) ? findAccount(token.slice(MOCK_PREFIX.length)) : undefined
  return acc ? ok(sessionUser(acc)) : fail('UNAUTHORIZED', '로그인이 필요해요.')
}

/** 가짜 비밀번호 변경. 검사 순서는 현재 비밀번호 → 비밀번호 규칙이다. (AU-04) */
async function mockChangePassword(req: PasswordChangeRequest): Promise<ApiResult<null>> {
  await sleep(350)
  const token = tokenStore.get()
  const acc = token?.startsWith(MOCK_PREFIX) ? findAccount(token.slice(MOCK_PREFIX.length)) : undefined
  if (!acc) return fail('UNAUTHORIZED', '로그인이 필요해요.')
  if (req.currentPassword !== passwordOf(acc.employeeNo)) return fail('AUTH_CURRENT_PASSWORD_MISMATCH', '현재 비밀번호가 맞지 않아요.')
  const details = checkPassword(req.newPassword, req.currentPassword, acc.employeeNo)
  if (details.length) return fail('AUTH_PASSWORD_POLICY_VIOLATION', details[0].message, { details })
  setPassword(acc.employeeNo, req.newPassword)
  return ok(null)
}

export const authApi = {
  /** 사번·비밀번호 로그인 */
  login(req: LoginRequest): Promise<ApiResult<LoginData>> {
    if (USE_MOCK) return mockLogin(req)
    return request<LoginData>('/auth/login', { method: 'POST', body: JSON.stringify(req) })
  },

  /** SSO 로그인. 실제 SSO 연동 방식이 미확정이라 시연(mock)에서만 동작한다. */
  loginSso(): Promise<ApiResult<LoginData>> {
    if (USE_MOCK) return mockLogin({ employeeNo: 'EMP-1001', password: MOCK_PASSWORD }, true)
    return Promise.resolve(fail('SSO_NOT_READY', 'SSO 로그인은 준비 중이에요. 사번으로 로그인해 주세요.'))
  },

  /** 시연 전용: 비밀번호 없이 계정을 골라 로그인 */
  mockQuickLogin(id: string): Promise<ApiResult<LoginData>> {
    return mockLogin({ employeeNo: id, password: MOCK_PASSWORD }, true)
  },

  /** 현재 로그인한 사용자 조회 (새로고침 후 로그인 유지 확인에 사용) */
  me(): Promise<ApiResult<User>> {
    if (USE_MOCK) return mockMe()
    return request<User>('/users/me')
  },

  /**
   * 비밀번호 변경 (임시 비밀번호 상태에서도 쓴다). 성공하면 서버가 그 사용자의 모든 로그인을 끊으므로
   * 화면은 로그인 화면으로 돌려보내 다시 로그인하게 한다.
   */
  changePassword(req: PasswordChangeRequest): Promise<ApiResult<null>> {
    if (USE_MOCK) return mockChangePassword(req)
    return request<null>('/users/me/password', { method: 'PUT', body: JSON.stringify(req) })
  },
}
