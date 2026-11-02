/**
 * 운영 현황 (관리자, /ops). (design/ITssue-Prototype.html viewExc)
 * 현재 미처리 문의 중 지금 확인하고 처리할 일만 모았다: 긴급 조치(P1), 당일 미종결 예외, 티켓 연동 확인, 담당자 배정 확인, 팀별 개인 현황.
 *
 * 목록은 접수 목록(TK-05 view=ALL)을 조건별로 받아 나눈다 (api/ops.ts). 팀별 개인 현황은 구성원·부재·업무량이 필요해
 * 서버 모드에서는 안내만 보인다. 확인·재시도·담당자 지정도 서버 모드에서는 요청하지 않고 안내만 한다. (Jira 쪽 작업이 끝까지 진행되지 않음)
 */
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { URGENCY_LABEL } from '../../api/catalog'
import type { Urgency } from '../../api/chatTypes'
import { getOpsSnapshot, recheckTransition, retryJiraCreate, type OpsSnapshot } from '../../api/ops'
import { listCandidates, listSupportGroups, type Candidate, type SupportGroupRef } from '../../api/reference'
import { getTicket, watchTickets } from '../../api/tickets'
import type { TicketDetail, TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatElapsed } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { Topbar } from '../../ui/Topbar'
import { StaffStatus, UrgencyChip } from '../staff/QueueView'
import { ReassignDialog } from './ReassignDialog'

