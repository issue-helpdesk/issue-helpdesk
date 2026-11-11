/**
 * 처리할 문의 화면 (/queue, /queue/:ticketId). 담당자가 맡은 접수를 탭·검색·필터로 좁혀 보고, 열면 오른쪽에 상세가 붙는다.
 * (design/ITssue-Prototype.html 의 처리할 문의와 같은 구성)
 *
 * 목록은 TK-05(view=ASSIGNED, assigneeId=나), 상세는 TK-06 이다. 서버가 걸러 주므로 화면은 조건만 보낸다.
 * 정렬은 긴급도 → ITSM 알림이 온 건 → 오래된 건 순이 기본이다. 상태 변경(처리 시작·처리 결과)은 제안이며 상세에서 한다.
 */
import titleInq from '../../assets/mascot/title-inq.webp'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CATEGORIES, STAFF_STATUS, URGENCY_LABEL } from '../../api/catalog'
import type { CategoryCode, Urgency, WorkStatus } from '../../api/chatTypes'
import { listTickets, watchTickets } from '../../api/tickets'
import type { TicketListQuery, TicketSummary } from '../../api/ticketTypes'
import type { Page } from '../../api/inquiries'
import { USE_MOCK_TICKET } from '../../core/config'
import { formatDateTime, formatElapsed } from '../../core/format'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { Pager } from '../../ui/Pager'
import { SortTh } from '../../ui/SortTh'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { TicketDetailPanel } from './TicketDetailPanel'

const PAGE_SIZE = 20

type Tab = 'all' | 'rdy' | 'open' | 'fin' | 'cls'
const ALL_TAB = { key: 'all' as Tab, label: '전체 상태', statuses: ['RDY', 'WIP', 'FIN', 'CLS'] as WorkStatus[] }
const TABS: { key: Tab; label: string; statuses: WorkStatus[] }[] = [
  { key: 'rdy', label: '처리 대기', statuses: ['RDY'] },
  { key: 'open', label: '진행 중', statuses: ['RDY', 'WIP'] },
  { key: 'fin', label: '해결 확인 대기', statuses: ['FIN'] },
  { key: 'cls', label: '해결 완료', statuses: ['CLS'] },
]

const URGENCIES: Urgency[] = ['P1', 'P2', 'P3', 'P4']
/** 접수 기간 알약: 오늘 / 최근 30일 / 최근 1년 (며칠 전부터) */
const PERIODS = [
  { value: 'd', label: '오늘', days: 0 },
  { value: 'm', label: '최근 30일', days: 30 },
  { value: 'y', label: '최근 1년', days: 365 },
]

/** 정렬 열 → API sort 기준 (urgency·createdAt·workStatus 외에는 프로토타입용 임시 값, api/tickets.ts 참고) */
const SORT_KEY = { pri: 'urgency', receipt: 'receiptNo', title: 'summary', status: 'workStatus', when: 'createdAt', cat: 'category' } as const
type SortCol = keyof typeof SORT_KEY

const pad = (n: number) => String(n).padStart(2, '0')
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 긴급도 칩 (높음) */
export const UrgencyChip = ({ u }: { u: Urgency | null }) => (u ? <span className={`pri-${u.toLowerCase()}`}>{URGENCY_LABEL[u]}</span> : <span className="muted small">-</span>)

/** 담당자 화면의 상태 배지 (상태 변경을 ITSM에 요청한 중에는 안내를 함께 보인다) */
export function StaffStatus({ t }: { t: Pick<TicketSummary, 'workStatus' | 'transitionStatus' | 'requestedWorkStatus' | 'needsAdmin'> }) {
  if (!t.workStatus) return <StateBadge tone="recv" label="접수 완료" />
  const s = STAFF_STATUS[t.workStatus]
  if (t.transitionStatus === 'PENDING') return <StateBadge tone={s.tone} label={s.label} sub="ITSM 반영 확인 중" block />
  // 해결이 끝난 접수는 연동·배정 확인 대상이 아니다
  if ((t.needsAdmin || t.transitionStatus === 'NEEDS_ADMIN') && t.workStatus !== 'CLS') return <StateBadge tone="urg" label="확인 필요" />
  return <StateBadge tone={s.tone} label={s.label} />
}

