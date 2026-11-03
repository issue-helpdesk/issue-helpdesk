/**
 * 화면 오른쪽 위의 사용자 컨트롤 (공통 UI): 화면 모드(1칸, 올리면 3칸) + 사용자 메뉴(내 프로필·로그아웃).
 * 로그인 화면의 화면 모드와 같은 자리다. 위치 스위치는 ui/userPlacement.ts 하나다. 상세 패널(.detail)은 이 위에 겹쳐 열려서, 패널이 열려 있는 동안은 패널이 이 컨트롤을 덮는다.
 *
 * 상단바(Topbar)가 있는 화면은 상단바 안에, 없는 화면(새 문의)은 floating 으로 화면 오른쪽 위에 띄운다.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Icon } from './Icon'
import { useShell } from './shellContext'
import { ThemeSwitch } from './ThemeSwitch'
import { USER_IN_TOP_RIGHT } from './userPlacement'

/** 이름 끝 두 글자를 프로필 동그라미에 보여 준다 (이름이 아직 없으면 빈 칸) */
const initials = (name?: string) => (name ?? '').slice(-2)

export function UserControls({ floating = false }: { floating?: boolean }) {
  const { user, logout } = useAuth()
  const { openProfile } = useShell()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const first = useRef<HTMLButtonElement>(null)

  // 메뉴는 바깥을 누르거나 Esc 를 누르면 닫는다. 열면 첫 항목으로 초점을 옮긴다
  useEffect(() => {
    if (!open) return
    first.current?.focus()
    const out = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      box.current?.querySelector<HTMLElement>('.av')?.focus()
    }
    document.addEventListener('pointerdown', out)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', out)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  if (!user || !USER_IN_TOP_RIGHT) return null

  return (
    <div className={`tr${floating ? ' fl' : ''}`}>
      <ThemeSwitch compact />
      <div className="um" ref={box}>
        <button type="button" className="av" aria-label="내 메뉴" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {initials(user.name)}
        </button>
        {open && (
          <div className="pop" role="menu" aria-label="내 메뉴">
            <div className="nm">
              <b>{user.name}</b>
              <small>
                {user.departmentName} · {ROLE_LABEL[user.serviceRole]}
              </small>
            </div>
            <button
              type="button"
              role="menuitem"
              className="lk"
              ref={first}
              onClick={() => {
                // 창을 닫으면 메뉴를 열었던 아바타 버튼으로 초점이 돌아가도록 먼저 그쪽에 초점을 둔다 (이 항목은 곧 사라진다)
                box.current?.querySelector<HTMLElement>('.av')?.focus()
                setOpen(false)
                openProfile()
              }}
            >
              내 프로필
            </button>
            <button
              type="button"
              role="menuitem"
              className="lk"
              onClick={() => {
                // 로그아웃하면 토큰을 지우고 로그인 화면으로 돌아간다 (뒤로가기로 돌아오지 못하게 replace)
                logout()
                navigate('/login', { replace: true })
              }}
            >
              <Icon name="logout" size={16} />
              로그아웃
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