const URGS: Urgency[] = ['P1', 'P2', 'P3', 'P4']
const hm = (iso: string) => {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const monthDay = (iso: string) => {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일`
}

/** 접수 → Jira 생성 → 담당자 배정 3단계: 막힌 단계는 빨강, 확인 중은 노랑, 아직 안 온 단계는 회색 */
function Dots({ t, mode }: { t: TicketSummary; mode: 'link' | 'asg' }) {
  const g = 'var(--s-ok-dot)'
  const r = 'var(--s-urg-dot)'
  const w = 'var(--s-warn-dot)'
  const n = 'var(--s-recv-dot)'
  let c: string[]
  let label: string
  if (mode === 'asg') {
    c = [g, g, r]
    label = '접수 완료, Jira 생성 완료, 담당자 배정 확인 필요'
  } else if (t.transitionStatus === 'NEEDS_ADMIN') {
    c = [g, g, g]
    label = '접수 완료, Jira 생성 완료, 담당자 배정 완료. 상태 동기화 확인 필요'
  } else if (t.jiraSyncStatus === 'NEEDS_ADMIN') {
    c = [g, r, n]
    label = '접수 완료, Jira 생성 막힘, 담당자 배정 대기'
  } else {
    c = [g, w, n]
    label = '접수 완료, Jira 생성 여부 확인 중, 담당자 배정 대기'
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

const linkWhy = (t: TicketSummary) => (t.transitionStatus === 'NEEDS_ADMIN' ? 'Jira 동기화 확인 필요' : t.jiraSyncStatus === 'NEEDS_ADMIN' ? 'Jira 생성 요청 응답 시간 초과 · 생성 여부 확인 필요' : 'Jira 생성 결과 확인 중')
const sub = (t: TicketSummary) => `${t.receiptNo} · ${t.group?.name ?? '-'} · ${t.assignee?.name ?? '배정 전'}`

type Key = 'U' | 'X' | 'L' | 'A'

export function OpsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [groups, setGroups] = useState<SupportGroupRef[]>([])
  const [team, setTeam] = useState('')
  const [chip, setChip] = useState('')
  const [snap, setSnap] = useState<OpsSnapshot | null>(null)
  const [error, setError] = useState('')
  const [more, setMore] = useState<Record<Key, boolean>>({ U: false, X: false, L: false, A: false })
  const [people, setPeople] = useState<Record<string, Candidate[]>>({})
  const [peopleErr, setPeopleErr] = useState('')
  const [results, setResults] = useState<{ at: string; no: string; id: number; text: string }[]>([])
  const [toast, setToast] = useState('')
  const [check, setCheck] = useState<TicketSummary | null>(null)
  const [assign, setAssign] = useState<TicketDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [checkErr, setCheckErr] = useState('')
  const [tick, setTick] = useState(0)
  const [opened] = useState(() => new Date().toISOString())
  const [reload, setReload] = useState(0)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

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

  // 팀별 개인 현황: 담당 그룹마다 구성원·부재·업무량
  useEffect(() => {
    if (!admin || !groups.length) return
    let alive = true
    Promise.all(groups.map((g) => listCandidates(g.name, '팀별 개인 현황').then((r) => [g.name, r] as const))).then((rs) => {
      if (!alive) return
      const bad = rs.find(([, r]) => !r.ok)
      if (bad && !bad[1].ok) {
        setPeopleErr(bad[1].error.message)
        setPeople({})
        return
      }
      setPeopleErr('')
      setPeople(Object.fromEntries(rs.map(([name, r]) => [name, r.ok ? r.data : []])))
    })
    return () => {
      alive = false
    }
  }, [admin, groups, tick, reload])

  useEffect(() => () => clearTimeout(timer.current), [])

  const say = useCallback((m: string) => {
    setToast(m)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setToast(''), 3000)
  }, [])

  const note = useCallback(
    (t: { id: number; receiptNo: string }, text: string) => setResults((l) => [{ at: hm(new Date().toISOString()), no: t.receiptNo, id: t.id, text }, ...l].slice(0, 5)),
    [],
  )

  const grp = chip || team || groups[0]?.name || ''
  const members = people[grp] ?? []
  const open = (id: number) => navigate(`/tickets/${id}`)
  const toggle = (k: Key) => setMore((m) => ({ ...m, [k]: !m[k] }))
  const asOf = snap?.asOf ?? opened

  const goCheck = useCallback(
    async (kind: 'link' | 'trn') => {
      if (!user || !check) return
      setBusy(true)
      setCheckErr('')
      const r = kind === 'trn' ? await recheckTransition(user, check.id) : await retryJiraCreate(user, check.id)
      setBusy(false)
      if (!r.ok) return setCheckErr(r.error.message)
      const t = check
      setCheck(null)
      if (kind === 'trn') {
        const to = r.data.workStatus === 'FIN' ? '해결 확인 대기' : r.data.workStatus === 'CLS' ? '해결 완료' : r.data.workStatus === 'WIP' ? '처리 중' : '처리 대기'
        note(t, `Jira 상태를 확인하고 ${to}(으)로 반영했어요`)
        say(`Jira 반영을 확인했어요. 상태가 ${to}(으)로 바뀌었어요.`)
      } else {
        const who = r.data.assignee ? `${r.data.assignee.name} 님에게 자동 배정했어요` : '담당자는 배정 확인에서 지정해 주세요'
        note(t, `기존 티켓이 없어 새로 생성했어요: ${r.data.jiraKey} · ${who}`)
        say(`기존 티켓이 없어 새로 생성했어요: ${r.data.jiraKey}`)
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

  const rowU = (t: TicketSummary) => (
    <button key={t.id} type="button" className="orow" onClick={() => open(t.id)}>
      <span className="o-p">
        <UrgencyChip u={t.urgency} />
      </span>
      <span className="o-t">
        <b>{t.summary}</b>
        <small>{sub(t)}</small>
      </span>
      <span className="o-s">
        <StaffStatus t={t} />
      </span>
      <span className="o-e">
        <b>{formatElapsed(t.createdAt)}</b> 경과
      </span>
    </button>
  )
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
      {mode === 'link' ? (
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
    else say(r.error.message)
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
                  setChip('')
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
                    <p className="shs">알림이 사라져도 여기서 다시 볼 수 있어요. 새로 열면 지워져요.</p>
                  </div>
                </div>
                {results.map((x, i) => (
                  <div key={i} className="rres">
                    <div>
                      <b>
                        {x.no} · {x.text}
                      </b>
                      <small>{x.at}</small>
                    </div>
                    <button type="button" className="btn ghost sm" onClick={() => open(x.id)}>
                      처리 이력 보기
                    </button>
                  </div>
                ))}
              </section>
            )}

            <div className="ogrid">
              {sec(
                <>
                  긴급 조치 필요 <UrgencyChip u="P1" /> <span className="ocnt">{urgent.length}건</span>
                </>,
                '현재 미처리 · 처리 대기·처리 중 (과거 접수 포함)',
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?pri=P1&st=open')}>
                  P1 보기
                </button>,
                wait(list('U', urgent, rowU, '처리 대기·처리 중인 긴급 건이 없어요.')),
              )}
              {sec(
                <>
                  당일 미종결 예외 <span className="ocnt">{exc.length}건</span> <span className="tag gray">제안</span>
                </>,
                <>
                  접수 당일 안에 끝나지 않은 <UrgencyChip u="P1" /> <UrgencyChip u="P2" /> 건
                </>,
                <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?pri=P12&unres=1')}>
                  모두 보기
                </button>,
                wait(list('X', exc, rowU, '접수 당일 안에 끝나지 않은 P1·P2 건이 없어요.')),
              )}
            </div>

            <div className="ogrid">
              {sec(
                <>
                  티켓 연동 확인 <span className="ocnt">Jira {linkL.length}건</span>
                </>,
                'Jira 이슈가 안 만들어졌거나 상태를 가져오지 못한 건',
                null,
                wait(list('L', linkL, rowC('link'), '연동 확인이 필요한 건이 없어요.')),
                linkL.length ? 'need' : '',
              )}
              {sec(
                <>
                  담당자 배정 확인 <span className="ocnt">배정 전 {asgL.length}건</span>
                </>,
                'Jira 이슈는 만들어졌지만 담당자가 비어 있는 건',
                null,
                wait(list('A', asgL, rowC('asg'), '배정 확인이 필요한 건이 없어요.')),
                asgL.length ? 'need' : '',
              )}
            </div>

            {sec(
              <>
                팀별 개인 현황 <span className="tag gray">제안</span>
              </>,
              '팀별로 근무 여부와 진행 중 티켓의 긴급도를 확인해요. 이름을 누르면 그 담당자의 처리 대기·처리 중 티켓을 볼 수 있어요. 칩 숫자는 근무/전체 인원이에요.',
              null,
              peopleErr ? (
                <div className="alert info" role="status">
                  <Icon name="alert" />
                  <div>{peopleErr}</div>
                </div>
              ) : (
                <>
                  <div className="subc" role="group" aria-label="담당 그룹">
                    {groups.map((g) => {
                      const list = people[g.name] ?? []
                      return (
                        <button key={g.id} type="button" className={`chip${g.name === grp ? ' on' : ''}`} aria-pressed={g.name === grp} onClick={() => setChip(g.name)}>
                          {g.name} <em>{`${list.filter((c) => c.avail).length}/${list.length}`}</em>
                        </button>
                      )
                    })}
                  </div>
                  <div className="tw">
                    <table className="tbl ptbl">
                      <colgroup>
                        <col style={{ width: '14%' }} />
                        <col style={{ width: '13%' }} />
                        <col style={{ width: '11%' }} />
                        <col style={{ width: '11%' }} />
                        <col style={{ width: '22%' }} />
                        <col style={{ width: '12%' }} />
                        <col style={{ width: '17%' }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>이름</th>
                          <th>오늘 상태</th>
                          <th className="c">처리 대기 (RDY)</th>
                          <th className="c">처리 중 (WIP)</th>
                          <th>
                            긴급도 <span className="small muted">(처리 대기 + 처리 중)</span>
                          </th>
                          <th>Jira 계정</th>
                          <th>비고</th>
                        </tr>
                      </thead>
                      <tbody>
                        {members.map((c) => {
                          const notes = [!c.avail && '부재 중 · 자동배정 제외', !c.jira && 'Jira 배정 반영 불가'].filter(Boolean).join(' · ')
                          return (
                            <tr key={c.id}>
                              <td>
                                <button type="button" className="lk" title={`${c.name} 담당자의 처리 대기·처리 중 티켓 보기`} onClick={() => navigate(`/tickets?staff=${encodeURIComponent(c.name)}&st=open`)}>
                                  {c.name}
                                </button>
                              </td>
                              <td>
                                <span className={`stt ${c.avail ? 'on' : 'off'}`}>
                                  <i />
                                  {c.avail ? '근무' : `부재 (${c.leave ?? '연차'})`}
                                </span>
                              </td>
                              <td className="c">{c.rdy}건</td>
                              <td className="c">{c.wip}건</td>
                              <td>
                                <span className="pcs">
                                  {URGS.map((p) => (
                                    <span key={p} className={`pcn ${c.pri[p] ? `pri-${p.toLowerCase()}` : 'z'}`} title={URGENCY_LABEL[p]}>
                                      {p} <b>{c.pri[p]}</b>
                                    </span>
                                  ))}
                                </span>
                              </td>
                              <td>{c.jira ? '연결됨' : <span className="od">⚠ 미연결</span>}</td>
                              <td className="small muted">{notes || '-'}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              ),
            )}
          </div>
        </div>
      </main>

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
          onGo={(kind) => void goCheck(kind)}
        />
      )}
      {assign && (
        <ReassignDialog
          t={assign}
          mode="assign"
          onClose={() => setAssign(null)}
          onDone={() => {
            note(assign, '담당자를 지정했어요')
            say('담당자를 지정했어요.')
            setAssign(null)
            setReload((n) => n + 1)
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

function CheckDialog({ t, busy, err, onClose, onDetail, onGo }: { t: TicketSummary; busy: boolean; err: string; onClose: () => void; onDetail: () => void; onGo: (kind: 'link' | 'trn') => void }) {
  const trn = t.transitionStatus === 'NEEDS_ADMIN'
  const to = t.requestedWorkStatus === 'FIN' ? '해결 확인 대기' : t.requestedWorkStatus === 'CLS' ? '해결 완료' : t.requestedWorkStatus === 'WIP' ? '처리 중' : '요청한 상태'
  return (
    <Modal title={trn ? 'Jira 상태 확인' : 'Jira 생성 확인'} onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {t.receiptNo} · {t.group?.name ?? '-'} · <UrgencyChip u={t.urgency} />
      </p>
      <ol className="osteps">
        <li>
          <b>① Jira에서 찾기</b>
          <span>
            {trn ? (
              <>
                Jira에서 이 티켓의 현재 상태를 먼저 확인하세요. 이미 <b>{to}</b>로 바뀌어 있으면 다시 반영하지 않고 완료로 처리해요. 상태는 Jira 확인 전에는 바뀌지 않아요.
              </>
            ) : (
              <>
                Jira에 접수번호 <b className="mono">{t.receiptNo}</b>로 만들어진 티켓이 있는지 먼저 확인하세요. 확인하기 전에는 다시 만들지 마세요. (중복 생성 방지)
              </>
            )}
          </span>
        </li>
        <li>
          <b>② 결과 기록</b>
          <span>확인한 결과에 맞는 버튼을 눌러 주세요. 처리 이력에 남아요.</span>
        </li>
      </ol>
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
        <button type="button" className="btn pri" disabled={busy} onClick={() => onGo(trn ? 'trn' : 'link')}>
          {trn ? 'Jira 상태 확인·다시 반영' : 'Jira 생성 확인·재시도'}
        </button>
      </div>
    </Modal>
  )
}
