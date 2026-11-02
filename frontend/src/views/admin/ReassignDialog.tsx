/**
 * 담당자 재배정 창 (관리자). (design/ITssue-Prototype.html 'rs-open')
 * 같은 담당 그룹의 구성원을 오늘 상태·업무량·긴급도·Jira 계정과 함께 보여 주고, 하나를 골라 사유와 함께 재배정한다.
 * 추천은 근무 중이고 Jira 계정이 연결된 사람 중 업무량(처리 대기+처리 중)이 가장 적은 사람이다 (자동배정과 같은 기준).
 * 재배정해도 진행 상태는 그대로이다. 서버(TK-09)는 Jira 실행기가 배포되기 전에는 요청하지 않고 안내만 한다.
 */
import { useEffect, useId, useState } from 'react'
import { URGENCY_LABEL } from '../../api/catalog'
import type { Urgency } from '../../api/chatTypes'
import { listCandidates, type Candidate } from '../../api/reference'
import { reassignTicket } from '../../api/tickets'
import type { TicketDetail } from '../../api/ticketTypes'
import { useAuth } from '../../core/session'
import { Modal } from '../../ui/Modal'

const URGS: Urgency[] = ['P1', 'P2', 'P3', 'P4']

export function ReassignDialog({ t, onClose, onDone }: { t: TicketDetail; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [list, setList] = useState<Candidate[] | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [pick, setPick] = useState<number | null>(null)
  const [why, setWhy] = useState('')
  const [whyErr, setWhyErr] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const group = t.group?.name ?? ''
  const cur = t.assignee?.id ?? null

  useEffect(() => {
    let alive = true
    listCandidates(group).then((r) => {
      if (!alive) return
      if (!r.ok) return setLoadErr(r.error.message)
      setList(r.data)
      // 추천: 근무 중이고 Jira 계정이 연결된 사람 중 업무량이 가장 적은 사람 (현재 담당 제외)
      const ok = r.data.filter((c) => c.id !== cur && c.jira)
      const rec = ok.filter((c) => c.avail).sort((a, b) => a.rdy + a.wip - (b.rdy + b.wip))[0]
      setPick((rec ?? ok[0])?.id ?? null)
    })
    return () => {
      alive = false
    }
  }, [group, cur])

  const recId = list ? list.filter((c) => c.id !== cur && c.jira && c.avail).sort((a, b) => a.rdy + a.wip - (b.rdy + b.wip))[0]?.id : undefined
  const note = (c: Candidate) => (c.id === cur ? '현재 담당' : c.id === recId ? '추천 (가용 + 업무량 최소)' : !c.jira ? 'Jira 배정 반영 불가' : !c.avail ? '부재 · 예외로 지정하면 사유에 남겨요' : '')

  const submit = async () => {
    if (!user) return
    if (!why.trim()) return setWhyErr('재배정 사유를 입력해 주세요.')
    if (pick === null) return setErr('새 담당자를 선택해 주세요.')
    setBusy(true)
    const r = await reassignTicket(user, t.id, { assigneeId: pick, reason: why.trim() })
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    onDone()
  }

  return (
    <Modal title="담당자 재배정" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {t.receiptNo} · {group} · {t.urgency && <span className={`pri-${t.urgency.toLowerCase()}`}>{`${t.urgency} ${URGENCY_LABEL[t.urgency]}`}</span>}
      </p>
      <p style={{ margin: 0 }}>
        현재 담당 <b>{t.assignee?.name ?? '-'}</b>
      </p>
      {loadErr ? (
        <div className="alert err" role="alert">
          <div>{loadErr}</div>
        </div>
      ) : list === null ? (
        <div className="empty" role="status">
          불러오는 중이에요…
        </div>
      ) : (
        <div className="tw">
          <table className="tbl ost">
            <thead>
              <tr>
                <th>
                  <span className="sr">선택</span>
                </th>
                <th>이름</th>
                <th>오늘 상태</th>
                <th>
                  업무량 <span className="small muted">(RDY+WIP)</span>
                </th>
                <th>긴급도</th>
                <th>Jira 계정</th>
                <th>비고</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => {
                const isCur = c.id === cur
                const ok = c.jira && !isCur
                return (
                  <tr key={c.id} className={isCur ? 'vold' : undefined}>
                    <td>
                      <input type="radio" name={`${uid}-as`} id={`${uid}-as-${c.id}`} value={c.id} checked={pick === c.id} disabled={!ok} onChange={() => { setPick(c.id); setErr('') }} />
                    </td>
                    <td>
                      <label htmlFor={`${uid}-as-${c.id}`}>
                        <b>{c.name}</b>
                      </label>
                    </td>
                    <td>
                      <span className={`stt ${c.avail ? 'on' : 'off'}`}>
                        <i />
                        {c.avail ? '근무' : `부재 (${c.leave ?? '연차'})`}
                      </span>
                    </td>
                    <td>
                      {c.rdy + c.wip}건
                      <div className="small muted">
                        RDY {c.rdy} · WIP {c.wip}
                      </div>
                    </td>
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
                    <td className="small muted">{isCur ? <b>현재 담당</b> : note(c)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="field">
        <label htmlFor={`${uid}-w`}>재배정 사유 (필수)</label>
        <input id={`${uid}-w`} className={`inp${whyErr ? ' err' : ''}`} value={why} placeholder="예) 휴가, 업무량 조정" autoComplete="off" aria-invalid={!!whyErr} aria-describedby={whyErr ? `${uid}-w-e` : undefined} onChange={(e) => { setWhy(e.target.value); setWhyErr('') }} />
        {whyErr && (
          <div className="ferr" id={`${uid}-w-e`} role="alert">
            {whyErr}
          </div>
        )}
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        재배정하면 처리 이력에 남고 새 담당자·문의자에게 알림이 가요. 진행 상태는 그대로 유지돼요.
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
        <button type="button" className="btn pri" disabled={busy || !list} onClick={() => void submit()}>
          재배정
        </button>
      </div>
    </Modal>
  )
}
