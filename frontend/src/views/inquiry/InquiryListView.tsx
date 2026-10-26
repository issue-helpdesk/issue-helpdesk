/**
 * 문의 내역 화면 (/list). 내 문의를 상태별로 보고, 검색·분류·기간으로 좁히고, 열 머리를 눌러 정렬한다.
 * (design/ITssue-Prototype.html 의 문의 내역과 같은 구성)
 *
 * 조건은 API 의 문의 목록 조건(IQ-02)으로 만들어 listInquiries 에 보낸다. 모의 모드에서는 같은 조건으로 걸러 주고,
 * 서버가 생기면 서버가 걸러 준다. 종료된 문의도 눌러서 열면 "대화 이어가기"로 다시 이어 갈 수 있다.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { groupOf, LIST_GROUPS, listInquiries, type InquiryListQuery, type ListGroup, type Page } from '../../api/inquiries'
import type { InquirySummary } from '../../api/types'
import titleHist from '../../assets/mascot/title-hist.webp'
import { formatRelative } from '../../core/format'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { Pager } from '../../ui/Pager'
import { StateBadge } from '../../ui/StateBadge'
import { STATE_TONE } from '../../ui/stateStyle'
import { Topbar } from '../../ui/Topbar'

const PAGE_SIZE = 20
const PERIODS = [
  { value: '7', label: '최근 7일' },
  { value: '30', label: '최근 30일' },
]
/** 정렬 열 → API sort 기준 (createdAt·updatedAt 외에는 임시 값, api/inquiries.ts 참고) */
const SORT_KEY = { title: 'title', category: 'category', status: 'displayStatus', when: 'updatedAt' } as const
type SortCol = keyof typeof SORT_KEY

const pad = (n: number) => String(n).padStart(2, '0')
/** n일 전 날짜를 YYYY-MM-DD 로 (로컬 날짜) */
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 검색어와 겹치는 부분을 강조한다 */
function Hl({ text, q }: { text: string; q: string }) {
  const needle = q.trim().toLowerCase()
  const i = needle ? text.toLowerCase().indexOf(needle) : -1
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark className="hl">{text.slice(i, i + needle.length)}</mark>
      {text.slice(i + needle.length)}
    </>
  )
}

