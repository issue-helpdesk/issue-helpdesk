/**
 * 캘린더 (담당자·관리자): 연차·반차 일정을 달력으로 보고, 내 일정을 등록·삭제한다. (docs/api/05 TO-01~04)
 *
 * - 보이는 범위는 서버가 정한다: 관리자는 전체, 팀장은 자기 그룹, 일반 담당자는 지금은 본인만(팀 일정은 서버에 요청 중).
 * - 관리자에게만 "내 일정 / 전체" 보기 전환이 있다. 담당자는 서버가 주는 범위를 그대로 보여 준다.
 * - 등록·삭제는 본인 일정만 한다. 부재 중인 사람은 자동 배정에서 빠진다는 안내를 머리말에 둔다.
 * - 달력과 같은 내용을 목록으로도 보여 준다 (달력만으로는 읽기 어려운 사용자와 좁은 화면을 위해).
 */
import { useEffect, useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { createTimeOff, deleteTimeOff, listTimeOff, TIME_OFF_LABEL, ymd, type TimeOff, type TimeOffType } from '../../api/timeOff'
import titleOps from '../../assets/mascot/title-ops.webp'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'
import { Topbar } from '../../ui/Topbar'
import { useToast } from '../../ui/useToast'

const DOW = ['일', '월', '화', '수', '목', '금', '토']
const KIND_CLS: Record<TimeOffType, string> = { ANNUAL: 'an', HALF_AM: 'am', HALF_PM: 'pm' }

const pad = (n: number) => String(n).padStart(2, '0')
const fmtDay = (s: string) => {
  const d = new Date(`${s}T00:00:00`)
  return `${d.getMonth() + 1}/${d.getDate()}(${DOW[d.getDay()]})`
}
const period = (t: TimeOff) => (t.startDate === t.endDate ? fmtDay(t.startDate) : `${fmtDay(t.startDate)} ~ ${fmtDay(t.endDate)}`)

/** 그 달 달력에 보이는 날짜들 (앞뒤 빈 칸은 이웃 달 날짜로 채워 항상 7의 배수) */
function gridDays(year: number, month: number): string[] {
  const first = new Date(year, month, 1)
  const start = new Date(year, month, 1 - first.getDay())
  const last = new Date(year, month + 1, 0)
  const total = Math.ceil((first.getDay() + last.getDate()) / 7) * 7
  return Array.from({ length: total }, (_, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    return ymd(d)
  })
}

export function CalendarView() {
  const { user } = useAuth()
  const [today] = useState(() => ymd(new Date()))
  const [ym, setYm] = useState(() => ({ y: new Date().getFullYear(), m: new Date().getMonth() }))
  const [all, setAll] = useState<TimeOff[] | null>(null)
  const [error, setError] = useState('')
  const [scope, setScope] = useState<'all' | 'mine'>('all')
  const [tick, setTick] = useState(0)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<TimeOff | null>(null)
  const { say, fail } = useToast()
  const allowed = user?.serviceRole === 'AGENT' || user?.serviceRole === 'ADMIN'
  const admin = user?.serviceRole === 'ADMIN'

  const days = useMemo(() => gridDays(ym.y, ym.m), [ym])

  useEffect(() => {
    if (!user || !allowed) return
    let alive = true
    listTimeOff(user, days[0], days[days.length - 1]).then((r) => {
      if (!alive) return
      if (r.ok) {
        setAll(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, allowed, days, tick])

  if (user && !allowed) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const items = (all ?? []).filter((t) => scope === 'all' || t.userId === user.id)
  const monthFrom = `${ym.y}-${pad(ym.m + 1)}-01`
  const monthTo = ymd(new Date(ym.y, ym.m + 1, 0))
  const inMonth = items.filter((t) => t.startDate <= monthTo && t.endDate >= monthFrom)
  const onDay = (d: string) => items.filter((t) => t.startDate <= d && t.endDate >= d)
  const move = (delta: number) => setYm((c) => { const d = new Date(c.y, c.m + delta, 1); return { y: d.getFullYear(), m: d.getMonth() } })
  const showAllLabel = admin ? '전체' : '보이는 일정'

  async function remove(t: TimeOff) {
    const r = await deleteTimeOff(t.id)
    setRemoving(null)
    if (!r.ok) return fail(r.error.message)
    say('부재 일정을 삭제했어요.')
    setTick((n) => n + 1)
  }

  return (
    <>
      <main className="main">
        <Topbar title="캘린더" sub="연차·반차 일정을 확인하고 내 일정을 등록해요" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">CALENDAR</div>
              <h1>캘린더</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                연차·반차를 등록하면 그 시간에는 자동 배정에서 빠져요. 일정은 본인 것만 등록하고 삭제할 수 있어요.
              </p>
            </div>

            <div className="calbar">
              <div className="calnav">
                <button type="button" className="btn sec sm" aria-label="이전 달" onClick={() => move(-1)}>
                  <Icon name="chevron" className="flip" />
                </button>
                <h2 className="calttl" aria-live="polite">
                  {ym.y}년 {ym.m + 1}월
                </h2>
                <button type="button" className="btn sec sm" aria-label="다음 달" onClick={() => move(1)}>
                  <Icon name="chevron" />
                </button>
                <button type="button" className="btn sec sm" onClick={() => setYm({ y: new Date().getFullYear(), m: new Date().getMonth() })}>
                  오늘
                </button>
              </div>
              <div className="calact">
                {admin && (
                  <div className="seg" role="group" aria-label="보기 범위">
                    <button type="button" className={scope === 'mine' ? 'on' : ''} aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>
                      내 일정
                    </button>
                    <button type="button" className={scope === 'all' ? 'on' : ''} aria-pressed={scope === 'all'} onClick={() => setScope('all')}>
                      {showAllLabel}
                    </button>
                  </div>
                )}
                <button type="button" className="btn pri" onClick={() => setAdding(true)}>
                  <Icon name="plus" /> 일정 등록
                </button>
              </div>
            </div>

            {error && (
              <div className="alert bad" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn sec sm" onClick={() => setTick((n) => n + 1)}>
                    다시 불러오기
                  </button>
                </div>
              </div>
            )}

            <div className="panel calwrap">
              <div className="cal" role="grid" aria-label={`${ym.y}년 ${ym.m + 1}월 부재 일정`}>
                {DOW.map((d) => (
                  <div key={d} className="dow" role="columnheader">
                    {d}
                  </div>
                ))}
                {days.map((d) => {
                  const evs = onDay(d)
                  const out = Number(d.slice(5, 7)) - 1 !== ym.m
                  return (
                    <div key={d} className={`cd${out ? ' out' : ''}${d === today ? ' today' : ''}`} role="gridcell" aria-current={d === today ? 'date' : undefined}>
                      <span className="dn">{Number(d.slice(8))}</span>
                      {evs.map((t) => (
                        <span key={t.id} className={`ev ${KIND_CLS[t.timeOffType]}`} title={`${t.user.name} · ${TIME_OFF_LABEL[t.timeOffType]}${t.note ? ` · ${t.note}` : ''}`}>
                          {t.user.name} {TIME_OFF_LABEL[t.timeOffType]}
                        </span>
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="panel">
              <h3 style={{ margin: '0 0 8px' }}>
                {ym.m + 1}월 일정 <span className="small muted">{inMonth.length}건</span>
              </h3>
              {all === null && !error ? (
                <div className="muted small" role="status">
                  불러오는 중이에요.
                </div>
              ) : inMonth.length === 0 ? (
                <div className="muted" style={{ padding: '14px 0' }}>
                  이번 달 등록된 부재 일정이 없어요. 연차나 반차 계획이 있으면 미리 등록해 두세요.
                </div>
              ) : (
                <div className="tw">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>구성원</th>
                        <th>유형</th>
                        <th>기간</th>
                        <th>메모</th>
                        <th>
                          <span className="sr">관리</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {inMonth.map((t) => (
                        <tr key={t.id}>
                          <td>
                            <b>{t.user.name}</b>
                          </td>
                          <td>
                            <span className={`evt ${KIND_CLS[t.timeOffType]}`}>{TIME_OFF_LABEL[t.timeOffType]}</span>
                          </td>
                          <td>{period(t)}</td>
                          <td>{t.note || '—'}</td>
                          <td>
                            {t.userId === user.id && (
                              <button type="button" className="btn ghost sm" aria-label={`${period(t)} ${TIME_OFF_LABEL[t.timeOffType]} 삭제`} onClick={() => setRemoving(t)}>
                                삭제
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {adding && (
        <AddDialog
          onClose={() => setAdding(false)}
          onDone={(msg, firstDay) => {
            setAdding(false)
            say(msg)
            const d = new Date(`${firstDay}T00:00:00`)
            setYm({ y: d.getFullYear(), m: d.getMonth() })
            setTick((n) => n + 1)
          }}
        />
      )}
      {removing && (
        <Modal title={`${period(removing)} ${TIME_OFF_LABEL[removing.timeOffType]}을(를) 삭제할까요?`} role="alertdialog" variant="form" onClose={() => setRemoving(null)}>
          <p className="muted small" style={{ margin: 0 }}>
            삭제하면 이 기간에도 자동 배정 대상에 다시 포함돼요.
          </p>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setRemoving(null)}>
              취소
            </button>
            <button type="button" className="btn pri" onClick={() => void remove(removing)}>
              삭제
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

function AddDialog({ onClose, onDone }: { onClose: () => void; onDone: (message: string, firstDay: string) => void }) {
  const { user } = useAuth()
  const [today] = useState(() => ymd(new Date()))
  const [kind, setKind] = useState<TimeOffType>('ANNUAL')
  const [start, setStart] = useState(today)
  const [end, setEnd] = useState(today)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [top, setTop] = useState('')
  const [errs, setErrs] = useState<Partial<Record<'start' | 'end' | 'note', string>>>({})
  const half = kind !== 'ANNUAL'

  async function submit() {
    if (!user || busy) return
    const e: typeof errs = {}
    if (!start) e.start = '시작일을 정해 주세요.'
    if (!end) e.end = '종료일을 정해 주세요.'
    else if (start && end < start) e.end = '종료일은 시작일 이후로 정해 주세요.'
    if (note.length > 500) e.note = '메모는 500자까지 쓸 수 있어요.'
    setTop('')
    setErrs(e)
    if (Object.keys(e).length) return
    setBusy(true)
    const r = await createTimeOff(user, { timeOffType: kind, startDate: start, endDate: half ? start : end, note })
    setBusy(false)
    if (r.ok) return onDone('부재 일정을 등록했어요.', start)
    if (r.error.code === 'TIME_OFF_OVERLAP') return setTop(r.error.message)
    const next: typeof e = {}
    for (const d of r.error.details ?? []) {
      if (d.field === 'startDate') next.start = d.message
      else if (d.field === 'endDate') next.end = d.message
      else if (d.field === 'note') next.note = d.message
    }
    if (Object.keys(next).length) setErrs(next)
    else setTop(r.error.message)
  }

  const fld = (k: 'start' | 'end' | 'note', id: string, label: string, input: React.ReactNode) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {input}
      {errs[k] && (
        <div className="errtx" id={`${id}-err`} role="alert">
          {errs[k]}
        </div>
      )}
    </div>
  )

  return (
    <Modal title="부재 일정 등록" variant="form" onClose={onClose}>
      <form
        noValidate
        style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
        onSubmit={(ev) => {
          ev.preventDefault()
          void submit()
        }}
      >
        {top && (
          <div className="alert bad" role="alert">
            <Icon name="alert" />
            <div>{top}</div>
          </div>
        )}
        <div className="field">
          <label htmlFor="to-kind">유형</label>
          <SelectBox
            id="to-kind"
            value={kind}
            options={(Object.keys(TIME_OFF_LABEL) as TimeOffType[]).map((k) => ({ value: k, label: TIME_OFF_LABEL[k] }))}
            onChange={(v) => {
              setKind(v as TimeOffType)
              if (v !== 'ANNUAL') setEnd(start)
            }}
          />
        </div>
        <div className="row2">
          {fld('start', 'to-start', half ? '날짜' : '시작일', <input id="to-start" type="date" className={`inp${errs.start ? ' err' : ''}`} value={start} onChange={(e) => { setStart(e.target.value); if (half) setEnd(e.target.value) }} aria-invalid={!!errs.start} aria-describedby={errs.start ? 'to-start-err' : undefined} />)}
          {!half && fld('end', 'to-end', '종료일', <input id="to-end" type="date" className={`inp${errs.end ? ' err' : ''}`} value={end} min={start} onChange={(e) => setEnd(e.target.value)} aria-invalid={!!errs.end} aria-describedby={errs.end ? 'to-end-err' : undefined} />)}
        </div>
        {half && <div className="hint">반차는 하루만 등록할 수 있어요.</div>}
        {fld('note', 'to-note', '메모 (선택)', <input id="to-note" className={`inp${errs.note ? ' err' : ''}`} value={note} placeholder="예) 가족 행사" onChange={(e) => setNote(e.target.value)} aria-invalid={!!errs.note} aria-describedby={errs.note ? 'to-note-err' : undefined} />)}
        <div className="acts">
          <button type="button" className="btn sec" onClick={onClose}>
            취소
          </button>
          <button type="submit" className="btn pri" aria-disabled={busy}>
            등록
          </button>
        </div>
      </form>
    </Modal>
  )
}
