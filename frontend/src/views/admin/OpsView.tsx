/**
 * 운영 현황 (관리자, /ops). (design/ITssue-Prototype.html viewExc)
 * 현재 미처리 문의 중 지금 확인하고 처리할 일만 모았다: 긴급 조치(P1), 당일 미종결 예외, 티켓 연동 확인, 담당자 배정 확인. (팀별 개인 현황은 캘린더 화면 맨 아래에 있다)
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
import { Modal } from '../../ui/Modal'
import { useToast } from '../../ui/useToast'
import { Topbar } from '../../ui/Topbar'
import { UrgencyChip } from '../staff/QueueView'
import { ReassignDialog } from './ReassignDialog'
import { UrgentRow } from './UrgentRow'
import { TicketDetailPanel } from '../staff/TicketDetailPanel'

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
    label = '접수 완료, ITSM 생성 완료, 담당자 배정 확인 필요'
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

const linkWhy = (t: TicketSummary) => (t.transitionStatus === 'NEEDS_ADMIN' ? 'ITSM 동기화 확인 필요' : t.jiraSyncStatus === 'NEEDS_ADMIN' ? 'ITSM 생성 요청 응답 시간 초과 · 생성 여부 확인 필요' : 'ITSM 생성 결과 확인 중')
const sub = (t: TicketSummary) => `${t.receiptNo} · ${t.group?.name ?? '-'} · ${t.assignee?.name ?? '배정 전'}`

type Key = 'U' | 'X' | 'L' | 'A'
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
  const [more, setMore] = useState<Record<Key, boolean>>({ U: false, X: false, L: false, A: false })
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
    const blank = Math.max(0, 3 - shown.length)
    return (
      <>
        <div className="otb">
          {shown.map(row)}
          {blank > 0 && <div className="onil">{items.length ? '해당하는 건이 더 없어요' : none}</div>}
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

  const rowU = (t: TicketSummary) => <UrgentRow key={t.id} t={t} onOpen={() => open(t.id)} />
  const rowC = (mode: 'link' | 'asg') => (t: TicketSummary) => (
    <div key={t.id} className="orow l">
      <div className="o-main">
        <span className="o-p">
          <UrgencyChip u={t.urgency} />
        </span>
        <span className="o-t">
          <b>{t.summary}</b>
          <small>
            {sub(t)} · {mode === 'link' ? linkWhy(t) : '개인 배정을 확인해야 해요'}
          </small>
        </span>
      </div>
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
          지정
        </button>
      )}
    </div>
  )

  const startAssign = async (t: TicketSummary) => {
    if (!user) return
    const r = await getTicket(user, t.id)
    if (r.ok) setAssign(r.data)
    else fail(r.error.message)
  }

  const sec = (title: ReactNode, desc: ReactNode, right: ReactNode, inner: ReactNode, cls?: string, label?: string) => (
    <section className={`panel${cls ? ` ${cls}` : ''}`} aria-label={label}>
      <div className="sech">
        <div>
          <h3 className="sht">{title}</h3>
          <p className="shs">{desc}</p>
        </div>
        {right}
      </div>
      {inner}
    </section>
  )

  const urgent = snap?.urgent ?? []
  const exc = snap?.exception ?? []
  const linkL = snap?.link ?? []
  const asgL = snap?.assign ?? []
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
                현재 미처리 문의 중 지금 확인하고 처리할 일만 모았어요.
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
              <span className="tag gray">제안</span>
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
                    <h3 className="sht">최근 처리 결과</h3>
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

            <div className="ogrid">
              {sec(
                <>
                  긴급 조치 필요 <span className="ocnt">{urgent.length}건</span>
                </>,
                '현재 미처리 · 처리 대기·처리 중 (과거 접수 포함)',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?pri=P1&st=open')}>
                  모두 보기
                </button>,
                wait(list('U', urgent, rowU, '처리 대기·처리 중인 긴급 건이 없어요.')),
              )}
              {sec(
                <>
                  당일 미종결 예외 <span className="ocnt">{exc.length}건</span> <span className="tag gray">제안</span>
                </>,
                '접수 당일 안에 끝나지 않은 긴급·높음 건',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?pri=P12&unres=1')}>
                  모두 보기
                </button>,
                wait(list('X', exc, rowU, '접수 당일 안에 끝나지 않은 긴급·높음 건이 없어요.')),
              )}
            </div>

            <div className="ogrid">
              {sec(
                <>
                  티켓 연동 확인 <span className="ocnt">{linkL.length}건</span>
                </>,
                'ITSM 이슈가 안 만들어졌거나 상태를 가져오지 못한 건',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?st=none')}>
                  모두 보기
                </button>,
                wait(list('L', linkL, rowC('link'), '연동 확인이 필요한 건이 없어요.')),
                linkL.length ? 'need' : '',
              )}
              {sec(
                <>
                  담당자 배정 확인 <span className="ocnt">{asgL.length}건</span>
                </>,
                'ITSM 이슈는 만들어졌지만 담당자가 비어 있는 건',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?st=none')}>
                  모두 보기
                </button>,
                wait(list('A', asgL, rowC('asg'), '배정 확인이 필요한 건이 없어요.')),
                asgL.length ? 'need' : '',
              )}
            </div>
          </div>
        </div>
      </main>

      {openId !== null && <TicketDetailPanel key={openId} id={openId} tick={tick} slide={slide} onSlideEnd={() => setSlide(false)} onClose={() => setOpenId(null)} />}
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
          onDone={(registered) => {
            note(assign, registered ? '담당자 지정 등록함 · 실행기가 처리하면 반영돼요' : '담당자를 지정했어요')
            say(registered ? '담당자 지정을 등록했어요. 실행기가 ITSM에 반영하면 담당자가 바뀌어요.' : '담당자를 지정했어요.')
            setAssign(null)
            setReload((n) => n + 1)
          }}
        />
      )}
    </>
  )
}

const WORK_LABEL = { RDY: '처리 대기', WIP: '처리 중', FIN: '해결 확인 대기', CLS: '해결 완료' } as const

function CheckDialog({ t, busy, err, onClose, onDetail, onGo }: { t: TicketSummary; busy: boolean; err: string; onClose: () => void; onDetail: () => void; onGo: (kind: 'link' | 'trn', reason: string) => void }) {
  const trn = t.transitionStatus === 'NEEDS_ADMIN'
  const [why, setWhy] = useState('')
  const [whyErr, setWhyErr] = useState('')
  const to = t.requestedWorkStatus ? WORK_LABEL[t.requestedWorkStatus] : '요청한 상태'
  const now = t.workStatus ? WORK_LABEL[t.workStatus] : '이전 상태'
  const verifying = t.jiraSyncStatus === 'VERIFYING'
  const submit = () => {
    const w = why.trim()
    if (!w) return setWhyErr('재처리 사유를 입력해 주세요.')
    onGo(trn ? 'trn' : 'link', w)
  }
  return (
    <Modal title={trn ? 'ITSM 상태 확인' : 'ITSM 생성 확인'} onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        접수 <span className="mono">{t.receiptNo}</span> · {t.jiraKey ? <>ITSM <b className="mono">{t.jiraKey}</b></> : 'ITSM 티켓 없음'} · {t.group?.name ?? '-'} · <UrgencyChip u={t.urgency} />
      </p>
      <div className="mdl-issue">
        <div className="stlist" aria-label="확인이 필요한 내용">
          <div className={`sx live ${trn || !verifying ? 'tn-urg' : 'tn-warn'}`}>
            <span className="mk">
              <Icon name="alert" />
            </span>
            <span className="l">{trn ? '상태 변경' : 'ITSM 연동'}</span>
            <span className="vb">
              <span className={`sbd ${trn || !verifying ? 'tn-urg' : 'tn-warn'}`}>
                <i />
                {trn ? 'ITSM 동기화 필요' : verifying ? '생성 여부 확인 중' : 'ITSM 생성 확인 필요'}
              </span>
            </span>
            <span className="sxs">{trn ? `${now} → ${to} 변경이 ITSM에 반영됐는지 확인하지 못함` : linkWhy(t)}</span>
          </div>
        </div>
      </div>
      <p className="mdl-how">
        {trn ? (
          <>
            ITSM에서 현재 상태를 먼저 읽어 와요. 이미 <b>{to}</b>이면 다시 요청하지 않고 완료로 처리하고, 아직 <b>{now}</b>이면 <b>{to}</b>로 바꾸는 요청을 다시 보내요.
          </>
        ) : (
          <>
            ITSM에서 접수번호 <b className="mono">{t.receiptNo}</b>로 만든 티켓이 있는지 먼저 찾아요. 있으면 그 티켓을 연결하고, 없을 때만 새로 만들어요. (중복 생성 방지)
          </>
        )}
      </p>
      <div className="field">
        <label htmlFor="ops-why">
          재처리 사유 <span className="muted">(필수)</span>
        </label>
        <textarea id="ops-why" className={`ta${whyErr ? ' err' : ''}`} maxLength={500} value={why} placeholder="예) ITSM 장애 복구 후 재처리" aria-invalid={!!whyErr} aria-describedby={whyErr ? 'ops-why-e' : undefined} onChange={(e) => { setWhy(e.target.value); setWhyErr('') }} />
        {whyErr && (
          <div className="ferr" id="ops-why-e" role="alert">
            {whyErr}
          </div>
        )}
        <div className="wcnt">
          <span className="hint">처리 이력과 감사 기록에 남아요.</span>
          <span className="hint">
            <b>{why.length}</b>/500
          </span>
        </div>
      </div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          닫기
        </button>
        <button type="button" className="btn sec" onClick={onDetail}>
          상세
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={submit}>
          {trn ? 'ITSM 상태 확인·다시 반영' : 'ITSM 생성 확인·재시도'}
        </button>
      </div>
    </Modal>
  )
}
