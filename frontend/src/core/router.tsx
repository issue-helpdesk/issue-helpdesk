/**
 * 화면 경로(라우팅) 정의.
 *
 * 새 화면을 만들면 여기에 경로를 추가한다.
 * 로그인이 필요한 화면은 `RequireAuth` 아래에 둔다.
 */
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { HomePlaceholder } from '../views/HomePlaceholder'
import { LoginView } from '../views/login/LoginView'
import { HOME_BY_ROLE } from './roles'
import { useAuth } from './session'

/**
 * 로그인한 사용자만 들어갈 수 있는 영역.
 * 화면 이동을 막는 편의 기능일 뿐이며, 실제 권한 검사는 백엔드가 한다. (SRS NFR-SEC-02)
 */
function RequireAuth() {
  const { user, loading } = useAuth()
  if (loading) return null // 저장된 토큰 확인 중에는 아무것도 그리지 않는다
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

/** 알 수 없는 주소로 오면 로그인 상태에 맞는 첫 화면으로 보낸다. */
function Landing() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? HOME_BY_ROLE[user.role] : '/login'} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginView />} />

      {/* 로그인 필요 영역. 화면을 만들면 HomePlaceholder 를 실제 화면으로 바꾼다 */}
      <Route element={<RequireAuth />}>
        <Route path="/new" element={<HomePlaceholder title="새 문의" />} />
        <Route path="/queue" element={<HomePlaceholder title="처리할 문의" />} />
        <Route path="/dash" element={<HomePlaceholder title="대시보드" />} />
      </Route>

      <Route path="*" element={<Landing />} />
    </Routes>
  )
}
