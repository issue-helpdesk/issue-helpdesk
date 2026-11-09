/**
 * 사이드바: 로고, 메뉴, 최근 문의, 로그인 사용자 정보.
 *
 * 메뉴는 역할에 따라 다르다. 문의 메뉴(새 문의·문의 내역·FAQ)는 모든 역할이 쓰고,
 * 담당자는 "업무", 관리자는 "운영" 메뉴가 더해진다. (PRD 2장: 담당자·관리자도 일반 임직원 기능을 쓴다)
 * 아직 만들지 않은 화면의 메뉴는 넣지 않고, 화면을 만들 때 아래 목록에 추가한다.
 */
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { watchMyInquiries } from '../api/inquiries'
import { markInquirySeen } from '../api/inquirySeen'
import { watchUnread } from '../api/notifications'
import { getIngestFailures, watchIngest } from '../api/guideWatch'
import { countOpsAttention } from '../api/ops'
import { countSecurityAlerts, watchSecurity } from '../api/security'
import { listTickets, watchTickets } from '../api/tickets'
import type { InquirySummary, ServiceRole } from '../api/types'
import { USE_MOCK_INQUIRY, USE_MOCK_NOTIFY } from '../core/config'
import { formatRelative } from '../core/format'
import { refreshInquiryList } from '../core/poll'
import { HOME_BY_ROLE, ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Icon, type IconName } from './Icon'
import { Logo } from './Logo'
import { useShell } from './shellContext'
import { stateView } from './stateStyle'
import { ThemeSwitch } from './ThemeSwitch'
import { USER_IN_TOP_RIGHT } from './userPlacement'

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

/** 가이드 열람: 관리자는 가이드 관리를 쓰므로 문의자·담당자에게만 보인다 */
const DOCS_MENU: NavItem = { to: '/docs', label: '가이드', icon: 'folder' }

/** 역할별로 더해지는 메뉴 (문의자는 없음) */
const EXTRA_MENU: Partial<Record<ServiceRole, { group: string; items: NavItem[] }>> = {
  AGENT: {
    group: '업무',
    items: [
      { to: '/my', label: '내 대시보드', icon: 'home' },
      { to: '/queue', label: '처리할 문의', icon: 'file' },
      { to: '/stats', label: '통계', icon: 'chart' },
      { to: '/calendar', label: '캘린더', icon: 'calendar' },
    ],
  },
  ADMIN: {
    group: '운영',
    items: [
      { to: '/dash', label: '대시보드', icon: 'home' },
      { to: '/stats', label: '통계', icon: 'chart' },
      { to: '/ops', label: '운영 현황', icon: 'alert' },
      { to: '/security', label: '보안·감사 알림', icon: 'bell' },
      { to: '/audit', label: '운영 기록', icon: 'clock' },
      { to: '/tickets', label: '전체 문의', icon: 'file' },
      { to: '/guides', label: '가이드 관리', icon: 'folder' },
      { to: '/calendar', label: '캘린더', icon: 'calendar' },
      { to: '/accounts', label: '계정 관리', icon: 'user' },
      { to: '/ai', label: 'AI 운영', icon: 'shield' },
    ],
  },
}

/** 이름 끝 두 글자를 프로필 동그라미에 보여 준다 */
const initials = (name: string) => name.slice(-2)

