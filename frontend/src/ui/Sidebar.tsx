/**
 * 사이드바: 로고, 메뉴, 최근 문의, 로그인 사용자 정보.
 *
 * 메뉴는 역할에 따라 다르다. 문의 메뉴(새 문의·문의 내역·FAQ)는 모든 역할이 쓰고,
 * 담당자는 "업무", 관리자는 "운영" 메뉴가 더해진다. (PRD 2장: 담당자·관리자도 일반 임직원 기능을 쓴다)
 * 아직 만들지 않은 화면의 메뉴는 넣지 않고, 화면을 만들 때 아래 목록에 추가한다.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { watchMyInquiries } from '../api/inquiries'
import type { InquirySummary, ServiceRole } from '../api/types'
import { formatRelative } from '../core/format'
import { HOME_BY_ROLE, ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Icon, type IconName } from './Icon'
import { Logo } from './Logo'
import { STATE_TONE } from './stateStyle'

interface NavItem {
  to: string
  label: string
  icon: IconName
}

/** 모든 역할이 쓰는 문의 메뉴 */
const INQUIRY_MENU: NavItem[] = [
  { to: '/new', label: '새 문의', icon: 'plus' },
  { to: '/list', label: '문의 내역', icon: 'chat' },
  { to: '/faq', label: 'FAQ', icon: 'help' },
]

/** 역할별로 더해지는 메뉴 (문의자는 없음) */
const EXTRA_MENU: Partial<Record<ServiceRole, { group: string; items: NavItem[] }>> = {
  AGENT: { group: '업무', items: [{ to: '/queue', label: '처리할 문의', icon: 'file' }] },
  ADMIN: { group: '운영', items: [{ to: '/dash', label: '대시보드', icon: 'home' }] },
}

/** 이름 끝 두 글자를 프로필 동그라미에 보여 준다 */
const initials = (name: string) => name.slice(-2)

export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [recent, setRecent] = useState<InquirySummary[]>([])

  // 최근 문의 목록을 불러오고, 새 문의나 진행 상황이 바뀔 때마다 다시 받는다
  const employeeNo = user?.employeeNo
  useEffect(() => {
    if (!employeeNo) return
    return watchMyInquiries(employeeNo, setRecent)
  }, [employeeNo])

  if (!user) return null

  const extra = EXTRA_MENU[user.serviceRole]
  const unread = recent.reduce((sum, i) => sum + i.unread, 0)

  const go = (to: string) => {
    navigate(to)
    onNavigate() // 좁은 화면에서는 이동하면 사이드바를 닫는다
  }

  const renderItem = (it: NavItem) => (
    <button key={it.to} type="button" className={pathname === it.to ? 'on' : ''} aria-current={pathname === it.to ? 'page' : undefined} onClick={() => go(it.to)}>
      <Icon name={it.icon} />
      <span>{it.label}</span>
      {/* 확인하지 않은 담당자 답변 수 (0 이면 숨김, 99 초과는 99+) */}
      {it.to === '/list' && unread > 0 && <span className="count">{unread > 99 ? '99+' : unread}</span>}
    </button>
  )

  return (
    <aside className="side">
      <div className="brand">
        {/* 로고는 홈으로 가는 버튼: 문의자=새 문의, 담당자=처리할 문의, 관리자=대시보드 */}
        <button type="button" className="brandbtn" aria-label="ITssue 홈으로" onClick={() => go(HOME_BY_ROLE[user.serviceRole])}>
          <Logo width={112} />
        </button>
      </div>

      <nav className="nav" aria-label="주 메뉴">
        <div className="grp">문의</div>
        {INQUIRY_MENU.map(renderItem)}
        {extra && (
          <>
            <div className="grp">{extra.group}</div>
            {extra.items.map(renderItem)}
          </>
        )}
      </nav>

      {recent.length > 0 && (
        <div className="nav">
          <div className="grp">최근 문의</div>
          <div className="recent">
            {recent.slice(0, 5).map((i) => {
              const tone = STATE_TONE[i.stateKind]
              return (
                <button key={i.id} type="button" className={`rt${pathname === `/chat/${i.id}` ? ' on' : ''}`} onClick={() => go(`/chat/${i.id}`)}>
                  <b>
                    <span>{i.title}</span>
                    {i.unread > 0 && <span className="count">{i.unread}</span>}
                  </b>
                  <small>
                    <span className="rs" style={{ color: `var(--s-${tone}-fg)` }}>
                      <i style={{ background: `var(--s-${tone}-dot)` }} />
                      {i.stateLabel}
                    </span>{' '}
                    · {formatRelative(i.updatedAt)}
                  </small>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="who">
        <span className="pf">{initials(user.name)}</span>
        <div>
          <div className="nm">{user.name}</div>
          <small>
            {user.departmentName} · {ROLE_LABEL[user.serviceRole]}
          </small>
        </div>
        <button
          className="btn ghost sm out"
          type="button"
          aria-label="로그아웃"
          title="로그아웃"
          onClick={() => {
            // 로그아웃하면 토큰을 지우고 로그인 화면으로 돌아간다 (뒤로가기로 돌아오지 못하게 replace)
            logout()
            navigate('/login', { replace: true })
          }}
        >
          <Icon name="arrow" />
        </button>
      </div>
    </aside>
  )
}
