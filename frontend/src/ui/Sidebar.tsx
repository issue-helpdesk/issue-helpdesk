/**
 * 사이드바: 로고, 메뉴, 최근 문의, 로그인 사용자 정보.
 *
 * 메뉴는 역할에 따라 다르다. 문의 메뉴(새 문의·문의 내역·FAQ)는 모든 역할이 쓰고,
 * 담당자는 "업무", 관리자는 "운영" 메뉴가 더해진다. (PRD 2장: 담당자·관리자도 일반 임직원 기능을 쓴다)
 * 아직 만들지 않은 화면의 메뉴는 넣지 않고, 화면을 만들 때 아래 목록에 추가한다.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { watchMyInquiries } from '../api/inquiries'
import { listTickets, watchTickets } from '../api/tickets'
import type { InquirySummary, ServiceRole } from '../api/types'
import { formatRelative } from '../core/format'
import { HOME_BY_ROLE, ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Icon, type IconName } from './Icon'
import { Logo } from './Logo'
import { useShell } from './shellContext'
import { stateView } from './stateStyle'
import { ThemeSwitch } from './ThemeSwitch'

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
  AGENT: {
    group: '업무',
    items: [
      { to: '/my', label: '내 대시보드', icon: 'home' },
      { to: '/queue', label: '처리할 문의', icon: 'file' },
      { to: '/stats', label: '통계', icon: 'chart' },
    ],
  },
  ADMIN: {
    group: '운영',
    items: [
      { to: '/dash', label: '대시보드', icon: 'home' },
      { to: '/tickets', label: '전체 문의', icon: 'file' },
      { to: '/accounts', label: '계정 관리', icon: 'user' },
    ],
  },
}

/** 이름 끝 두 글자를 프로필 동그라미에 보여 준다 */
const initials = (name: string) => name.slice(-2)