export function QueueView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { ticketId } = useParams()
  const openId = ticketId ? Number(ticketId) : null
  // 패널이 닫혀 있다가 열릴 때만 오른쪽에서 밀려 들어온다 (열린 채 다른 접수로 바꿀 때는 움직이지 않는다)
  const [slide, setSlide] = useState(false)
  const [prevOpen, setPrevOpen] = useState(false)
  if (prevOpen !== (openId !== null)) {
    setPrevOpen(openId !== null)
    setSlide(openId !== null)
  }

  // 대시보드에서 오면 주소의 값으로 시작한다 (?tab=open&sub=RDY, ?pri=P1, ?per=m,)
  const [params] = useSearchParams()
  const fromUrl = <T extends string>(k: string, ok: readonly T[], d: T): T => (ok.includes(params.get(k) as T) ? (params.get(k) as T) : d)
  const [tab, setTab] = useState<Tab>(() => fromUrl('tab', ['all', 'rdy', 'open', 'fin', 'cls'] as const, 'all'))
  const [sub, setSub] = useState<'' | 'RDY' | 'WIP'>(() => fromUrl('sub', ['', 'RDY', 'WIP'] as const, ''))
  const [q, setQ] = useState('')
  const [pri, setPri] = useState<string>(() => fromUrl('pri', ['', 'P1', 'P2', 'P3', 'P4'] as const, ''))
  const [per, setPer] = useState<string>(() => fromUrl('per', ['', 'd', 'm', 'y'] as const, ''))
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' } | null>(null)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<TicketSummary> | null>(null)
  // 처리 상태별 건수 (검색어·긴급도·기간을 따라간다). null = 아직 못 읽음
  const [statusCounts, setStatusCounts] = useState<Partial<Record<WorkStatus, number>> | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const [reload, setReload] = useState(0)

  // 접수가 바뀌면(새 접수, 상태 변경) 목록과 상세를 다시 읽는다
  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])

  const query: TicketListQuery = useMemo(() => {
    const t = tab === 'all' ? ALL_TAB : TABS.find((x) => x.key === tab)!
    const days = PERIODS.find((p) => p.value === per)?.days
    return {
      view: 'ASSIGNED',
      assigneeId: user?.id,
      page,
      size: PAGE_SIZE,
      // 정렬을 고르기 전에는 긴급도 높은 순 (열 머리는 강조하지 않는다)
      sort: sort ? `${SORT_KEY[sort.col]},${sort.dir}` : 'urgency,asc',
      workStatus: tab === 'open' && sub ? [sub] : t.statuses,
      urgency: pri ? [pri as Urgency] : undefined,
      createdFrom: days === undefined ? undefined : daysAgo(days),
      q: q.trim() || undefined,
    }
  }, [user?.id, tab, sub, page, sort, pri, per, q])

  useEffect(() => {
    if (!user) return
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
  }, [user, query, tick, reload])

  // 탭별 건수: 검색어·긴급도·기간을 따라간다 (상태 탭 자체만 빼고 센다). 상태 조건 없이 1건만 요청해 응답의 상태별 건수(statusCounts)를 읽고, 검색어를 칠 때마다 보내지 않도록 잠깐 기다린다
  useEffect(() => {
    if (!user) return
    let alive = true
    const days = PERIODS.find((p) => p.value === per)?.days
    const timer = setTimeout(() => {
      // 상태 조건 없이 1건만 요청하면 응답의 statusCounts 가 상태별 건수를 준다 (R-46)
      listTickets(user, { view: 'ASSIGNED', assigneeId: user.id, size: 1, urgency: pri ? [pri as Urgency] : undefined, createdFrom: days === undefined ? undefined : daysAgo(days), q: q.trim() || undefined }).then((r) => {
        if (!alive || !r.ok) return
        const sc = r.data.statusCounts ?? {}
        setStatusCounts({ RDY: sc.RDY ?? 0, WIP: sc.WIP ?? 0, FIN: sc.FIN ?? 0, CLS: sc.CLS ?? 0 })
      })
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [user, tick, q, pri, per])

  if (!user) return null

  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage(1)
  }
  const count = (statuses: WorkStatus[]) => statuses.reduce((n, s) => n + (statusCounts?.[s] ?? 0), 0)
  const subCount = (s: 'RDY' | 'WIP') => statusCounts?.[s] ?? 0
  const cond = !!(q.trim() || pri || per)
  // 전체 상태 탭을 맨 앞에 두고, 각 탭에 내가 맡은 건수를 보인다
  const tabs = [ALL_TAB, ...TABS]
  const onSort = (col: SortCol) => {
    setSort((s) => (s && s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: col === 'when' ? 'desc' : 'asc' }))
    setPage(1)
  }
  const open = (id: number) => navigate(`/queue/${id}`)
  const items = data?.items ?? []

  return (
    <>
      <main className="main">
        <Topbar title="처리할 문의" sub={`${user.departmentName} · ${user.name} 담당자`} lead={<img className="tti" src={titleInq} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">MY QUEUE</div>
              <h1>처리할 문의를 확인해요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                문의 상태를 변경하고 처리 결과를 등록해요. 처리가 끝나면 문의자가 해결 여부를 확인해요.
              </p>
            </div>


            <div className="d2seg" role="tablist" aria-label="처리 상태">
              {tabs.map((t) => (
                <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={tab === t.key ? 'on' : ''} onClick={() => { reset(setTab)(t.key); setSub('') }}>
                  {t.label}
                  {statusCounts && <em>{count(t.statuses)}</em>}
                </button>
              ))}
            </div>

            <div className="d2f" role="group" aria-label="필터">
              <label className={`srch${q.trim() ? ' f' : ''}`}>
                <Icon name="search" size={18} />
                <input value={q} placeholder="접수번호 · ITSM 번호 · 제목 · 문의자로 검색" aria-label="처리할 문의 검색" autoComplete="off" onChange={(e) => reset(setQ)(e.target.value)} />
                {q && (
                  <button type="button" className="x" aria-label="검색어 지우기" onClick={() => reset(setQ)('')}>
                    ✕
                  </button>
                )}
              </label>
              <span className="small muted" role="status" aria-live="polite">
                {data?.totalCount ?? 0}건
              </span>
              <FilterPill label="긴급도" value={pri} options={URGENCIES.map((p) => ({ value: p, label: URGENCY_LABEL[p] }))} onChange={reset(setPri)} />
              <FilterPill label="접수 기간" value={per} options={PERIODS.map((p) => ({ value: p.value, label: p.label }))} onChange={reset(setPer)} />
            </div>

            {tab === 'open' && (
              <div className="subc" role="group" aria-label="진행 중 상태 구분">
                {([['', '전체 진행 중', count(['RDY', 'WIP'])], ['RDY', '처리 대기', subCount('RDY')], ['WIP', '처리 중', subCount('WIP')]] as const).map(([k, label, n]) => (
                  <button key={k || 'all'} type="button" className={`chip${sub === k ? ' on' : ''}`} aria-pressed={sub === k} onClick={() => reset(setSub)(k)}>
                    {label} <em>{n}</em>
                  </button>
                ))}
              </div>
            )}

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
                    <table className="tbl fx fx2">
                      <colgroup>
                        <col style={{ width: '9%' }} />
                        <col style={{ width: '15%' }} />
                        <col style={{ width: '31%' }} />
                        <col style={{ width: '14%' }} />
                        <col style={{ width: '14%' }} />
                        <col style={{ width: '17%' }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <SortTh col="pri" label="긴급도" center sort={sort} onSort={onSort} />
                          <SortTh plain={!USE_MOCK_TICKET} col="receipt" label="접수번호 / 티켓" sort={sort} onSort={onSort} />
                          <SortTh plain={!USE_MOCK_TICKET} col="title" label="제목" sort={sort} onSort={onSort} />
                          <SortTh col="status" label="상태" center sort={sort} onSort={onSort} />
                          <SortTh col="when" label="접수일 / 경과" sort={sort} onSort={onSort} />
                          <SortTh plain={!USE_MOCK_TICKET} col="cat" label="분류" center sort={sort} onSort={onSort} />
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
                              <small>{t.requester.name}</small>
                            </td>
                            <td className="c">
                              <StaffStatus t={t} />
                            </td>
                            <td className="small">
                              {formatDateTime(t.createdAt)} 접수
                              <br />
                              <b>{formatElapsed(t.createdAt)}</b> 경과
                            </td>
                            <td className="c">{t.category ? <span className={`tag c-${t.category.code}`}>{CATEGORIES[t.category.code as CategoryCode].name}</span> : <span className="muted small">미분류</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={data.page} size={data.size} total={data.totalCount} onPage={setPage} />
                </>
              ) : (
                <div className="empty">{cond ? '조건에 맞는 문의가 없어요.' : '이 상태의 문의가 없어요.'}</div>
              )}
            </div>
          </div>
        </div>
      </main>
      {openId !== null && <TicketDetailPanel key={openId} id={openId} tick={tick} slide={slide} onSlideEnd={() => setSlide(false)} onClose={() => navigate('/queue')} />}
    </>
  )
}
