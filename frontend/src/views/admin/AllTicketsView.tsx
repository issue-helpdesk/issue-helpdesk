/**
 * 전체 문의 (관리자, /tickets · /tickets/:ticketId). (design/ITssue-Prototype.html viewTickets)
 * "담당자 처리"는 모든 접수를 상태 탭·검색·필터로 좁혀 보고, 열면 오른쪽에 상세가 붙는다. 처리할 문의(담당자) 화면과 같은 틀이다.
 * "AI 처리"는 티켓 없이 AI 안내로 끝난 상담을 구분별로 본다.
 *
 * 목록은 TK-05(view=ALL), AI 상담은 문의 목록 IQ-02(displayStatus), 팀·담당자 필터는 RF-03·US-01 이다.
 * 서버와 다른 점은 PR 본문과 각 API 함수의 주석에 적었다. (정렬은 접수일·긴급도·업무 상태만, 검색은 접수번호·Jira 키·요약만 서버가 받는다)
 */
import { useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CATEGORIES, URGENCY_LABEL } from '../../api/catalog'
import type { CategoryCode, Urgency, WorkStatus } from '../../api/chatTypes'
import { listAiInquiries, type AiKind, type AiPage } from '../../api/inquiries'
import type { Page } from '../../api/inquiries'
import { listStaff, listSupportGroups, type StaffRef, type SupportGroupRef } from '../../api/reference'
import { listTickets, watchTickets } from '../../api/tickets'
import type { TicketListQuery, TicketSummary } from '../../api/ticketTypes'
import titleDone from '../../assets/mascot/title-done.webp'
import titleInq from '../../assets/mascot/title-inq.webp'
import { formatDateTime, formatElapsed } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { Pager } from '../../ui/Pager'
import { SortTh } from '../../ui/SortTh'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { StaffStatus, UrgencyChip } from '../staff/QueueView'
import { TicketDetailPanel } from '../staff/TicketDetailPanel'

const PAGE_SIZE = 20
type Mode = 'staff' | 'ai'
/** 상태 탭: '' 전체 · none 배정 전(아직 Jira 생성 전) · open 진행 중(처리 대기+처리 중) */
type St = '' | 'none' | 'open' | 'RDY' | 'WIP' | 'FIN' | 'CLS'
const ST_TABS: { key: St; label: string }[] = [
  { key: '', label: '전체' },
  { key: 'none', label: '배정 전' },
  { key: 'open', label: '진행 중' },
  { key: 'FIN', label: '해결 확인 대기' },
  { key: 'CLS', label: '해결 완료' },
]
const URGENCIES: Urgency[] = ['P1', 'P2', 'P3', 'P4']
/** 접수 기간: 오늘 / 최근 30일 / 최근 1년 (며칠 전부터) */
const PERIODS = [
  { value: 'd', label: '오늘', days: 0 },
  { value: 'm', label: '최근 30일', days: 30 },
  { value: 'y', label: '최근 1년', days: 365 },
]
const AI_KINDS: { key: '' | AiKind; label: string }[] = [
  { key: '', label: '전체' },
  { key: 'ok', label: 'AI 해결' },
  { key: 'pend', label: '해결 확인 대기 (AI 안내)' },
  { key: 'unr', label: '미해결 종료' },
]

/** 정렬 열 → API sort 기준 (urgency·createdAt·workStatus 외에는 프로토타입용 임시 값) */
const SORT_KEY = { pri: 'urgency', receipt: 'receiptNo', title: 'summary', status: 'workStatus', when: 'createdAt', cat: 'category', assignee: 'assignee' } as const
type SortCol = keyof typeof SORT_KEY
const AI_SORT_KEY = { title: 'title', cat: 'cat', guide: 'guide', when: 'updatedAt' } as const
type AiSortCol = keyof typeof AI_SORT_KEY