export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { user, logout } = useAuth()
  const { openProfile } = useShell()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [recent, setRecent] = useState<InquirySummary[]>([])
  // 담당자·관리자의 문의 메뉴 접기. undefined 는 자동: 사이드바가 넘칠 때만 접고, 넓어지면 되돌린다
  const [inqOpen, setInqOpen] = useState<boolean | undefined>(undefined)
  const [auto, setAuto] = useState(false)
  const sideRef = useRef<HTMLElement>(null)
  // 담당자: 처리할 문의 건수(처리 대기·처리 중·해결 확인 대기)와 Jira 알림이 온 건수
  const [queue, setQueue] = useState({ n: 0, nw: 0 })
  const agentId = user?.serviceRole === 'AGENT' ? user.id : null
  useEffect(() => {
    if (!user || agentId === null) return
    return watchTickets(() => {
      listTickets(user, { view: 'ASSIGNED', assigneeId: agentId, size: 100 }).then((r) => {
        if (r.ok) setQueue({ n: r.data.items.filter((t) => t.workStatus && t.workStatus !== 'CLS').length, nw: r.data.items.filter((t) => t.jiraMention).length })
      })
    })
  }, [user, agentId])

  // 최근 문의 목록을 불러오고, 새 문의나 진행 상황이 바뀔 때마다 다시 받는다
  const employeeNo = user?.employeeNo
  useEffect(() => {
    if (!employeeNo) return
    return watchMyInquiries(employeeNo, setRecent)
  }, [employeeNo])

  const extra = EXTRA_MENU[user?.serviceRole ?? 'EMPLOYEE']
  const fold = !!extra
  const open = !fold || inqOpen !== false

  useLayoutEffect(() => {
    const sd = sideRef.current
    if (!sd || !fold || inqOpen !== undefined || window.innerWidth <= 860) return
    if (sd.scrollHeight > sd.clientHeight + 1) {
      setInqOpen(false)
      setAuto(true)
    }
  }, [fold, inqOpen, recent.length, queue.n])
  useEffect(() => {
    const back = () => {
      if (auto && window.innerWidth > 860) {
        setInqOpen(undefined)
        setAuto(false)
      }
    }
    window.addEventListener('resize', back)
    return () => window.removeEventListener('resize', back)
  }, [auto])

  if (!user) return null
  const unread = recent.reduce((sum, i) => sum + i.unread, 0)

  const go = (to: string) => {
    navigate(to)
    onNavigate() // 좁은 화면에서는 이동하면 사이드바를 닫는다
  }

  // 상세가 열려 있어도(/queue/123) 그 메뉴를 강조한다
  const on = (to: string) => pathname === to || pathname.startsWith(`${to}/`)
  const renderItem = (it: NavItem) => (
    <button key={it.to} type="button" className={on(it.to) ? 'on' : ''} aria-current={on(it.to) ? 'page' : undefined} onClick={() => go(it.to)}>
      <Icon name={it.icon} />
      <span>{it.label}</span>
      {/* 확인하지 않은 담당자 답변 수 (0 이면 숨김, 99 초과는 99+) */}
      {it.to === '/list' && unread > 0 && <span className="count">{unread > 99 ? '99+' : unread}</span>}
      {/* 처리할 문의: 건수, 문의자 새 알림이 있으면 점(건수가 있을 때) 또는 NEW */}
      {it.to === '/queue' && queue.nw > 0 && queue.n > 0 && (
        <span className="count has-new" role="img" aria-label={`${queue.n}건, 새 알림 ${queue.nw}건`} title={`새 알림 ${queue.nw}건`}>
          {queue.n}
        </span>
      )}
      {it.to === '/queue' && queue.nw > 0 && queue.n === 0 && <span className="count nw">NEW {queue.nw}</span>}
      {it.to === '/queue' && queue.nw === 0 && queue.n > 0 && <span className="count">{queue.n}</span>}
    </button>
  )

  return (
    <aside className="side" ref={sideRef}>
      <div className="brand">
        {/* 로고는 홈으로 가는 버튼: 문의자=새 문의, 담당자=처리할 문의, 관리자=대시보드 */}
        <button type="button" className="brandbtn" aria-label="ITssue 홈으로" onClick={() => go(HOME_BY_ROLE[user.serviceRole])}>
          <Logo width={118} kind="word" />
        </button>
      </div>

      <nav className="nav" aria-label="주 메뉴">
        {fold ? (
          <button type="button" className="grp tg" aria-expanded={open} aria-label={`문의 메뉴 ${open ? '접기' : '펼치기'}`} onClick={() => { setInqOpen(!open); setAuto(false) }}>
            문의
            <span className="chv" aria-hidden="true">
              <Icon name="chevron" />
            </span>
          </button>
        ) : (
          <div className="grp">문의</div>
        )}
        {open && INQUIRY_MENU.map(renderItem)}
        {extra && (
          <>
            <div className="grp">{extra.group}</div>
            {extra.items.map(renderItem)}
          </>
        )}
      </nav>

      {recent.length > 0 && (
        <div className="nav">
          <div className="grp gsr">
            최근 문의
            {/* 문의 내역으로 가서 검색 칸에 바로 입력할 수 있게 한다 */}
            <button type="button" className="gic" aria-label="최근 문의 검색" title="내 문의 검색" onClick={() => { navigate('/list', { state: { focusSearch: Date.now() } }); onNavigate() }}>
              <Icon name="search" size={15} />
            </button>
          </div>
          <div className="recent">
            {recent.slice(0, 5).map((i) => {
              const sv = stateView(i)
              const tone = sv.tone
              return (
                <button key={i.id} type="button" className={`rt${pathname === `/chat/${i.id}` ? ' on' : ''}`} onClick={() => go(`/chat/${i.id}`)}>
                  <b>
                    <span>{i.title}</span>
                    {i.unread > 0 && <span className="count">{i.unread}</span>}
                  </b>
                  <small>
                    <span className="rs" style={{ color: `var(--s-${tone}-fg)` }}>
                      <i style={{ background: `var(--s-${tone}-dot)` }} />
                      {sv.label}
                    </span>{' '}
                    · {formatRelative(i.updatedAt)}
                  </small>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="modebar">
        <small>화면 모드</small>
        <ThemeSwitch />
      </div>

      <div className="who">
        {/* 이름 영역을 누르면 "내 프로필" 창이 열린다 */}
        <button type="button" className="whobtn" aria-label="내 프로필 열기" onClick={openProfile}>
          <span className="pf">{initials(user.name)}</span>
          <div>
            <div className="nm">{user.name}</div>
            <small>
              {user.departmentName} · {ROLE_LABEL[user.serviceRole]}
            </small>
          </div>
        </button>
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
          <Icon name="logout" />
        </button>
      </div>
    </aside>
  )
}
