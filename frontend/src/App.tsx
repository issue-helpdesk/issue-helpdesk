/**
 * 앱 최상위 컴포넌트.
 * 로고 심볼 정의를 한 번만 깔아 두고, 경로별 화면은 core/router 에서 정한다.
 */
import { AppRoutes } from './core/router'
import { LogoDefs } from './ui/Logo'

export default function App() {
  return (
    <>
      <LogoDefs />
      <AppRoutes />
    </>
  )
}
