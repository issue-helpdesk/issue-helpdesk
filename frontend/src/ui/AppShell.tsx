/**
 * 로그인 후 화면의 공통 틀: 왼쪽 사이드바 + 오른쪽 본문(Outlet).
 *
 * 화면 폭이 860px 이하이면 사이드바는 숨겨지고, 각 화면 상단바의 메뉴 버튼으로 열고 닫는다.
 * 본문에는 각 화면(views)이 자기 상단바(Topbar)와 내용을 그린다.
 *
 * 키보드: 사이드바를 열면 첫 메뉴로 초점이 가고, Esc 로 닫으면 메뉴 버튼으로 돌아간다.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../core/session'
import { PasswordDialog } from './PasswordDialog'
import { Sidebar } from './Sidebar'
import { ShellContext } from './shellContext'

export function AppShell() {
  // 사이드바를 연 시점의 경로를 기억한다. 다른 화면으로 이동하면 경로가 달라져 자동으로 닫힌 것으로 본다.
  const [openPath, setOpenPath] = useState<string | null>(null)
  const { pathname } = useLocation()
  const navOpen = openPath === pathname
  const { user } = useAuth()
  // "내 프로필" 창. 임시 비밀번호 상태에서는 사용자가 열지 않아도 닫을 수 없는 창이 먼저 뜬다.
  const [profileOpen, setProfileOpen] = useState(false)
  const forced = !!user?.passwordChangeRequired

  const toggleNav = useCallback(() => setOpenPath((cur) => (cur === pathname ? null : pathname)), [pathname])
  const closeNav = useCallback(() => setOpenPath(null), [])
  const openProfile = useCallback(() => setProfileOpen(true), [])
  const value = useMemo(() => ({ toggleNav, openProfile }), [toggleNav, openProfile])

  // 사이드바가 열리면 첫 메뉴로 초점을 옮기고, Esc 로 닫으면 메뉴 버튼으로 돌려 보낸다
  useEffect(() => {
    if (!navOpen) return
    document.querySelector<HTMLElement>('.side .nav button')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpenPath(null)
      document.querySelector<HTMLElement>('.top .menu, .xmenu')?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navOpen])

  // 화면이 바뀌면 본문으로 초점을 옮긴다. 이미 입력칸 등에 초점이 있으면 건드리지 않는다.
  useEffect(() => {
    const main = document.querySelector<HTMLElement>('main.main')
    if (!main) return
    main.id = 'main'
    main.tabIndex = -1
    const a = document.activeElement
    if (!a || a === document.body || a.closest('.side')) main.focus({ preventScroll: true })
  }, [pathname])
  const skip = () => document.getElementById('main')?.focus()

  return (
    <ShellContext.Provider value={value}>
      <div className={`app${navOpen ? ' nav-open' : ''}`}>
        <button type="button" className="skip" onClick={skip}>
          본문으로 건너뛰기
        </button>
        {/* 좁은 화면에서 사이드바 바깥을 누르면 닫히도록 하는 어두운 막 */}
        <div className="scrim" onClick={closeNav} />
        <Sidebar onNavigate={closeNav} />
        <Outlet />
        {(forced || profileOpen) && <PasswordDialog forced={forced} onClose={() => setProfileOpen(false)} />}
      </div>
    </ShellContext.Provider>
  )
}