const pad = (n: number) => String(n).padStart(2, '0')
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 아직 Jira 생성·배정이 끝나지 않은 접수의 상태 표시 */
function PreStatus({ t }: { t: TicketSummary }) {
  if (t.jiraSyncStatus === 'NEEDS_ADMIN') return <StateBadge tone="urg" label="Jira 생성 확인 필요" />
  if (t.jiraSyncStatus === 'VERIFYING') return <StateBadge tone="warn" label="생성 여부 확인 중" />
  if (t.assignStatus === 'NEEDS_ADMIN') return <StateBadge tone="urg" label="담당자 배정 확인 필요" />
  return <StateBadge tone="recv" label="접수 완료" />
}

export function AllTicketsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { ticketId } = useParams()
  const openId = ticketId ? Number(ticketId) : null
  const [slide, setSlide] = useState(false)
  const [prevOpen, setPrevOpen] = useState(false)
  if (prevOpen !== (openId !== null)) {
    setPrevOpen(openId !== null)
    setSlide(openId !== null)
  }

  // 대시보드에서 오면 주소의 값으로 시작한다 (?st=open&cat=NET&pri=P12&team=…&staff=…&per=m&alarm=1&unres=1&mode=ai&aik=ok)
  const [params] = useSearchParams()
  const pick = <T extends string>(k: string, ok: readonly T[], d: T): T => (ok.includes(params.get(k) as T) ? (params.get(k) as T) : d)
  const [mode, setMode] = useState<Mode>(() => pick('mode', ['staff', 'ai'] as const, 'staff'))
  const [st, setSt] = useState<St>(() => pick('st', ['', 'none', 'open', 'RDY', 'WIP', 'FIN', 'CLS'] as const, ''))
  const [cat, setCat] = useState<string>(() => pick('cat', ['', ...Object.keys(CATEGORIES)] as const, ''))
  const [pri, setPri] = useState<string>(() => pick('pri', ['', 'P12', 'P1', 'P2', 'P3', 'P4'] as const, ''))
  const [team, setTeam] = useState(() => params.get('team') ?? '')
  const [staff, setStaff] = useState(() => params.get('staff') ?? '')
  const [per, setPer] = useState<string>(() => pick('per', ['', 'd', 'm', 'y'] as const, ''))
  const [alarm, setAlarm] = useState(() => params.get('alarm') === '1')
  const [unres, setUnres] = useState(() => params.get('unres') === '1')
  const [aik, setAik] = useState<'' | AiKind>(() => pick('aik', ['', 'ok', 'pend', 'unr'] as const, ''))
  // AI 처리 보기의 검색어·분류 (접수 기간은 담당자 처리와 함께 쓴다)
  const [aiQ, setAiQ] = useState('')
  const [aiCat, setAiCat] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' } | null>(null)
  const [aiSort, setAiSort] = useState<{ col: AiSortCol; dir: 'asc' | 'desc' } | null>(null)
  const [page, setPage] = useState(1)
  const [aiPage, setAiPage] = useState(1)
  const [data, setData] = useState<Page<TicketSummary> | null>(null)
  const [ai, setAi] = useState<AiPage | null>(null)
  const [counts, setCounts] = useState<Record<string, number> | null>(null)
  const [mentions, setMentions] = useState<{ items: TicketSummary[]; total: number }>({ items: [], total: 0 })
  const [groups, setGroups] = useState<SupportGroupRef[]>([])
  const [staffList, setStaffList] = useState<StaffRef[]>([])
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const [reload, setReload] = useState(0)

  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])

  // 팀·담당자 필터의 목록
  useEffect(() => {
    if (!user) return
    let alive = true
    listSupportGroups().then((r) => alive && r.ok && setGroups(r.data))
    listStaff(user).then((r) => alive && r.ok && setStaffList(r.data))
    return () => {
      alive = false
    }
  }, [user])

  const query: TicketListQuery = useMemo(() => {
    const days = PERIODS.find((p) => p.value === per)?.days
    const w: WorkStatus[] | undefined =
      st === 'open' ? ['RDY', 'WIP'] : st === 'RDY' || st === 'WIP' || st === 'FIN' || st === 'CLS' ? [st] : unres ? ['RDY', 'WIP', 'FIN'] : undefined
    return {
      view: 'ALL',
      page,
      size: PAGE_SIZE,
      sort: sort ? `${SORT_KEY[sort.col]},${sort.dir}` : 'createdAt,desc',
      workStatus: w,
      jiraSyncStatus: st === 'none' ? ['PENDING', 'VERIFYING', 'NEEDS_ADMIN'] : undefined,
      categoryCode: cat ? [cat as CategoryCode] : undefined,
      urgency: pri === 'P12' ? ['P1', 'P2'] : pri ? [pri as Urgency] : undefined,
      groupId: team ? groups.find((g) => g.name === team)?.id : undefined,
      assigneeId: staff ? staffList.find((s) => s.name === staff)?.id : undefined,
      createdFrom: days === undefined ? undefined : daysAgo(days),
      jiraMention: alarm || undefined,
      q: q.trim() || undefined,
    }
  }, [st, unres, cat, pri, team, staff, per, alarm, q, page, sort, groups, staffList])

  useEffect(() => {
    if (!user || mode !== 'staff') return
    let alive = true
    listTickets(user, query).then((r) => {
      if (!alive) return
      if (r.ok) {
        setData(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, mode, query, tick, reload])

  // 상태 탭의 건수: 조건과 상관없이 전체에서 센다 (서버는 목록 응답에 상태별 건수가 없어 상태마다 1건씩 요청해 총건수만 읽는다)
  useEffect(() => {
    if (!user || mode !== 'staff') return
    let alive = true
    const one = (extra: TicketListQuery) => listTickets(user, { view: 'ALL', size: 1, ...extra }).then((r) => (r.ok ? r.data.totalCount : 0))
    Promise.all([one({}), one({ jiraSyncStatus: ['PENDING', 'VERIFYING', 'NEEDS_ADMIN'] }), one({ workStatus: ['RDY'] }), one({ workStatus: ['WIP'] }), one({ workStatus: ['FIN'] }), one({ workStatus: ['CLS'] })]).then(([all, none, RDY, WIP, FIN, CLS]) => {
      if (alive) setCounts({ '': all, none, open: RDY + WIP, RDY, WIP, FIN, CLS })
    })
    listTickets(user, { view: 'ALL', size: 3, jiraMention: true }).then((r) => alive && r.ok && setMentions({ items: r.data.items, total: r.data.totalCount }))
    return () => {
      alive = false
    }
  }, [user, mode, tick])

  useEffect(() => {
    if (!user || mode !== 'ai') return
    let alive = true
    listAiInquiries({ page: aiPage, size: PAGE_SIZE, sort: aiSort ? `${AI_SORT_KEY[aiSort.col]},${aiSort.dir}` : undefined, per: per as 'd' | 'm' | 'y' | '', kind: aik, categoryCode: aiCat as CategoryCode | '', q: aiQ }).then((r) => {
      if (!alive) return
      if (r.ok) {
        setAi(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, mode, aiPage, aiSort, per, aik, aiCat, aiQ, reload])

  if (!user) return null
  // 관리자만 쓴다 (실제 권한은 서버가 검사한다)
  if (user.serviceRole !== 'ADMIN') return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />

  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage(1)
  }
  const active = [cat, pri, team, staff, per, alarm && 'a', unres && 'u'].filter(Boolean).length
  const clear = () => {
    setCat('')
    setPri('')
    setTeam('')
    setStaff('')
    setPer('')
    setAlarm(false)
    setUnres(false)
    setPage(1)
  }
  const onSort = (col: SortCol) => {
    setSort((s) => (s && s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: col === 'when' ? 'desc' : 'asc' }))
    setPage(1)
  }
  const onAiSort = (col: AiSortCol) => {
    setAiSort((s) => (s && s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: col === 'when' ? 'desc' : 'asc' }))
    setAiPage(1)
  }
  const switchMode = (m: Mode) => {
    setMode(m)
    setError('')
    setPage(1)
    setAiPage(1)
    if (m === 'ai' && openId !== null) navigate('/tickets')
  }
  const open = (id: number) => navigate(`/tickets/${id}`)
  const items = data?.items ?? []
  const subOpen = st === 'open' || st === 'RDY' || st === 'WIP'
  const perChip = per && (
    <span className="d2p act">
      <small>접수 기간</small>
      <span>{PERIODS.find((p) => p.value === per)?.label}</span>
      <button type="button" className="x" aria-label="접수 기간 조건 해제" onClick={() => { setPer(''); setPage(1); setAiPage(1) }}>
        ✕
      </button>
    </span>
  )

  const seg = (
    <div className="seg" role="group" aria-label="구분">
      <button type="button" className={mode === 'staff' ? 'on' : ''} aria-pressed={mode === 'staff'} onClick={() => switchMode('staff')}>
        담당자 처리
      </button>
      <button type="button" className={mode === 'ai' ? 'on' : ''} aria-pressed={mode === 'ai'} onClick={() => switchMode('ai')}>
        AI 처리
      </button>
    </div>
  )

  const head = (
    <div>
      <div className="eyebrow">ALL INQUIRIES</div>
      <h1>모든 문의를 한눈에 확인해요</h1>
      <p className="muted" style={{ marginTop: 4 }}>
        AI 해결과 담당자 처리를 구분해서 볼 수 있어요.
      </p>
    </div>
  )

  if (mode === 'ai') {
    const rows = ai?.items ?? []
    return (
      <main className="main">
        <Topbar title="전체 문의" sub={`AI 상담 ${ai?.totalCount ?? 0}건`} lead={<img className="tti" src={titleDone} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            {head}
            {seg}
            <div className="d2seg" role="group" aria-label="AI 상담 결과 구분">
              {AI_KINDS.map((k) => (
                <button key={k.key || 'all'} type="button" className={aik === k.key ? 'on' : ''} aria-pressed={aik === k.key} onClick={() => { setAik(k.key); setAiPage(1) }}>
                  {k.label} {ai && <em>{ai.counts[k.key || 'all']}</em>}
                </button>
              ))}
            </div>
            <div className="d2f" role="group" aria-label="필터">
              <label className={`srch${aiQ.trim() ? ' f' : ''}`}>
                <Icon name="search" size={18} />
                <input value={aiQ} placeholder="문의 제목 · 번호 · 가이드로 검색" aria-label="AI 처리 검색" autoComplete="off" onChange={(e) => { setAiQ(e.target.value); setAiPage(1) }} />
                {aiQ && (
                  <button type="button" className="x" aria-label="검색어 지우기" onClick={() => { setAiQ(''); setAiPage(1) }}>
                    ✕
                  </button>
                )}
              </label>
              <span className="small muted" role="status" aria-live="polite">
                {ai?.totalCount ?? 0}건
              </span>
              <FilterPill label="분류" value={aiCat} options={Object.keys(CATEGORIES).map((c) => ({ value: c, label: CATEGORIES[c as CategoryCode].name }))} onChange={(v) => { setAiCat(v); setAiPage(1) }} />
              <FilterPill label="접수 기간" value={per} options={PERIODS.map((p) => ({ value: p.value, label: p.label }))} onChange={(v) => { setPer(v); setAiPage(1) }} />
              {(aiCat || per || aiQ.trim()) && (
                <button type="button" className="d2clr" onClick={() => { setAiCat(''); setPer(''); setAiQ(''); setAiPage(1) }}>
                  ✕ 필터 해제
                </button>
              )}
            </div>
            <div className="alert info">
              <Icon name="check" />
              <div>
                AI 안내까지만 이어지고 티켓이 만들어지지 않은 문의예요. <b>해결 확인 대기</b>는 문의자가 아직 해결 여부를 고르지 않은 건, <b>미해결 종료</b>는 해결되지 않고 끝난 건이에요. 해결 완료(CLS)와는 따로 집계해요.
              </div>
            </div>
            <div className="panel" style={{ padding: '6px 10px' }} aria-live="polite">
              {error ? (
                <div className="alert err" role="alert">
                  <Icon name="alert" />
                  <div>
                    {error}{' '}
                    <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                      다시 시도
                    </button>
                  </div>
                </div>
              ) : ai === null ? (
                <div className="empty" role="status">
                  불러오는 중이에요…
                </div>
              ) : rows.length ? (
                <>
                  <div className="tw">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <SortTh col="title" label="문의" sort={aiSort} onSort={onAiSort} />
                          <SortTh col="cat" label="분류" sort={aiSort} onSort={onAiSort} />
                          <SortTh col="guide" label="사용한 가이드" sort={aiSort} onSort={onAiSort} />
                          <th>구분</th>
                          <SortTh col="when" label="시점" sort={aiSort} onSort={onAiSort} />
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.id}>
                            <td>
                              <b>{r.title}</b>
                              <small className="mono">{r.id}</small>
                            </td>
                            <td>{r.categoryCode ? <span className={`tag c-${r.categoryCode}`}>{CATEGORIES[r.categoryCode].name}</span> : <span className="muted small">미분류</span>}</td>
                            <td className="small">{r.guide}</td>
                            <td>
                              {r.kind === 'pend' ? <StateBadge tone="need" label="해결 확인 대기" sub="AI 안내" block /> : r.kind === 'unr' ? <StateBadge tone="warn" label="미해결 종료" /> : <StateBadge tone="ok" label="AI 해결" />}
                            </td>
                            <td className="muted small">{r.when}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={ai.page} size={ai.size} total={ai.totalCount} onPage={setAiPage} />
                </>
              ) : (
                <div className="empty">조건에 맞는 상담이 없어요.</div>
              )}
            </div>
          </div>
        </div>
      </main>
    )
  }

  return (
    <>
      <main className="main">
        <Topbar title="전체 문의" sub={`${data?.totalCount ?? 0}건`} lead={<img className="tti" src={titleInq} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            {head}

            {mentions.total > 0 && (
              <div className="alert err bn" role="status">
                <Icon name="bell" />
                <div className="bnl">
                  <b>문의자가 답변했어요.</b>
                  {mentions.items.map((t) => (
                    <button key={t.id} type="button" className="lk rl" onClick={() => open(t.id)}>
                      <span className="rc">{t.receiptNo}</span>
                      <span className="sp" aria-hidden="true">
                        ·
                      </span>
                      {t.summary}
                    </button>
                  ))}
                  {mentions.total > 3 && <span className="rmore">외 {mentions.total - 3}건</span>}
                </div>
              </div>
            )}

            {seg}

            <div className="d2seg" role="group" aria-label="처리 상태">
              {ST_TABS.map((x) => {
                const on = st === x.key || (x.key === 'open' && (st === 'RDY' || st === 'WIP'))
                return (
                  <button key={x.key || 'all'} type="button" className={on ? 'on' : ''} aria-pressed={on} onClick={() => reset(setSt)(x.key)}>
                    {x.label} {counts && <em>{counts[x.key]}</em>}
                  </button>
                )
              })}
            </div>
            {subOpen && (
              <div className="subc" role="group" aria-label="진행 중 상태 구분">
                {([['open', '전체 진행 중'], ['RDY', '처리 대기'], ['WIP', '처리 중']] as const).map(([k, label]) => (
                  <button key={k} type="button" className={`chip${st === k ? ' on' : ''}`} aria-pressed={st === k} onClick={() => reset(setSt)(k)}>
                    {label} {counts && <em>{counts[k]}</em>}
                  </button>
                ))}
              </div>
            )}

            <div className="d2f" role="group" aria-label="필터">
              <label className={`srch${q.trim() ? ' f' : ''}`}>
                <Icon name="search" size={18} />
                <input value={q} placeholder="접수번호 · Jira 번호 · 제목 · 문의자 · 담당자로 검색" aria-label="전체 문의 검색" autoComplete="off" onChange={(e) => reset(setQ)(e.target.value)} />
                {q && (
                  <button type="button" className="x" aria-label="검색어 지우기" onClick={() => reset(setQ)('')}>
                    ✕
                  </button>
                )}
              </label>
              <span className="small muted" role="status" aria-live="polite">
                {data?.totalCount ?? 0}건
              </span>
              <FilterPill label="분류" value={cat} options={Object.keys(CATEGORIES).map((c) => ({ value: c, label: CATEGORIES[c as CategoryCode].name }))} onChange={reset(setCat)} />
              <FilterPill label="긴급도" value={pri} options={[{ value: 'P12', label: 'P1·P2 · 긴급·높음' }, ...URGENCIES.map((p) => ({ value: p, label: `${p} · ${URGENCY_LABEL[p]}` }))]} onChange={reset(setPri)} />
              <FilterPill label="팀" value={team} options={groups.map((g) => ({ value: g.name, label: g.name }))} onChange={reset(setTeam)} />
              <FilterPill label="담당자" value={staff} options={staffList.map((s) => ({ value: s.name, label: `${s.name} · ${s.group}` }))} onChange={reset(setStaff)} />
              {perChip}
              {alarm && (
                <span className="d2p act">
                  <small>알림</small>
                  <span>확인할 Jira 알림</span>
                  <button type="button" className="x" aria-label="Jira 알림 필터 해제" onClick={() => reset(setAlarm)(false)}>
                    ✕
                  </button>
                </span>
              )}
              {unres && (
                <span className="d2p act">
                  <small>상태</small>
                  <span>해결 완료 제외</span>
                  <button type="button" className="x" aria-label="해결 완료 제외 조건 해제" onClick={() => reset(setUnres)(false)}>
                    ✕
                  </button>
                </span>
              )}
              {active > 0 && (
                <button type="button" className="d2clr" onClick={clear}>
                  ✕ 필터 해제
                </button>
              )}
            </div>

            <div className="panel" style={{ padding: '6px 10px' }} aria-live="polite">
              {error ? (
                <div className="alert err" role="alert">
                  <Icon name="alert" />
                  <div>
                    {error}{' '}
                    <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                      다시 시도
                    </button>
                  </div>
                </div>
              ) : data === null ? (
                <div className="empty" role="status">
                  불러오는 중이에요…
                </div>
              ) : items.length ? (
                <>
                  <div className="tw">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <SortTh col="pri" label="긴급도" center sort={sort} onSort={onSort} />
                          <SortTh col="receipt" label="접수번호 / 티켓" sort={sort} onSort={onSort} />
                          <SortTh col="title" label="제목" sort={sort} onSort={onSort} />
                          <SortTh col="status" label="상태" center sort={sort} onSort={onSort} />
                          <SortTh col="when" label="접수일 / 경과" sort={sort} onSort={onSort} />
                          <SortTh col="cat" label="분류" center sort={sort} onSort={onSort} />
                          <SortTh col="assignee" label="담당" sort={sort} onSort={onSort} />
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((t) => (
                          <tr key={t.id} className={openId === t.id ? 'cur' : ''}>
                            <td className="c">
                              <UrgencyChip u={t.urgency} />
                            </td>
                            <td className="mono small">
                              {t.receiptNo}
                              <br />
                              {t.jiraKey ?? '-'}
                            </td>
                            <td>
                              <button type="button" className="lk" onClick={() => open(t.id)}>
                                {t.summary}
                              </button>
                              {t.jiraMention && <span className="newd" role="img" aria-label="새 답변" />}
                              <small>{t.requester.name}</small>
                            </td>
                            <td className="c">{t.workStatus ? <StaffStatus t={t} /> : <PreStatus t={t} />}</td>
                            <td className="small">
                              {formatDateTime(t.createdAt)} 접수
                              <br />
                              <b>{formatElapsed(t.createdAt)}</b> 경과
                            </td>
                            <td className="c">{t.category ? <span className={`tag c-${t.category.code}`}>{CATEGORIES[t.category.code as CategoryCode].name}</span> : <span className="muted small">미분류</span>}</td>
                            <td>
                              {t.assignee?.name ?? '배정 전'}
                              <small>{t.group?.name ?? ''}</small>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={data.page} size={data.size} total={data.totalCount} onPage={setPage} />
                </>
              ) : (
                <div className="empty">조건에 맞는 문의가 없어요.</div>
              )}
            </div>
          </div>
        </div>
      </main>
      {openId !== null && <TicketDetailPanel key={openId} id={openId} tick={tick} slide={slide} onSlideEnd={() => setSlide(false)} onClose={() => navigate('/tickets')} />}
    </>
  )
}
