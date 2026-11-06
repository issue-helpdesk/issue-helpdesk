/**
 * 운영 기록 (관리자, /audit). (design/ITssue-Prototype.html viewAudit, docs/api/05 OP-04 GET /audit-logs)
 * AI 판단·접수 확정·담당자 배정·실패 같은 주요 처리 기록을 구분·이벤트·기간으로 조회한다. 대화 원문은 없고 결과와 사유만 보인다.
 * 보안·감사 알림(감지된 의심 신호)과는 다른 기록이다. 접수·문의 대상 기록은 서버가 준 접수번호(R-40)를 구분 칸 둘째 줄에 보이고,
 * 누르면 화면은 그대로 두고 오른쪽에 그 접수의 상세 패널만 연다(다른 접수번호를 누르면 패널만 바뀐다).
 * 서버는 접수번호·이름이 아니라 내부 숫자 id(targetId)만 주므로 id 는 내지 않고(마우스를 올리면 나온다), 서버가 결과에 담아 준
 * 접수번호·문서 코드·FAQ 번호만 구분 칸 둘째 줄에 보여 준다 (docs/api/06 R-42 가 반영되면 모든 줄에 이름을 보일 수 있다).
 * 이벤트·결과의 화면 말은 api/auditLogs.ts 의 사전과 describeAudit() 이다.
 */
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { EVENT_LABEL, TARGET_KINDS, TARGET_LABEL, describeAudit, listAuditLogs, type AuditLog } from '../../api/auditLogs'
import type { Page } from '../../api/inquiries'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatDateTime } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { watchTickets } from '../../api/tickets'
import { listUsers } from '../../api/users'
import { Pager } from '../../ui/Pager'
import { SelectBox } from '../../ui/SelectBox'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { TicketDetailPanel } from '../staff/TicketDetailPanel'

type Period = '' | 'today' | 'w'
const PERIOD: { v: Period; label: string; days?: number }[] = [
  { v: '', label: '전체 기간' },
  { v: 'today', label: '오늘', days: 0 },
  { v: 'w', label: '최근 7일', days: 7 },
]
const PAGE_SIZE = 50

