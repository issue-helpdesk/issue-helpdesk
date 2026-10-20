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
import { Sidebar } from './Sidebar'
import { ShellContext } from './shellContext'

export function AppShell() {
  // 사이드바를 연 시점의 경로를 기억한다. 다른 화면으로 이동하면 경로가 달라져 자동으로 닫힌 것으로 본다.
  const [openPath, setOpenPath] = useState<string | null>(null)
  const { pathname } = useLocation()
  const navOpen = openPath === pathname

  const toggleNav = useCallback(() => setOpenPath((cur) => (cur === pathname ? null : pathname)), [pathname])
  const closeNav = useCallback(() => setOpenPath(null), [])
  const value = useMemo(() => ({ toggleNav }), [toggleNav])

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

  return (
    <ShellContext.Provider value={value}>
      <div className={`app${navOpen ? ' nav-open' : ''}`}>
        {/* 좁은 화면에서 사이드바 바깥을 누르면 닫히도록 하는 어두운 막 */}
        <div className="scrim" onClick={closeNav} />
        <Sidebar onNavigate={closeNav} />
        <Outlet />
      </div>
    </ShellContext.Provider>
  )
}
