/**
 * 가이드 관리 (관리자, /guides). (design/ITssue-Prototype.html viewGuides)
 * AI 답변의 근거가 되는 문서를 분류별로 보고, 버전마다 열람 범위·외부 AI 전송 정책·현행 여부를 관리한다.
 * 현행 버전 중 검색 준비가 끝난 것만 AI 답변에 쓰인다. 해결 사례를 묶어 가이드 초안으로 만드는 탭은 제안이다.
 * 문서·버전은 문서 API(DC-01·02·06·07·09), 해결 사례 묶음은 접수 목록(TK-05)을 읽어 화면에서 만든다.
 * 서버에 없는 버전 메모·정책 변경 사유·가이드 초안 만들기는 서버 모드에서 안내만 한다. (api/guides.ts, 요청 R-21~23)
 */
import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import {
  GUIDE_SCOPES,
  GUIDE_TXS,
  TX_RANK,
  createGuideDraft,
  guideLabel,
  listGuideVersions,
  listGuides,
  setGuideCurrent,
  setGuideNote,
  setGuideTransfer,
  uploadGuide,
  watchGuides,
  type Guide,
  type GuideScope,
  type GuideTx,
  type GuideVersion,
} from '../../api/guides'
import { listTickets } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatElapsed } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { StaffStatus } from '../staff/QueueView'

const TX_CLS: Record<GuideTx, string> = { 허용: 'ok', '마스킹 후 허용': 'warn', 금지: 'urg' }
/** 해결 사례 분석 단위: 일간(최근 이틀) · 주간(최근 7일) */
const GCP = { d: { lb: '일간', sub: '최근 이틀 해결된 티켓', max: 1 }, w: { lb: '주간', sub: '최근 7일 해결된 티켓', max: 6 } } as const
type Per = keyof typeof GCP
type Tab = 'list' | 'case'

interface Cluster {
  title: string
  cat: CategoryCode
  list: TicketSummary[]
  n: number
  sim: number
  exist: Guide | null
}

/** 같은 분류·같은 제목을 같은 주제로 본다(시연 기준). 해결 티켓의 5% 이상(최소 2건)인 묶음만 남긴다 */
function clustersOf(tickets: TicketSummary[], guides: Guide[], per: Per) {
  const day = 86_400_000
  const win = tickets.filter((t) => t.workStatus === 'CLS' && t.category && Date.now() - Date.parse(t.createdAt) < (GCP[per].max + 1) * day)
  const thr = Math.max(2, Math.round(win.length * 0.05))
  const g: Record<string, TicketSummary[]> = {}
  win.forEach((t) => {
    const k = `${t.category!.code}|${t.summary}`
    ;(g[k] = g[k] ?? []).push(t)
  })
  const cl: Cluster[] = Object.values(g)
    .map((l) => {
      const t0 = l[0]
      const cat = t0.category!.code
      const h = [...t0.summary].reduce((a, ch) => a + ch.charCodeAt(0), 0)
      const tk = t0.summary.replace(/[·()/]/g, ' ').split(/\s+/).filter((w) => w.length >= 2)
      const exist = guides.find((x) => x.cat === cat && x.current && tk.some((w) => x.title.includes(w))) ?? null
      return { title: t0.summary, cat, list: l, n: l.length, sim: 84 + (h % 13), exist }
    })
    .filter((c) => c.n >= thr)
    .sort((a, b) => b.n - a.n || a.title.localeCompare(b.title))
  return { win, cl, inCl: cl.reduce((a, c) => a + c.n, 0) }
}