export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { user, logout } = useAuth()
  const { openProfile, sideOff, toggleSide } = useShell()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [recent, setRecent] = useState<InquirySummary[]>([])
  // 메뉴가 길어 최근 문의가 잘리면 5개 대신 2개만 보인다. 문의 메뉴는 항상 펼쳐 둔다
  const [shortRecent, setShortRecent] = useState(false)
  const sideRef = useRef<HTMLElement>(null)
  // 담당자: 처리할 문의 건수(처리 대기·처리 중·해결 확인 대기)와 새 알림(담당자 배정) 개수
  const [queue, setQueue] = useState({ n: 0, nw: 0 })
  const agentId = user?.serviceRole === 'AGENT' ? user.id : null
  // 관리자: 연동·배정 확인이 필요한 접수 수 (운영 현황 메뉴 옆)
  const [attention, setAttention] = useState(0)
  const [secNew, setSecNew] = useState(0)
  const isAdmin = user?.serviceRole === 'ADMIN'
  // 가이드 적재에 실패한 버전 수 (가이드 관리 메뉴 옆 점)
  const guideFail = useSyncExternalStore(watchIngest, getIngestFailures).length
  useEffect(() => {
    if (!user || !isAdmin) return
    return watchTickets(() => {
      countOpsAttention(user).then(setAttention)
    })
  }, [user, isAdmin])
  // 관리자: 신규 보안·감사 알림 수 (보안·감사 알림 메뉴 옆)
  useEffect(() => {
    if (!user || !isAdmin) return
    return watchSecurity(() => {
      countSecurityAlerts(user).then((c) => setSecNew(c?.신규 ?? 0))
    })
  }, [user, isAdmin])
  useEffect(() => {
    if (!user || agentId === null) return
    return watchTickets(() => {
      listTickets(user, { view: 'ASSIGNED', assigneeId: agentId, size: 100 }).then((r) => {
        if (r.ok) setQueue((q) => ({ n: r.data.items.filter((t) => t.workStatus && t.workStatus !== 'CLS').length, nw: q.nw }))
      })
    })
  }, [user, agentId])
  // 서버 모드: 새 알림(담당자 배정) 개수는 서버가 알려 주는 안 읽은 개수(NT-02)를 쓴다
  useEffect(() => {
    if (!user || agentId === null || USE_MOCK_NOTIFY) return
    return watchUnread((c) => setQueue((q) => ({ ...q, nw: c.count })))
  }, [user, agentId])

  // 최근 문의 목록을 불러오고, 새 문의나 진행 상황이 바뀔 때마다 다시 받는다
  const employeeNo = user?.employeeNo
  // 관리자는 서버가 모든 사용자의 문의를 주므로 본인 번호를 보내 내 문의만 받는다
  const ownerId = user?.serviceRole === 'ADMIN' ? user.id : undefined
  useEffect(() => {
    if (!employeeNo) return
    return watchMyInquiries(employeeNo, setRecent, ownerId)
  }, [employeeNo, ownerId])
  // 서버가 변화를 알려 주지 않으므로 화면을 옮길 때 한 번 다시 읽는다 (짧은 시간에 여러 번 옮겨도 15초에 한 번만)
  const lastRefresh = useRef<number | null>(null)
  useEffect(() => {
    const now = Date.now()
    const first = lastRefresh.current === null // 처음 열 때는 목록을 이미 읽는다
    if (!first && now - (lastRefresh.current ?? 0) < 15_000) return
    lastRefresh.current = now
    if (!first) refreshInquiryList()
  }, [pathname])

  const extra = EXTRA_MENU[user?.serviceRole ?? 'EMPLOYEE']

  useLayoutEffect(() => {
    const sd = sideRef.current
    if (!sd || shortRecent || window.innerWidth <= 860) return
    if (sd.scrollHeight > sd.clientHeight + 1) {
      if (recent.length > 2) {
        // 화면에 그려 본 뒤에야 넘치는지 알 수 있어서 이 안에서 정한다
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setShortRecent(true)
      }
    }
  }, [shortRecent, recent.length, queue.n])
  useEffect(() => {
    const back = () => {
      if (shortRecent && window.innerWidth > 860) setShortRecent(false)
    }
    window.addEventListener('resize', back)
    return () => window.removeEventListener('resize', back)
  }, [shortRecent])

  // 지금 보고 있는 문의에는 새 답변 표시를 두지 않는다 (내가 방금 보낸 글·진행 중인 답변 때문에 점이 켜지지 않게).
  // 서버 모드에서는 보고 있는 문의의 최신 변경 시각까지 봤다고 기록해, 다른 화면으로 옮겨도 점이 남지 않게 한다
  const openId = /^\/chat\/(\d+)$/.exec(pathname)?.[1]
  useEffect(() => {
    if (USE_MOCK_INQUIRY || !employeeNo || !openId) return
    const cur = recent.find((i) => String(i.id) === openId)
    if (cur) markInquirySeen(employeeNo, cur.id, cur.lastAiMessageId)
  }, [recent, openId, employeeNo])
  if (!user) return null
  const shown = recent.map((i) => (String(i.id) === openId ? { ...i, unread: 0 } : i))
  const unread = shown.reduce((sum, i) => sum + i.unread, 0)

  const go = (to: string) => {
    navigate(to)
    onNavigate() // 좁은 화면에서는 이동하면 사이드바를 닫는다
  }

  // 상세가 열려 있어도(/queue/123) 그 메뉴를 강조한다
  const on = (to: string) => pathname === to || pathname.startsWith(`${to}/`)
  const renderItem = (it: NavItem) => (
    <button key={it.to} type="button" className={on(it.to) ? 'on' : ''} data-tip={it.label} aria-current={on(it.to) ? 'page' : undefined} onClick={() => go(it.to)}>
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
      {it.to === '/ops' && attention > 0 && <span className="count">{attention}</span>}
      {it.to === '/security' && secNew > 0 && <span className="count">{secNew}</span>}
      {/* 가이드 적재 실패: 숫자 대신 점 (어느 가이드인지는 가이드 관리에서 분류·가이드 옆 점으로 보인다) */}
      {it.to === '/guides' && isAdmin && guideFail > 0 && <span className="count dot" role="img" aria-label={`적재 실패 ${guideFail}건`} title={`적재에 실패한 가이드 ${guideFail}건`} />}
    </button>
  )

  return (
    <aside className="side" ref={sideRef}>
      <div className="brand">
        {/* 로고는 홈으로 가는 버튼: 문의자=새 문의, 담당자=처리할 문의, 관리자=대시보드 */}
        <button type="button" className="brandbtn" aria-label="ITssue 홈으로" onClick={() => go(HOME_BY_ROLE[user.serviceRole])}>
          <Logo width={118} kind="word" />
          {/* 접힌 레일에서 보이는 작은 IT 로고(디자인 가이드의 단색 IT 심볼) */}
          <svg className="itmark" viewBox="227 141 551 450" aria-hidden="true">
            <path d="M237 151H353V581H237Z" />
            <path d="M391 151H768L741 229C737 240 729 245 714 245H616V581H500V245H391Z" />
          </svg>
        </button>
        {/* 펼친 상태에서는 접기(‹), 접힌 레일에서는 로고에 올리면 펼치기(›) */}
        <button type="button" className="sbk" aria-expanded={!sideOff} aria-label={`사이드바 ${sideOff ? '펼치기' : '접기'}`} title={`사이드바 ${sideOff ? '펼치기' : '접기'}`} onClick={toggleSide}>
          <svg className="i" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M12.5 4.5L7 10l5.5 5.5" />
          </svg>
        </button>
      </div>

      <nav className="nav" aria-label="주 메뉴">
        <div className="grp">문의</div>
        {(user?.serviceRole === 'ADMIN' ? INQUIRY_MENU : [...INQUIRY_MENU, DOCS_MENU]).map(renderItem)}
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
            {shown.slice(0, shortRecent ? 2 : 5).map((i) => {
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
                      <i className={sv.ring ? 'ring' : undefined} style={{ background: `var(--s-${tone}-dot)` }} />
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

      {!USER_IN_TOP_RIGHT && (
        <>
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
        </>
      )}
    </aside>
  )
}
