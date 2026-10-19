/**
 * 로그인 후 화면의 공통 틀: 왼쪽 사이드바 + 오른쪽 본문(Outlet).
 *
 * 화면 폭이 860px 이하이면 사이드바는 숨겨지고, 각 화면 상단바의 메뉴 버튼으로 열고 닫는다.
 * 본문에는 각 화면(views)이 자기 상단바(Topbar)와 내용을 그린다.
 */
import { useCallback, useMemo, useState } from 'react'
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
