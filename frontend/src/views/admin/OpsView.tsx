/**
 * 운영 현황 (관리자, /ops). (design/ITssue-Prototype.html viewExc)
 * 티켓 연동·담당자 배정 확인과 팀별 개인 현황을 함께 보여 준다.
 *
 * 목록은 접수 목록(TK-05 view=ALL)을 조건별로 받아 나눈다 (api/ops.ts). 
 * 확인·재시도는 접수를 서버로 보내는 환경(VITE_SERVER_INTAKE)에서 연동 작업 재처리(TK-12)를 등록한다. 서버는 등록만 하고 실행기가 나중에 처리한다.
 * 담당자 지정은 서버의 배정 API(TK-09)로 예약하고, 마찬가지로 실행기가 반영한다.
 */
import { Fragment, useCallback, useEffect, useState, type ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { getOpsSnapshot, recheckTransition, retryJiraCreate, type OpsSnapshot } from '../../api/ops'
import { listSupportGroups, type SupportGroupRef } from '../../api/reference'
import { getTicket, watchTickets } from '../../api/tickets'
import type { TicketDetail, TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatElapsed } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/useToast'
import { Topbar } from '../../ui/Topbar'
import { UrgencyChip } from '../staff/QueueView'
import { CheckDialog } from './CheckDialog'
import { linkWhy } from './checkText'
import { ReassignDialog } from './ReassignDialog'
import { TicketDetailPanel } from '../staff/TicketDetailPanel'
import { TeamBoard } from './TeamBoard'

const hm = (iso: string) => {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const monthDay = (iso: string) => {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일`
}

/** 접수 → ITSM 생성 → 담당자 배정 3단계: 막힌 단계는 빨강, 확인 중은 노랑, 아직 안 온 단계는 회색 */
function Dots({ t, mode }: { t: TicketSummary; mode: 'link' | 'asg' }) {
  const g = 'var(--s-ok-dot)'
  const r = 'var(--s-urg-dot)'
  const w = 'var(--s-warn-dot)'
  const n = 'var(--s-recv-dot)'
  let c: string[]
  let label: string
  if (mode === 'asg') {
    c = [g, g, r]
    label = '접수 완료, ITSM 생성 완료, 배정 확인 필요'
  } else if (t.transitionStatus === 'NEEDS_ADMIN') {
    c = [g, g, g]
    label = '접수 완료, ITSM 생성 완료, 담당자 배정 완료. 상태 동기화 확인 필요'
  } else if (t.jiraSyncStatus === 'NEEDS_ADMIN') {
    c = [g, r, n]
    label = '접수 완료, ITSM 생성 막힘, 담당자 배정 대기'
  } else {
    c = [g, w, n]
    label = '접수 완료, ITSM 생성 여부 확인 중, 담당자 배정 대기'
  }
  return (
    <span className="odots" role="img" aria-label={label}>
      {c.map((x, i) => (
        <Fragment key={i}>
          {i > 0 && <b />}
          <i style={{ background: x }} />
        </Fragment>
      ))}
    </span>
  )
}

const sub = (t: TicketSummary) => `${t.receiptNo} · ${t.group?.name ?? '-'} · ${t.assignee?.name ?? '배정 전'}`

type Key = 'L' | 'A' | 'U' | 'R'
/** 최근 처리 결과: 같은 접수의 요청 → 결과를 한 건으로 묶는다 */
interface Res {
  id: number
  no: string
  jira: string
  steps: { at: string; text: string; st: 'req' | 'done' }[]
}

export function OpsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [groups, setGroups] = useState<SupportGroupRef[]>([])
  const [team, setTeam] = useState('')
  const [snap, setSnap] = useState<OpsSnapshot | null>(null)
  const [error, setError] = useState('')
  const [more, setMore] = useState<Record<Key, boolean>>({ L: false, A: false, U: false, R: false })
  const [results, setResults] = useState<Res[]>([])
  const [resMore, setResMore] = useState(false)
  const [pending, setPending] = useState<number[]>([])
  const { say, fail } = useToast()
  const [check, setCheck] = useState<TicketSummary | null>(null)
  const [assign, setAssign] = useState<TicketDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [checkErr, setCheckErr] = useState('')
  const [tick, setTick] = useState(0)
  const [opened] = useState(() => new Date().toISOString())
  const [reload, setReload] = useState(0)

  const admin = user?.serviceRole === 'ADMIN'
  const groupId = groups.find((g) => g.name === team)?.id

  useEffect(() => {
    if (!admin) return
    listSupportGroups().then((r) => r.ok && setGroups(r.data))
  }, [admin])

  // 다른 화면에서 접수가 바뀌면 다시 읽는다
  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])

  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    getOpsSnapshot(user, groupId).then((r) => {
      if (!alive) return
      if (r.ok) {
        setSnap(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, groupId, tick, reload])


  /** 같은 접수의 요청과 결과는 한 줄로 묶고, 가장 최근에 건드린 건이 맨 위에 온다 */
  const note = useCallback((t: { id: number; receiptNo: string; jiraKey?: string | null }, text: string, st: 'req' | 'done' = 'done') => {
    setResults((l) => {
      const old = l.find((x) => x.id === t.id)
      const g: Res = old ?? { id: t.id, no: t.receiptNo, jira: '', steps: [] }
      const next: Res = { ...g, jira: t.jiraKey ?? g.jira, steps: [...g.steps, { at: hm(new Date().toISOString()), text, st }].slice(-4) }
      return [next, ...l.filter((x) => x.id !== t.id)].slice(0, 30)
    })
  }, [])

  // 문의를 누르면 전체 문의로 가지 않고 오른쪽에 그 문의의 상세만 연다
  const [openId, setOpenId] = useState<number | null>(null)
  const [slide, setSlide] = useState(false)
  const open = (id: number) => {
    if (openId === null) setSlide(true)
    setOpenId(id)
  }
  const toggle = (k: Key) => setMore((m) => ({ ...m, [k]: !m[k] }))
  const asOf = snap?.asOf ?? opened

  const goCheck = useCallback(
    async (kind: 'link' | 'trn', reason: string) => {
      if (!user || !check) return
      setBusy(true)
      setCheckErr('')
      const t = check
      const started = Date.now()
      const r = kind === 'trn' ? await recheckTransition(user, t.id, reason) : await retryJiraCreate(user, t.id, reason)
      setBusy(false)
      if (!r.ok) return setCheckErr(r.error.message)
      setCheck(null)
      // 요청을 받은 뒤 실제로 반영될 때까지는 행 버튼이 "처리 중"으로 바뀐다 (최소 1.2초는 보여서 눌렀다는 걸 알 수 있게)
      setPending((l) => [...l, t.id])
      note(t, kind === 'trn' ? '상태 다시 반영 요청' : '티켓 생성 재요청', 'req')
      say(r.data.outcome === 'REGISTERED' ? '재처리를 등록했어요. 실행기가 처리하면 상태가 바뀌어요.' : '재처리를 등록했어요. 잠시 뒤 반영돼요.')
      await new Promise((res) => setTimeout(res, Math.max(0, 1200 - (Date.now() - started))))
      setPending((l) => l.filter((x) => x !== t.id))
      // 서버는 등록만 하고 실행기가 나중에 처리한다. 아직 끝난 게 아니라고 남기고 목록은 다시 읽는다
      if (r.data.outcome === 'REGISTERED') {
        note({ ...t, jiraKey: r.data.jiraKey }, '등록함 · 실행기가 처리하면 반영돼요')
        setReload((n) => n + 1)
        return
      }
      if (r.data.outcome === 'LINKED_EXISTING') {
        note({ ...t, jiraKey: r.data.jiraKey }, `이미 만들어진 ITSM 이슈를 연결 · ${r.data.jiraKey}`)
        setReload((n) => n + 1)
        return
      }
      if (r.data.outcome === 'ALREADY_APPLIED') {
        note({ ...t, jiraKey: r.data.jiraKey }, 'ITSM에 이미 반영돼 있어 상태를 맞춤')
        setReload((n) => n + 1)
        return
      }
      if (kind === 'trn') {
        const to = r.data.workStatus === 'FIN' ? '해결 확인 대기' : r.data.workStatus === 'CLS' ? '해결 완료' : r.data.workStatus === 'WIP' ? '처리 중' : '처리 대기'
        note({ ...t, jiraKey: r.data.jiraKey }, `${to}(으)로 반영`)
      } else {
        note({ ...t, jiraKey: r.data.jiraKey }, `티켓 생성 · ${r.data.jiraKey}${r.data.assignee ? ` · ${r.data.assignee.name} 자동 배정` : ''}`)
      }
      setReload((n) => n + 1)
    },
    [user, check, note, say],
  )

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />

  const list = (k: Key, items: TicketSummary[], row: (t: TicketSummary) => ReactNode, none: string) => {
    const shown = more[k] ? items : items.slice(0, 3)
    return (
      <>
        <div className="otb">
          {shown.map(row)}
            {items.length === 0 && <div className="onil">{none}</div>}
        </div>
        {items.length > 3 && (
          <div className="omore">
            <button type="button" className="btn ghost sm" onClick={() => toggle(k)}>
              {more[k] ? '접기' : `나머지 ${items.length - 3}건 보기`}
            </button>
          </div>
        )}
      </>
    )
  }

  const rowC = (mode: 'link' | 'asg') => (t: TicketSummary) => (
    <div key={t.id} className="orow l">
      <button type="button" className="o-main" title="상세 보기" aria-label={`${t.summary} 상세 보기`} onClick={() => open(t.id)}>
        <span className="o-p">
          <UrgencyChip u={t.urgency} />
        </span>
        <span className="o-t">
          <b>{t.summary}</b>
          <small>
            {sub(t)} · {mode === 'link' ? linkWhy(t) : '개인 배정을 확인해야 해요'}
          </small>
        </span>
      </button>
      <Dots t={t} mode={mode} />
      <span className="o-e">
        <b>{formatElapsed(t.createdAt)}</b> 경과
      </span>
      {pending.includes(t.id) ? (
        <button type="button" className="btn pri sm" aria-busy="true" aria-disabled="true">
          <span>처리 중</span>
          <span className="dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </button>
      ) : mode === 'link' ? (
        <button type="button" className="btn pri sm" onClick={() => { setCheckErr(''); setCheck(t) }}>
          확인
        </button>
      ) : (
        <button type="button" className="btn pri sm" onClick={() => void startAssign(t)}>
          변경
        </button>
      )}
    </div>
  )

  // 신호등이 필요 없는 RDY 카드도 연동·배정 카드의 칼럼 위치를 유지한다.
  const classificationRow = (mode: 'unclassified' | 'review') => (t: TicketSummary) => (
    <div key={t.id} className="orow l">
      <button type="button" className="o-main" aria-label={`${t.summary} 상세 보기`} onClick={() => open(t.id)}>
        <span className="o-p"><UrgencyChip u={t.urgency} /></span>
        <span className="o-t"><b>{t.summary}</b><small>{sub(t)}</small></span>
      </button>
      <span aria-hidden="true" />
      <span className="o-e"><b>{formatElapsed(t.createdAt)}</b> 경과</span>
      <button type="button" className="btn pri sm" onClick={() => open(t.id)}>{mode === 'unclassified' ? '분류 지정' : '검토'}</button>
    </div>
  )

  const startAssign = async (t: TicketSummary) => {
    if (!user) return
    const r = await getTicket(user, t.id)
    if (r.ok) setAssign(r.data)
    else fail(r.error.message)
  }

  const sec = (title: ReactNode, desc: ReactNode, right: ReactNode, inner: ReactNode, cls?: string, label?: string) => (
    <section className="panel" aria-label={label}>
      <div className="sech">
        <div>
          <h2 className={`sht${cls ? ` ${cls}` : ''}`}>{title}</h2>
          <p className="shs">{desc}</p>
        </div>
        {right}
      </div>
      {inner}
    </section>
  )

  const linkL = snap?.link ?? []
  const asgL = snap?.assign ?? []
  const unclassifiedL = snap?.unclassified ?? []
  const reclassificationL = snap?.reclassification ?? []
  const wait = (body: ReactNode) => (snap ? body : <div className="empty" role="status">불러오는 중이에요…</div>)

  return (
    <>
      <main className="main">
        <Topbar title="운영 현황" sub={`현재 미처리 · ${hm(asOf)} 기준`} lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page opage">
            <div className="phead">
              <div className="eyebrow">NOW</div>
              <h1>운영 현황</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                연동·배정 확인이 필요한 문의와 팀원별 진행 중인 업무를 확인해요.
              </p>
            </div>

            <div className="ofil">
              <span className="d2p act" style={{ cursor: 'default' }}>
                <span className="ddb">
                  <small>기준</small>
                  <span>현재 미처리 전체</span>
                </span>
              </span>
              <FilterPill
                label="담당 그룹"
                value={team}
                options={groups.map((g) => ({ value: g.name, label: g.name }))}
                onChange={(v) => {
                  setTeam(v)
                }}
              />
              <span className="small muted">
                {monthDay(asOf)} {hm(asOf)} 기준
              </span>
              <span className="small muted dsy">
                <span>마지막 조회 {hm(asOf)}</span>
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={() => {
                    setReload((n) => n + 1)
                    say('최신 상태로 새로 불러왔어요.')
                  }}
                >
                  <Icon name="refresh" /> 새로고침
                </button>
              </span>
            </div>

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                    다시 시도
                  </button>
                </div>
              </div>
            )}

            {results.length > 0 && (
              <section className="panel" aria-label="최근 처리 결과" style={{ padding: '16px 20px' }}>
                <div className="sech">
                  <div>
                    <h2 className="sht">최근 처리 결과</h2>
                    <p className="shs">같은 건의 요청과 결과는 한 줄로 모아 보여요. 새로 열면 지워져요.</p>
                  </div>
                  {results.length > 3 && <span className="ocnt">{results.length}건</span>}
                </div>
                {(resMore ? results : results.slice(0, 3)).map((g) => {
                  const last = g.steps[g.steps.length - 1]
                  const doing = last.st === 'req'
                  return (
                    <div key={g.id} className="rres">
                      <div className="rr-m">
                        <div className="rr-t">
                          <span className="mono">{g.no}</span>
                          {g.jira && (
                            <>
                              {' · '}
                              <span className="mono">{g.jira}</span>
                            </>
                          )}
                          <span className={`rr-s ${doing ? 'ing' : 'ok'}`}>
                            {doing ? (
                              <>
                                처리 중
                                <span className="dots" aria-hidden="true">
                                  <i />
                                  <i />
                                  <i />
                                </span>
                              </>
                            ) : (
                              '완료'
                            )}
                          </span>
                        </div>
                        <div className="rr-l">
                          {g.steps.map((x, i) => (
                            <Fragment key={i}>
                              {i > 0 && (
                                <i className="ar" aria-hidden="true">
                                  →
                                </i>
                              )}
                              <span>
                                <time>{x.at}</time> {x.text}
                              </span>
                            </Fragment>
                          ))}
                        </div>
                      </div>
                      <button type="button" className="btn ghost sm" onClick={() => open(g.id)}>
                        처리 이력 보기
                      </button>
                    </div>
                  )
                })}
                {results.length > 3 && (
                  <div className="omore">
                    <button type="button" className="btn ghost sm" aria-expanded={resMore} onClick={() => setResMore((v) => !v)}>
                      {resMore ? '접기' : `나머지 ${results.length - 3}건 보기`}
                    </button>
                  </div>
                )}
              </section>
            )}

            {unclassifiedL.some(t=>t.urgency==='P1'||t.urgency==='P2') && <div className="alert info"><Icon name="alert" /><div>긴급·높음 미분류 문의가 있어요. 분류를 지정하고 담당자 배정을 확인해 주세요.</div></div>}
            <div className="ogrid">
              {sec(<>미분류 문의 <span className="ocnt">{unclassifiedL.length}건</span></>, '분류가 정해지지 않은 문의예요. 분류 지정 후 담당자를 확인해 주세요.', null, wait(list('U', unclassifiedL, classificationRow('unclassified'), '미분류 문의가 없어요.')),'need')}
              {sec(
                <>
                  티켓 연동 확인 <span className="ocnt">{linkL.length}건</span>
                </>,
                'ITSM 이슈가 안 만들어졌거나 상태를 가져오지 못한 건',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?needs=1')}>
                  모두 보기
                </button>,
                wait(list('L', linkL, rowC('link'), '연동 확인이 필요한 건이 없어요.')),
                'need',
              )}
              {sec(<>재분류 요청 <span className="ocnt">{reclassificationL.length}건</span></>, '담당자가 분류 검토를 요청한 문의예요.', null, wait(list('R', reclassificationL, classificationRow('review'), '재분류 요청이 없어요.')))}

              {sec(
                <>
                  담당자 배정 확인 <span className="ocnt">{asgL.length}건</span>
                </>,
                '분류를 확인하고 담당자를 지정해 주세요.',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets')}>
                  다른 문의 찾아 변경
                </button>,
                wait(list('A', asgL, rowC('asg'), '배정 확인이 필요한 건이 없어요.')),
                '',
              )}
            </div>
            <TeamBoard selectedGroup={team} onGroupChange={setTeam} refreshKey={reload} />
          </div>
        </div>
      </main>

      {openId !== null && <TicketDetailPanel key={openId} id={openId} tick={tick} slide={slide} onSlideEnd={() => setSlide(false)} onClose={() => setOpenId(null)}  />}
      {check && (
        <CheckDialog
          t={check}
          busy={busy}
          err={checkErr}
          onClose={() => setCheck(null)}
          onDetail={() => {
            setCheck(null)
            open(check.id)
          }}
          onGo={(kind, reason) => void goCheck(kind, reason)}
        />
      )}
      {assign && (
        <ReassignDialog
          t={assign}
          mode="assign"
          onClose={() => setAssign(null)}
          onDone={(registered, kind) => {
            note(assign, kind === 'classification' ? '분류 변경 요청 · 그룹 변경 시 자동배정' : registered ? '담당자 지정 등록함 · 실행기가 처리하면 반영돼요' : '담당자를 지정했어요')
            say(kind === 'classification' ? '분류 변경을 요청했어요. 처리 그룹이 바뀌면 담당자가 자동배정돼요.' : registered ? '담당자 지정을 등록했어요. 실행기가 ITSM에 반영하면 담당자가 바뀌어요.' : '담당자를 지정했어요.')
            setAssign(null)
            setReload((n) => n + 1)
          }}
        />
      )}
    </>
  )
}
