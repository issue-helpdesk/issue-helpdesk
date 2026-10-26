/**
 * 앱 최상위 컴포넌트.
 * 로고 심볼 정의를 한 번만 깔아 두고, 경로별 화면은 core/router 에서 정한다.
 */
import { AppRoutes } from './core/router'
import { LogoDefs } from './ui/Logo'

// LogoDefs: 여러 곳에서 사용할 로고의 SVG 정의 준비
// AppRoutes : 현재 주소에 맞는 화면을 표시하는 역할.
export default function App() {
  return (
    <>
      <LogoDefs />
      <AppRoutes />
    </>
  )
}
