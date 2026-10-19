/**
 * 로그인 후 첫 화면 자리표시.
 * 새 문의·처리할 문의·대시보드 화면을 만들면 core/router.tsx 에서 실제 화면으로 교체한다.
 */
import { useNavigate } from 'react-router-dom'
import { ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Logo } from '../ui/Logo'

export function HomePlaceholder({ title }: { title: string }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null

  return (
    <main className="placeholder">
      <Logo width={112} kind="word" />
      <h1>{title}</h1>
      <p className="muted">
        {user.name}님 ({user.dept} · {ROLE_LABEL[user.role]})으로 로그인했어요. 이 화면은 아직 준비 중이에요.
      </p>
      <button
        className="btn sec"
        type="button"
        onClick={() => {
          // 로그아웃하면 토큰을 지우고 로그인 화면으로 돌아간다 (뒤로가기로 돌아오지 못하게 replace)
          logout()
          navigate('/login', { replace: true })
        }}
      >
        로그아웃
      </button>
    </main>
  )
}