export function GuidesView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [guides, setGuides] = useState<Guide[] | null>(null)
  const [vers, setVers] = useState<Record<number, GuideVersion[]>>({})
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('list')
  const [catOpen, setCatOpen] = useState<Record<string, boolean>>({})
  const [openId, setOpenId] = useState<number | null>(null)
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null)
  const [per, setPer] = useState<Per>('d')
  const [clOpen, setClOpen] = useState<number | null>(null)
  const [tick, setTick] = useState(0)
  const [toast, setToast] = useState('')
  const [dlg, setDlg] = useState<null | { kind: 'upload' } | { kind: 'tx'; g: Guide; v: GuideVersion; to: GuideTx } | { kind: 'note'; g: Guide; v: GuideVersion } | { kind: 'draft'; c: Cluster; i: number }>(null)
  const admin = user?.serviceRole === 'ADMIN'

  const say = useCallback((m: string) => {
    setToast(m)
    setTimeout(() => setToast(''), 3000)
  }, [])

  useEffect(() => watchGuides(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    listGuides(user).then((r) => {
      if (!alive) return
      if (r.ok) {
        setGuides(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, tick])

  // 다른 화면에서 ?doc=문서번호 로 오면 그 가이드를 펼친다 (AI 운영의 "해당 가이드로 이동")
  const wantDoc = params.get('doc')
  const [shownDoc, setShownDoc] = useState<string | null>(null)
  if (wantDoc && guides && shownDoc !== wantDoc) {
    const g = guides.find((x) => x.docCode === wantDoc)
    setShownDoc(wantDoc)
    if (g) {
      setCatOpen((m) => ({ ...m, [g.cat]: true }))
      setOpenId(g.id)
    }
  }

  // 열린 가이드의 버전을 읽는다 (서버는 열 때 읽고, 바뀌면 다시 읽는다)
  useEffect(() => {
    if (!user || !admin || openId === null) return
    let alive = true
    listGuideVersions(user, openId).then((r) => {
      if (alive && r.ok) setVers((m) => ({ ...m, [openId]: r.data }))
    })
    return () => {
      alive = false
    }
  }, [user, admin, openId, tick])

  // 검색 준비(적재)가 진행 중인 버전이 있으면 끝날 때까지 몇 초마다 다시 읽는다
  useEffect(() => {
    if (!Object.values(vers).some((l) => l.some((x) => x.ready === '준비 중'))) return
    const t = setInterval(() => setTick((n) => n + 1), 4000)
    return () => clearInterval(t)
  }, [vers])

  // 해결 사례 묶음: 해결 완료(CLS) 접수를 읽는다 (탭 건수에도 쓴다)
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    listTickets(user, { view: 'ALL', workStatus: ['CLS'], size: 100, sort: 'createdAt,desc' }).then((r) => {
      if (alive && r.ok) setTickets(r.data.items)
    })
    return () => {
      alive = false
    }
  }, [user, admin])

  const gc = useMemo(() => clustersOf(tickets ?? [], guides ?? [], per), [tickets, guides, per])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const cats = (Object.keys(CATEGORIES) as CategoryCode[]).filter((c) => guides?.some((g) => g.cat === c))
  const allOpen = cats.length > 0 && cats.every((c) => catOpen[c])
  const reload = () => setTick((n) => n + 1)

  const changeTx = (g: Guide, v: GuideVersion, to: GuideTx) => {
    if (TX_RANK[to] > TX_RANK[v.tx]) return setDlg({ kind: 'tx', g, v, to })
    void applyTx(g, v, to, '')
  }
  const applyTx = async (g: Guide, v: GuideVersion, to: GuideTx, why: string) => {
    const r = await setGuideTransfer(user, g.id, v.id, to, why)
    if (!r.ok) return say(r.error.message)
    say(`외부 전송 정책을 ${to}${to === '금지' ? '로' : '으로'} 바꿨어요.`)
    reload()
  }
  const makeCurrent = async (g: Guide, v: GuideVersion) => {
    const r = await setGuideCurrent(user, g.id, v.id)
    if (!r.ok) return say(r.error.message)
    say(v.state === '만료' ? `${v.version}을(를) 다시 현행으로 되돌렸어요.` : '현행 버전을 바꿨어요.')
    reload()
  }

  const gpanel = (g: Guide) => {
    const open = openId === g.id
    const list = vers[g.id] ?? g.versions
    return (
      <div className="gprow" key={g.id}>
        <button type="button" className="grb" aria-expanded={open} onClick={() => setOpenId(open ? null : g.id)}>
          <span className="grt">
            <b>{guideLabel(g)}</b>
            <div className="small muted">{g.current ? `현행 ${g.current.version}` : '현행 없음'}</div>
          </span>
          <span className="gbs">{g.current?.tx === '금지' ? <StateBadge tone="urg" label="외부 전송 금지" /> : g.current?.tx === '마스킹 후 허용' ? <StateBadge tone="warn" label="마스킹 후 전송" /> : null}</span>
        </button>
        {open && (
          <div className="tw gvt" style={{ marginTop: 12 }}>
            {!list ? (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>버전</th>
                    <th className="c">상태</th>
                    <th className="c">검색 준비</th>
                    <th>열람 범위</th>
                    <th className="c" title="이 가이드의 내용을 외부 AI 모델에 보내 답변 생성에 써도 되는지">
                      외부 AI 전송
                    </th>
                    <th>메모</th>
                    <th>현행 관리</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((v) => (
                    <tr key={v.id} className={v.state === '현행' ? 'vcur' : v.state === '만료' ? 'vold' : undefined}>
                      <td>
                        <b>{v.version}</b>
                      </td>
                      <td className="c">
                        <StateBadge tone={v.state === '현행' ? 'ok' : v.state === '초안' ? 'warn' : 'recv'} label={v.state} />
                      </td>
                      <td className="c">
                        <StateBadge tone={v.ready === '준비 완료' ? 'ok' : v.ready === '준비 실패' ? 'urg' : 'warn'} label={v.ready} />
                        {v.error && <div className="small muted">{v.error}</div>}
                      </td>
                      <td>{v.scope}</td>
                      <td className="c">
                        <div className="seg tx" role="group" aria-label={`${v.version} 외부 AI 전송`}>
                          {GUIDE_TXS.slice()
                            .reverse()
                            .map((k) => (
                              <button key={k} type="button" className={v.tx === k ? `on ${TX_CLS[k]}` : ''} aria-pressed={v.tx === k} title={v.tx === k ? undefined : `${k}(으)로 바꾸기`} onClick={() => v.tx !== k && changeTx(g, v, k)}>
                                {k}
                              </button>
                            ))}
                        </div>
                      </td>
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                          <span>{v.note || '-'}</span>
                          <button type="button" className="btn ghost sm" aria-label={`${v.version} 메모 수정`} onClick={() => setDlg({ kind: 'note', g, v })}>
                            수정
                          </button>
                        </div>
                      </td>
                      <td>
                        {v.state !== '현행' && (
                          <button type="button" className="btn ghost sm" disabled={v.ready !== '준비 완료'} title={v.ready !== '준비 완료' ? '검색 준비가 끝나야 현행으로 바꿀 수 있어요' : v.state === '만료' ? '이전 버전을 다시 현행으로 되돌려요' : undefined} onClick={() => void makeCurrent(g, v)}>
                            현행 전환
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    )
  }

  const list = guides && (
    <>
      <div className="row" style={{ justifyContent: 'space-between', margin: 0 }}>
        <span className="small muted">
          분류 {cats.length}개 · 가이드 {guides.length}개
        </span>
        <button type="button" className="btn ghost sm" onClick={() => setCatOpen(allOpen ? {} : Object.fromEntries(cats.map((c) => [c, true])))}>
          {allOpen ? '모두 접기' : '모두 펼치기'}
        </button>
      </div>
      <div className="gseclist">
        {cats.map((c) => {
          const gs = guides.filter((g) => g.cat === c)
          const open = !!catOpen[c]
          return (
            <section key={c} className={`gsec${open ? ' open' : ''}`}>
              <button type="button" className="gcb" aria-expanded={open} onClick={() => setCatOpen((m) => ({ ...m, [c]: !m[c] }))}>
                <span className={`tag c-${c} gcbar`} aria-hidden="true" />
                <span className="gcm">
                  <b>{CATEGORIES[c].name}</b>
                  <small>
                    {guideLabel(gs[0])}
                    {gs.length > 1 ? ` 외 ${gs.length - 1}개` : ''}
                  </small>
                </span>
                <span className="gcr">
                  <span className="gcn">{gs.length}개</span>
                  <span className={`gchv${open ? ' on' : ''}`} aria-hidden="true">
                    <Icon name="chevronDown" />
                  </span>
                </span>
              </button>
              {open && <div className="gcp">{gs.map(gpanel)}</div>}
            </section>
          )
        })}
      </div>
    </>
  )

  const N = gc.win.length
  const pct = (n: number) => (N ? Math.round((n / N) * 100) : 0)
  const caseTab = (
    <>
      <div className="alert info">
        <Icon name="file" />
        <div>
          매일 자정에 AI가 해결 완료(CLS)된 티켓의 유사도를 분석해요 <span className="tag gray">제안</span>. 비슷한 주제로 들어온 건을 묶어 보여 주고, 골라서 가이드 초안으로 만들 수 있어요. 초안은 관리자 검토와 검색 준비가 끝난 뒤에만 현행이 될 수 있어요.
        </div>
      </div>
      <div className="row" style={{ justifyContent: 'space-between', margin: '14px 0 10px' }}>
        <div className="seg" role="group" aria-label="분석 단위">
          {(Object.keys(GCP) as Per[]).map((k) => (
            <button key={k} type="button" className={per === k ? 'on' : ''} aria-pressed={per === k} onClick={() => { setPer(k); setClOpen(null) }}>
              {GCP[k].lb}
            </button>
          ))}
        </div>
        <span className="small muted">
          마지막 분석 오늘 00:00 · 다음 분석 내일 00:00 <span className="tag gray">시연 데이터</span>
        </span>
      </div>
      <div className="gk">
        <div className="kpi grp">
          <div className="l">해결 티켓 분석</div>
          <div className="gcells g3">
            <div className="sgc">
              <div className="small muted gl">분석한 해결 티켓</div>
              <div className="v">
                <b>{N}</b>
                <span>건</span>
              </div>
              <div className="small muted">{GCP[per].sub}</div>
            </div>
            <div className="sgc">
              <div className="small muted gl">유사 주제 묶음</div>
              <div className="v">
                <b>{gc.cl.length}</b>
                <span>개</span>
              </div>
              <div className="small muted">해결 티켓의 5% 이상(최소 2건)이 비슷한 주제</div>
            </div>
            <div className="sgc">
              <div className="small muted gl">묶음에 들어간 티켓</div>
              <div className="v">
                <b>{gc.inCl}</b>
                <span>건</span>
              </div>
              <div className="small muted">
                {pct(gc.inCl)}% · 해결 {N}건 중
              </div>
            </div>
          </div>
        </div>
        <div className="kpi grp">
          <div className="l">가이드 후보</div>
          <div className="gcells g2">
            <div className="sgc">
              <div className="small muted gl">새 가이드 후보</div>
              <div className="v">
                <b>{gc.cl.filter((c) => !c.exist).length}</b>
                <span>개</span>
              </div>
              <div className="small muted">현행 가이드가 다루지 않는 주제</div>
            </div>
            <div className="sgc">
              <div className="small muted gl">기존 가이드 보강 후보</div>
              <div className="v">
                <b>{gc.cl.filter((c) => c.exist).length}</b>
                <span>개</span>
              </div>
              <div className="small muted">사례가 더 쌓인 주제</div>
            </div>
          </div>
        </div>
      </div>
      {gc.cl.length ? (
        <>
          <div className="gcs">
            {gc.cl.slice(0, 8).map((c, i) => {
              const open = clOpen === i
              return (
                <section key={`${c.cat}|${c.title}`} className="panel gc" aria-label={c.title}>
                  <div className="gc-h">
                    <span className={`tag c-${c.cat}`}>{CATEGORIES[c.cat].name}</span>
                    <b>{c.title}</b>
                    {c.exist ? <StateBadge tone="asg" label="기존 가이드 보강" /> : <StateBadge tone="need" label="새 가이드" />}
                    <span className="gc-n">
                      <b>{c.n}건</b> · {pct(c.n)}%
                    </span>
                  </div>
                  <div className="gc-bar" role="img" aria-label={`해결 ${N}건 중 ${c.n}건 (${pct(c.n)}%)`}>
                    <i style={{ width: `${Math.max(3, pct(c.n))}%` }} />
                  </div>
                  <p className="small muted" style={{ margin: '6px 0 0' }}>
                    묶인 티켓끼리 평균 유사도 {c.sim}% · {c.exist ? `보강할 가이드: ${guideLabel(c.exist)}` : '맞는 기존 가이드가 없어요'}
                  </p>
                  <div className="gc-acts">
                    {c.exist && (
                      <button
                        type="button"
                        className="btn ghost sm"
                        onClick={() => {
                          setTab('list')
                          setCatOpen((m) => ({ ...m, [c.exist!.cat]: true }))
                          setOpenId(c.exist!.id)
                        }}
                      >
                        기존 가이드 보기
                      </button>
                    )}
                    <button type="button" className="btn ghost sm" aria-expanded={open} onClick={() => setClOpen(open ? null : i)}>
                      포함된 티켓 {c.n}건 {open ? '접기' : '보기'}
                    </button>
                    <button type="button" className="btn pri sm" onClick={() => setDlg({ kind: 'draft', c, i })}>
                      {c.exist ? '버전 업데이트 초안' : '신규 가이드 초안'}
                    </button>
                  </div>
                  {open && (
                    <div className="tw gc-tw">
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>접수번호 / 티켓</th>
                            <th>제목</th>
                            <th>상태</th>
                            <th>접수일 / 경과</th>
                            <th>담당</th>
                          </tr>
                        </thead>
                        <tbody>
                          {c.list.slice(0, 10).map((t) => (
                            <tr key={t.id}>
                              <td className="mono small">
                                {t.receiptNo}
                                <br />
                                {t.jiraKey ?? '-'}
                              </td>
                              <td>
                                <button type="button" className="lk" onClick={() => navigate(`/tickets/${t.id}`)}>
                                  {t.summary}
                                </button>
                              </td>
                              <td>
                                <StaffStatus t={t} />
                              </td>
                              <td className="small">
                                <b>{formatElapsed(t.createdAt)}</b> 경과
                              </td>
                              <td>{t.assignee?.name ?? '-'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {c.n > 10 && (
                        <p className="small muted" style={{ margin: '8px 4px 0' }}>
                          나머지 {c.n - 10}건
                        </p>
                      )}
                    </div>
                  )}
                </section>
              )
            })}
          </div>
          {gc.cl.length > 8 && (
            <p className="small muted" style={{ marginTop: 8 }}>
              건수가 많은 상위 8개만 보여요. 전체 {gc.cl.length}개
            </p>
          )}
        </>
      ) : (
        <div className="panel" style={{ marginTop: 14 }}>
          <div className="empty">{tickets === null ? '불러오는 중이에요…' : `${GCP[per].lb} 분석에서 비슷한 주제로 묶인 해결 사례가 아직 없어요.`}</div>
        </div>
      )}
    </>
  )

  return (
    <>
      <main className="main">
        <Topbar title="가이드 관리" sub="AI 답변의 근거가 되는 문서" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page dpage">
            <div className="phead">
              <div className="eyebrow">KNOWLEDGE</div>
              <h1>AI 답변의 근거를 관리해요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                현재 사용 중인 버전 중 검색 준비가 완료된 버전만 AI 답변에 활용돼요.
              </p>
            </div>
            <div>
              <p className="muted">
                <b>외부 AI 전송</b>은 이 가이드 내용을 AI 모델에 보내 답변을 만들어도 되는지에 관한 설정이에요(문서 열람 권한인 열람 범위와는 별개). <b>허용</b>은 그대로 보내고, <b>마스킹 후 허용</b>은 민감정보를 가린 내용만 보내요. <b>금지</b>인 가이드 내용은 외부 AI에 보내지 않아요. 사용할 수 있는 근거가 없으면 담당자 연결을 제안해요. 열람 범위와 전송 정책을 정하지 않으면 관리자 전용·금지로 처리돼요.
              </p>
            </div>
            <div className="tabs">
              <button type="button" className={tab === 'list' ? 'on' : ''} onClick={() => setTab('list')}>
                가이드 목록 <span className="count">{guides?.length ?? 0}</span>
              </button>
              <button type="button" className={tab === 'case' ? 'on' : ''} onClick={() => setTab('case')}>
                해결 사례 → 가이드 초안 <span className="count">{gc.cl.length}</span>
              </button>
              <button type="button" className="btn pri sm fr" onClick={() => setDlg({ kind: 'upload' })}>
                <Icon name="plus" />
                가이드 파일 업로드
              </button>
            </div>

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={reload}>
                    다시 시도
                  </button>
                </div>
              </div>
            )}

            {tab === 'list' ? (
              guides ? (
                list
              ) : (
                <div className="empty" role="status">
                  불러오는 중이에요…
                </div>
              )
            ) : (
              caseTab
            )}
          </div>
        </div>
      </main>
      {dlg?.kind === 'upload' && (
        <UploadDialog
          onClose={() => setDlg(null)}
          onDone={(g) => {
            setDlg(null)
            setTab('list')
            setCatOpen((m) => ({ ...m, [g.cat]: true }))
            setOpenId(g.id)
            say('업로드했어요. 검색 준비 중이에요.')
            reload()
          }}
        />
      )}
      {dlg?.kind === 'tx' && (
        <TxDialog
          g={dlg.g}
          v={dlg.v}
          to={dlg.to}
          onClose={() => setDlg(null)}
          onApply={(why) => {
            const d = dlg
            setDlg(null)
            void applyTx(d.g, d.v, d.to, why)
          }}
        />
      )}
      {dlg?.kind === 'note' && (
        <NoteDialog
          g={dlg.g}
          v={dlg.v}
          onClose={() => setDlg(null)}
          onDone={() => {
            setDlg(null)
            say('메모를 저장했어요.')
            reload()
          }}
        />
      )}
      {dlg?.kind === 'draft' && (
        <DraftDialog
          c={dlg.c}
          per={per}
          onClose={() => setDlg(null)}
          onDone={(g, version, update) => {
            setDlg(null)
            setTab('list')
            setCatOpen((m) => ({ ...m, [g.cat]: true }))
            setOpenId(g.id)
            say(update ? `기존 가이드에 버전 업데이트 초안(${version})을 추가했어요. 검토 후 현행으로 전환하세요.` : '신규 가이드 초안을 만들었어요. 검토 후 현행으로 전환하세요.')
            reload()
          }}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </>
  )
}

function UploadDialog({ onClose, onDone }: { onClose: () => void; onDone: (g: Guide) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [file, setFile] = useState<File | null>(null)
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [cat, setCat] = useState<CategoryCode>('ACC')
  const [scope, setScope] = useState<GuideScope>('관리자 전용')
  const [tx, setTx] = useState<GuideTx>('금지')
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const clr = (k: string) => setErrs((e) => ({ ...e, [k]: '' }))

  const submit = async () => {
    if (!user) return
    const e: Record<string, string> = {}
    if (!file) e.file = '파일을 선택해 주세요.'
    if (!code.trim()) e.code = '문서 번호를 입력해 주세요.'
    if (!title.trim()) e.title = '가이드 제목을 입력해 주세요.'
    setErrs(e)
    if (Object.keys(e).length || !file) return
    setBusy(true)
    const r = await uploadGuide(user, { file, docCode: code, title, cat, scope, tx })
    setBusy(false)
    if (!r.ok) {
      const f = r.error.details?.find((d) => d.field === 'docCode')
      if (f) return setErrs({ code: f.message ?? r.error.message })
      return setErr(r.error.message)
    }
    onDone(r.data)
  }

  const field = (k: string, label: string, body: React.ReactNode) => (
    <div className="field">
      <label htmlFor={`${uid}-${k}`}>{label}</label>
      {body}
      {errs[k] && (
        <div className="ferr" id={`${uid}-${k}-e`} role="alert">
          {errs[k]}
        </div>
      )}
    </div>
  )
  return (
    <Modal title="가이드 파일 업로드" onClose={onClose}>
      <p className="small muted">PDF·DOCX·PPTX·MD·TXT 파일을 올리면 검색 준비(텍스트 추출·색인)를 거쳐 사용할 수 있어요.</p>
      {field('file', '파일', <input id={`${uid}-file`} className={`inp${errs.file ? ' err' : ''}`} type="file" accept=".pdf,.docx,.pptx,.md,.txt" style={{ padding: '9px 12px' }} aria-invalid={!!errs.file} onChange={(e) => { setFile(e.target.files?.[0] ?? null); clr('file') }} />)}
      {field('code', '문서 번호', <input id={`${uid}-code`} className={`inp${errs.code ? ' err' : ''}`} value={code} placeholder="예) IT-NET-004" autoComplete="off" aria-invalid={!!errs.code} onChange={(e) => { setCode(e.target.value); clr('code') }} />)}
      {field('title', '가이드 제목', <input id={`${uid}-title`} className={`inp${errs.title ? ' err' : ''}`} value={title} autoComplete="off" aria-invalid={!!errs.title} onChange={(e) => { setTitle(e.target.value); clr('title') }} />)}
      {field(
        'cat',
        '분류',
        <select id={`${uid}-cat`} className="sel" value={cat} onChange={(e) => setCat(e.target.value as CategoryCode)}>
          {(Object.keys(CATEGORIES) as CategoryCode[]).map((c) => (
            <option key={c} value={c}>
              {CATEGORIES[c].name}
            </option>
          ))}
        </select>,
      )}
      {field(
        'scope',
        '열람 범위',
        <select id={`${uid}-scope`} className="sel" value={scope} onChange={(e) => setScope(e.target.value as GuideScope)}>
          {GUIDE_SCOPES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>,
      )}
      {field(
        'tx',
        '외부 모델 전송',
        <select id={`${uid}-tx`} className="sel" value={tx} onChange={(e) => setTx(e.target.value as GuideTx)}>
          {GUIDE_TXS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>,
      )}
      <div className="hint">정하지 않으면 가장 제한적인 값(관리자 전용·금지)이 적용돼요.</div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          업로드
        </button>
      </div>
    </Modal>
  )
}

function TxDialog({ g, v, to, onClose, onApply }: { g: Guide; v: GuideVersion; to: GuideTx; onClose: () => void; onApply: (why: string) => void }) {
  const uid = useId()
  const [why, setWhy] = useState('')
  const [err, setErr] = useState('')
  return (
    <Modal title="외부 전송 정책 변경" onClose={onClose}>
      <p className="small muted">
        {guideLabel(g)} {v.version} · {v.tx} → {to}
      </p>
      <div className="alert warn">
        <Icon name="alert" />
        <div>이 가이드 내용이 이전보다 넓게 외부 AI 모델에 전달될 수 있어요. 변경 사유를 남겨 주세요.</div>
      </div>
      <div className="field">
        <label htmlFor={`${uid}-w`}>변경 사유 (필수)</label>
        <input id={`${uid}-w`} className={`inp${err ? ' err' : ''}`} value={why} placeholder="예) 개인정보 없음을 확인함" autoComplete="off" aria-invalid={!!err} onChange={(e) => { setWhy(e.target.value); setErr('') }} />
        {err && (
          <div className="ferr" role="alert">
            {err}
          </div>
        )}
      </div>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" onClick={() => (why.trim() ? onApply(why.trim()) : setErr('변경 사유를 입력해 주세요.'))}>
          변경
        </button>
      </div>
    </Modal>
  )
}

function NoteDialog({ g, v, onClose, onDone }: { g: Guide; v: GuideVersion; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [note, setNote] = useState(v.note)
  const [err, setErr] = useState('')
  const save = async () => {
    if (!user) return
    const r = await setGuideNote(user, g.id, v.id, note)
    if (!r.ok) return setErr(r.error.message)
    onDone()
  }
  return (
    <Modal title={`${v.version} 메모 수정`} onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {guideLabel(g)} · 관리자가 직접 적는 메모예요. AI가 쓰지 않고, 수정하면 변경 기록이 남아요.
      </p>
      <div className="field">
        <label htmlFor={`${uid}-n`}>메모</label>
        <input id={`${uid}-n`} className="inp" value={note} placeholder="예) 5회 실패 시 잠금, 10분 후 해제" autoComplete="off" onChange={(e) => setNote(e.target.value)} />
      </div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" onClick={() => void save()}>
          저장
        </button>
      </div>
    </Modal>
  )
}

function DraftDialog({ c, per, onClose, onDone }: { c: Cluster; per: Per; onClose: () => void; onDone: (g: Guide, version: string, update: boolean) => void }) {
  const { user } = useAuth()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const make = async () => {
    if (!user) return
    setBusy(true)
    const note = `${GCP[per].lb} 분석: 해결 사례 ${c.n}건을 ${c.exist ? '반영한 보강 초안' : '묶어 정리한 초안'}`
    const r = await createGuideDraft(user, { cat: c.cat, title: `${c.title} 가이드 (유사 사례 ${c.n}건 초안)`, existId: c.exist?.id ?? null, note })
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    onDone(r.data.guide, r.data.version, !!c.exist)
  }
  return (
    <Modal title="가이드 초안 미리보기" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {GCP[per].lb} 분석 · 해결 티켓 {c.n}건 · 평균 유사도 {c.sim}%
      </p>
      <dl className="dl" style={{ margin: 0 }}>
        <dt>제목</dt>
        <dd>{c.title} 가이드</dd>
        <dt>분류</dt>
        <dd>
          <span className={`tag c-${c.cat}`}>{CATEGORIES[c.cat].name}</span>
        </dd>
        <dt>대상</dt>
        <dd>{c.exist ? `기존 가이드 보강 · ${guideLabel(c.exist)}` : '새 가이드'}</dd>
      </dl>
      <div>
        <b style={{ fontSize: 14 }}>AI가 정리한 처리 순서</b> <span className="tag gray">시연 데이터</span>
        <ol className="osteps" style={{ marginTop: 8 }}>
          <li>
            <span>해결 사례의 처리 결과에서 공통 단계를 추려요.</span>
          </li>
        </ol>
      </div>
      <div>
        <b style={{ fontSize: 14 }}>근거 티켓</b>
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          {c.list.slice(0, 6).map((t, i) => (
            <span key={t.id}>
              {i > 0 && <span className="muted">· </span>}
              <span className="mono small">{t.receiptNo}</span>
            </span>
          ))}
          {c.n > 6 && <span className="small muted">외 {c.n - 6}건</span>}
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        비밀번호·개인정보 같은 민감정보는 초안에 넣지 않아요. 초안은 관리자 검토 후 현행으로 바꿔요.
      </p>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void make()}>
          {c.exist ? '버전 업데이트 초안' : '신규 가이드 초안'}
        </button>
      </div>
    </Modal>
  )
}