/** 정렬할 수 있는 열 머리 */
function SortTh({ col, label, sort, onSort }: { col: SortCol; label: string; sort: { col: SortCol; dir: 'asc' | 'desc' }; onSort: (c: SortCol) => void }) {
  const on = sort.col === col
  return (
    <th aria-sort={on ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className={`d2th${on ? (sort.dir === 'desc' ? ' dn' : ' up') : ''}`} onClick={() => onSort(col)}>
        {label}
        <i>
          <b />
          <b />
        </i>
      </button>
    </th>
  )
}

export function InquiryListView() {
  const { user } = useAuth()
  const employeeNo = user?.employeeNo
  const navigate = useNavigate()
  const focusSearch = (useLocation().state as { focusSearch?: boolean } | null)?.focusSearch
  const searchRef = useRef<HTMLInputElement>(null)

  const [group, setGroup] = useState<ListGroup | ''>('')
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [period, setPeriod] = useState('')
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' }>({ col: 'when', dir: 'desc' })
  const [page, setPage] = useState(1)
  // 불러온 쪽 (null = 불러오는 중), 분류별 건수 (조건과 상관없이 전체 기준)
  const [data, setData] = useState<Page<InquirySummary> | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  // 사이드바 "최근 문의" 검색 아이콘으로 들어오면 검색 칸에 초점을 둔다
  useEffect(() => {
    if (focusSearch) searchRef.current?.focus()
  }, [focusSearch])

  const query: InquiryListQuery = useMemo(
    () => ({
      page,
      size: PAGE_SIZE,
      sort: `${SORT_KEY[sort.col]},${sort.dir}`,
      displayStatus: group ? LIST_GROUPS.find((g) => g.key === group)!.statuses : undefined,
      categoryCode: cat ? [cat as CategoryCode] : undefined,
      createdFrom: period ? daysAgo(Number(period)) : undefined,
      q: q.trim() || undefined,
    }),
    [page, sort, group, cat, period, q],
  )

  useEffect(() => {
    if (!employeeNo) return
    let alive = true
    listInquiries(employeeNo, query).then((r) => {
      if (!alive) return
      if (r.ok) {
        setData(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [employeeNo, query, reload])

  // 분류별 건수: 조건 없이 전체를 한 번 읽어 센다 (서버가 생기면 분류마다 totalCount 로 읽는다)
  useEffect(() => {
    if (!employeeNo) return
    let alive = true
    listInquiries(employeeNo, { size: 100 }).then((r) => {
      if (!alive || !r.ok) return
      const c: Record<string, number> = { all: r.data.totalCount }
      for (const it of r.data.items) {
        const g = groupOf(it.displayStatus)
        c[g] = (c[g] ?? 0) + 1
      }
      setCounts(c)
    })
    return () => {
      alive = false
    }
  }, [employeeNo, reload])

  const cond = !!(q.trim() || cat || period || group)
  /** 조건을 바꾸면 첫 쪽으로 돌아간다 */
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage(1)
  }
  const clear = () => {
    setGroup('')
    setQ('')
    setCat('')
    setPeriod('')
    setPage(1)
  }
  const onSort = (col: SortCol) => {
    setSort((s) => (s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: col === 'when' ? 'desc' : 'asc' }))
    setPage(1)
  }

  const items = data?.items ?? []

  return (
    <main className="main">
      <Topbar title="문의 내역" sub="내 문의의 진행 상태" lead={<img className="tti" src={titleHist} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div>
            <div className="eyebrow">MY INQUIRIES</div>
            <h1>내 문의를 한눈에 확인해요</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              진행 중인 문의와 해결된 문의를 상태별로 확인하세요. 종료된 문의도 다시 열어 이어갈 수 있어요.
            </p>
          </div>

          <div className="d2seg" role="group" aria-label="상태">
            {[{ key: '' as const, label: '전체' }, ...LIST_GROUPS].map((g) => (
              <button key={g.key || 'all'} type="button" className={group === g.key ? 'on' : ''} aria-pressed={group === g.key} onClick={() => reset(setGroup)(g.key as ListGroup | '')}>
                {g.label} <em>{counts[g.key || 'all'] ?? 0}</em>
              </button>
            ))}
          </div>

          <div className="d2f">
            <label className={`srch${q.trim() ? ' f' : ''}`}>
              <Icon name="search" size={18} />
              <input ref={searchRef} value={q} placeholder="제목·접수번호·가이드명으로 검색" aria-label="내 문의 검색" autoComplete="off" onChange={(e) => reset(setQ)(e.target.value)} />
              {q && (
                <button type="button" className="x" aria-label="검색어 지우기" onClick={() => reset(setQ)('')}>
                  ✕
                </button>
              )}
            </label>
            <FilterPill label="상태" value={group} options={LIST_GROUPS.map((g) => ({ value: g.key, label: `${g.label} · ${counts[g.key] ?? 0}` }))} onChange={(v) => reset(setGroup)(v as ListGroup | '')} />
            <FilterPill label="분류" value={cat} options={(Object.keys(CATEGORIES) as CategoryCode[]).map((c) => ({ value: c, label: CATEGORIES[c].name }))} onChange={reset(setCat)} />
            <FilterPill label="기간" value={period} options={PERIODS} onChange={reset(setPeriod)} />
            {cond && (
              <button type="button" className="d2clr" onClick={clear}>
                ✕ 조건 해제
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
                        <SortTh col="title" label="문의" sort={sort} onSort={onSort} />
                        <SortTh col="category" label="분류" sort={sort} onSort={onSort} />
                        <SortTh col="status" label="상태" sort={sort} onSort={onSort} />
                        <th>접수번호</th>
                        <SortTh col="when" label="최근 활동" sort={sort} onSort={onSort} />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((i) => (
                        <tr key={i.id}>
                          <td>
                            <button type="button" className="lk" style={i.unread ? { fontWeight: 700 } : undefined} onClick={() => navigate(`/chat/${i.id}`)}>
                              <Hl text={i.title} q={q} />
                            </button>
                            {i.unread > 0 && (
                              <span className="nr">
                                <i />
                                새 답변 {i.unread}
                              </span>
                            )}
                          </td>
                          <td>{i.categoryCode ? <span className={`tag c-${i.categoryCode}`}>{CATEGORIES[i.categoryCode].name}</span> : <span className="muted small">분류 전</span>}</td>
                          <td>
                            <StateBadge tone={STATE_TONE[i.stateKind]} label={i.stateLabel} />
                          </td>
                          <td className="mono small">
                            {i.receiptNo ? (
                              <>
                                <Hl text={i.receiptNo} q={q} />
                                {i.jiraKey && (
                                  <>
                                    {' / '}
                                    <Hl text={i.jiraKey} q={q} />
                                  </>
                                )}
                              </>
                            ) : (
                              '-'
                            )}
                          </td>
                          <td className="muted small">{formatRelative(i.updatedAt)}</td>
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
  )
}