export function AuditLogView() {
  const { user } = useAuth()
  const [target, setTarget] = useState('')
  const [event, setEvent] = useState('')
  const [period, setPeriod] = useState<Period>('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<AuditLog> | null>(null)
  const [error, setError] = useState('')
  const admin = user?.serviceRole === 'ADMIN'
  // 접수번호를 눌러 연 상세 패널 (처음 열 때만 밀려 들어오고, 다른 접수로 바꿀 때는 안의 내용만 바뀐다)
  const [openId, setOpenId] = useState<number | null>(null)
  const [slide, setSlide] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])
  const openTicket = (id: number) => {
    if (openId === null) setSlide(true)
    setOpenId(id)
  }

  // 서버는 사용자 대상 기록에 내부 번호만 주므로, 계정 목록에서 이름·사번을 찾아 보여 준다 (R-42 가 반영되면 필요 없다)
  const [names, setNames] = useState<Record<number, string>>({})
  const needUsers = !!data?.items.some((x) => x.targetType === 'user' && x.targetId !== null && !(x.targetId in names))
  useEffect(() => {
    if (!user || !admin || !needUsers) return
    let alive = true
    ;(async () => {
      const found: Record<number, string> = {}
      for (let pg = 1; pg <= 10; pg++) {
        const r = await listUsers(user, { page: pg, size: 100, sort: 'employeeNo,asc' })
        if (!r.ok) break
        r.data.items.forEach((u) => (found[u.id] = `${u.name} · ${u.employeeNo}`))
        if (pg >= r.data.totalPages) break
      }
      if (alive) setNames((cur) => ({ ...cur, ...found }))
    })()
    return () => {
      alive = false
    }
  }, [user, admin, needUsers])

  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    const days = PERIOD.find((p) => p.v === period)?.days
    listAuditLogs(user, { page, size: PAGE_SIZE, eventType: event || undefined, targetType: target || undefined, days }).then((r) => {
      if (!alive) return
      if (r.ok) {
        setData(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, target, event, period, page])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  // 조건이 바뀌면 첫 쪽부터 다시 본다
  const pick = (set: (v: never) => void) => (v: string) => {
    set(v as never)
    setPage(1)
  }

  return (
    <>
    <main className="main">
      <Topbar title="운영 기록" sub="ITssue에서 일어난 주요 처리 기록" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div className="phead">
            <div className="eyebrow">AUDIT LOG</div>
            <h1>운영 기록을 확인해요</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              AI 판단·접수 확정·담당자 배정·실패 같은 주요 처리 기록이에요. 대화 원문은 남기지 않고 <b>결과와 사유</b>만 보여요.
            </p>
          </div>

          <div className="aufil">
            <div className="d2seg" role="group" aria-label="구분">
              {['', ...TARGET_KINDS].map((k) => (
                <button key={k} type="button" className={target === k ? 'on' : ''} aria-pressed={target === k} onClick={() => pick(setTarget)(k)}>
                  {k ? TARGET_LABEL[k] : '전체'}
                </button>
              ))}
            </div>
            <SelectBox
              id="audit-event"
              auto
              ariaLabel="이벤트"
              value={event}
              options={[{ value: '', label: '이벤트: 전체' }, ...Object.entries(EVENT_LABEL).map(([v, e]) => ({ value: v, label: e.label }))]}
              onChange={pick(setEvent)}
            />
            <div className="d2seg aupd" role="group" aria-label="기간">
              {PERIOD.map((p) => (
                <button key={p.v} type="button" className={period === p.v ? 'on' : ''} aria-pressed={period === p.v} onClick={() => pick(setPeriod)(p.v)}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div className="alert err" role="alert">
              <div>{error}</div>
            </div>
          )}

          <div className="panel" style={{ padding: '6px 10px' }}>
            {!data ? (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            ) : data.items.length === 0 ? (
              <div className="empty">조건에 맞는 기록이 없어요.</div>
            ) : (
              <div className="tw">
                <table className="tbl auditt">
                  {/* 칼럼 너비는 고정: 구분 탭을 바꿔도 칸이 흔들리지 않는다 */}
                  <colgroup>
                    <col style={{ width: 150 }} />
                    <col style={{ width: 130 }} />
                    <col style={{ width: 220 }} />
                    <col style={{ width: 110 }} />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>시각</th>
                      <th>구분</th>
                      <th>이벤트</th>
                      <th>처리자</th>
                      <th>결과 · 사유</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((x) => {
                      const ev = EVENT_LABEL[x.eventType]
                      const text = describeAudit(x)
                      return (
                        <tr key={x.id} className={x.ticketId != null && openId === x.ticketId ? 'cur' : ''} title={x.targetId !== null ? `내부 번호 ${x.targetId}` : undefined}>
                          <td className="tnum">{formatDateTime(x.createdAt)}</td>
                          <td>
                            {/* 종류는 첫 줄, 접수번호·문서 코드 같은 식별 이름은 줄을 바꿔 둘째 줄에 */}
                            <div className="aukd">{x.targetType ? (TARGET_LABEL[x.targetType] ?? x.targetType) : '-'}</div>
                            {x.receiptNo && x.ticketId != null ? (
                              <button type="button" className="aulink mono" aria-label={`접수 ${x.receiptNo} 상세 보기`} onClick={() => openTicket(x.ticketId as number)}>
                                {x.receiptNo}
                              </button>
                            ) : (
                              (text.name || (x.targetType === 'user' && x.targetId !== null && names[x.targetId])) && <div className="aunm mono">{text.name || names[x.targetId as number]}</div>
                            )}
                          </td>
                          <td>
                            <StateBadge tone={ev?.tone ?? 'recv'} label={ev?.label ?? x.eventType} />
                            <span className="aucode">{x.eventType}</span>
                          </td>
                          <td>{x.actor ? x.actor.name : <span className="muted">시스템</span>}</td>
                          <td>
                            {text.out || '-'}
                            {text.reason && <div className="small muted">{text.reason}</div>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {data && <Pager page={data.page} size={data.size} total={data.totalCount} onPage={setPage} />}
          </div>
        </div>
      </div>
    </main>
    {openId !== null && <TicketDetailPanel key={openId} id={openId} tick={tick} slide={slide} onSlideEnd={() => setSlide(false)} onClose={() => setOpenId(null)} />}
    </>
  )
}
