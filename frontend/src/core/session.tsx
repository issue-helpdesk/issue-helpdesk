/**
 * 로그인 상태(세션) 관리.
 *
 * `AuthProvider` 를 앱 루트에 한 번 두고, 화면에서는 `useAuth()` 로 현재 사용자와
 * 로그인·로그아웃 함수를 꺼내 쓴다. 토큰 보관은 `tokenStore` 가 맡는다.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi } from '../api/auth'
import type { ApiResult, LoginData, LoginRequest, PasswordChangeRequest, User } from '../api/types'
import { tokenStore } from './tokenStore'

/** 로그인 화면 맨 위에 한 번 보여 주는 안내: 비밀번호를 바꾼 뒤 / 로그인이 만료돼 돌아온 뒤 */
export type LoginNote = 'pw-changed' | 'expired'

interface AuthState {
  /** 로그인한 사용자. 로그인 전이면 null */
  user: User | null
  /** 새로고침 직후 저장된 토큰으로 사용자를 확인하는 중인지 */
  loading: boolean
  /** 로그인 화면에 보여 줄 안내. 없으면 null */
  loginNote: LoginNote | null
  /** 사번·비밀번호 로그인 */
  login: (req: LoginRequest) => Promise<ApiResult<LoginData>>
  /** SSO 로그인 (연동 방식 미확정이라 지금은 시연용) */
  loginSso: () => Promise<ApiResult<LoginData>>
  /** 시연 전용: 계정을 골라 바로 로그인 */
  mockQuickLogin: (id: string) => Promise<ApiResult<LoginData>>
  /**
   * 비밀번호 변경. 성공해도 화면은 그대로 두고(변경 완료 안내를 보여 줘야 해서), 다음 단계인
   * `logout('pw-changed')` 를 부르면 로그인 화면으로 돌아간다. (서버는 변경 시 모든 로그인을 끊는다)
   */
  changePassword: (req: PasswordChangeRequest) => Promise<ApiResult<null>>
  /** 로그아웃: 토큰과 사용자 정보를 지운다. note 를 주면 로그인 화면에 그 안내가 보인다. */
  logout: (note?: LoginNote) => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // 저장된 토큰이 있으면 사용자 확인이 끝날 때까지 loading 상태로 시작한다
  const [loading, setLoading] = useState<boolean>(() => !!tokenStore.get())
  const [loginNote, setLoginNote] = useState<LoginNote | null>(null)

  // 새로고침 후 저장된 토큰이 아직 유효한지 서버에 확인한다
  useEffect(() => {
    if (!tokenStore.get()) return
    let alive = true // 화면이 사라진 뒤에는 상태를 바꾸지 않기 위한 표시
    authApi.me().then((r) => {
      if (!alive) return
      if (r.ok) setUser(r.data)
      else {
        // 만료·무효 토큰은 버리고, 로그인 화면에서 만료됐다고 알린다 (별도 창은 없다)
        tokenStore.clear()
        setLoginNote('expired')
      }
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
      setLoginNote(null)
    }
    return r
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      loginNote,
      login: async (req) => accept(await authApi.login(req)),
      loginSso: async () => accept(await authApi.loginSso()),
      mockQuickLogin: async (id) => accept(await authApi.mockQuickLogin(id)),
      changePassword: (req) => authApi.changePassword(req),
      logout: (note) => {
        tokenStore.clear()
        setUser(null)
        setLoginNote(note ?? null)
      },
    }),
    [user, loading, loginNote, accept],
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
