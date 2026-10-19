/**
 * 로그인 상태(세션) 관리.
 *
 * `AuthProvider` 를 앱 루트에 한 번 두고, 화면에서는 `useAuth()` 로 현재 사용자와
 * 로그인·로그아웃 함수를 꺼내 쓴다. 토큰 보관은 `tokenStore` 가 맡는다.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi } from '../api/auth'
import type { ApiResult, LoginData, LoginRequest, User } from '../api/types'
import { tokenStore } from './tokenStore'

interface AuthState {
  /** 로그인한 사용자. 로그인 전이면 null */
  user: User | null
  /** 새로고침 직후 저장된 토큰으로 사용자를 확인하는 중인지 */
  loading: boolean
  /** 사번·비밀번호 로그인 */
  login: (req: LoginRequest) => Promise<ApiResult<LoginData>>
  /** SSO 로그인 (연동 방식 미확정이라 지금은 시연용) */
  loginSso: () => Promise<ApiResult<LoginData>>
  /** 시연 전용: 계정을 골라 바로 로그인 */
  mockQuickLogin: (id: string) => Promise<ApiResult<LoginData>>
  /** 로그아웃: 토큰과 사용자 정보를 지운다 */
  logout: () => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // 저장된 토큰이 있으면 사용자 확인이 끝날 때까지 loading 상태로 시작한다
  const [loading, setLoading] = useState<boolean>(() => !!tokenStore.get())

  // 새로고침 후 저장된 토큰이 아직 유효한지 서버에 확인한다
  useEffect(() => {
    if (!tokenStore.get()) return
    let alive = true // 화면이 사라진 뒤에는 상태를 바꾸지 않기 위한 표시
    authApi.me().then((r) => {
      if (!alive) return
      if (r.ok) setUser(r.data)
      else tokenStore.clear() // 만료·무효 토큰은 버린다
      setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [])

  /** 로그인 응답이 성공이면 토큰과 사용자를 저장하고, 결과는 화면에 그대로 돌려준다. */
  const accept = useCallback((r: ApiResult<LoginData>) => {
    if (r.ok) {
      tokenStore.set(r.data.accessToken)
      setUser(r.data.user)
    }
    return r
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login: async (req) => accept(await authApi.login(req)),
      loginSso: async () => accept(await authApi.loginSso()),
      mockQuickLogin: async (id) => accept(await authApi.mockQuickLogin(id)),
      logout: () => {
        tokenStore.clear()
        setUser(null)
      },
    }),
    [user, loading, accept],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// 훅과 컴포넌트를 한 파일에 두는 것을 허용한다 (react-refresh 규칙 예외)
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth 는 AuthProvider 안에서만 쓸 수 있어요.')
  return v
}
