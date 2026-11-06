/** 담당자 패널의 상태 변경 요청. 상태 확정과 권한 검증은 서버가 맡는다. */
import { useEffect, useRef, useState } from 'react'
import { changeTicketStatus, refreshTickets } from '../../api/tickets'
import type { TicketDetail } from '../../api/ticketTypes'
import type { User } from '../../api/types'

export function TicketWorkActions({ ticket, user, onRequested }: {
  ticket: TicketDetail
  user: User
  onRequested: (ticket: TicketDetail) => void
}) {
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => { active.current = false }
  }, [])

  if (user.serviceRole !== 'AGENT' || ticket.assignee?.id !== user.id) return null
  if (ticket.workStatus !== 'RDY' && ticket.workStatus !== 'WIP') return null

  const locked = sending || ticket.transitionStatus !== 'IDLE' || ticket.jiraSyncStatus !== 'SYNCED' || ticket.assignStatus !== 'ASSIGNED'
  const submit = async () => {
    if (locked || inFlight.current) return
    const result = note.trim()
    if (ticket.workStatus === 'WIP' && (!result || result.length > 4000)) {
      setError('처리 결과를 1~4,000자로 입력해 주세요.')
      return
    }
    inFlight.current = true
    setSending(true)
    setError('')
    try {
      const response = await changeTicketStatus(user, ticket.id, ticket.workStatus === 'RDY'
        ? { workStatus: 'WIP' }
        : { workStatus: 'FIN', resolutionNote: result })
      if (!active.current) return
      if (response.ok) onRequested(response.data)
      else {
        setError(response.error.message)
        // 다른 화면의 변경·진행 중 작업·응답 유실도 서버 최신 값으로 다시 확인한다.
        refreshTickets()
      }
    } finally {
      inFlight.current = false
      if (active.current) setSending(false)
    }
  }

  return (
    <section aria-label="문의 처리" style={{ marginTop: 12 }}>
      {ticket.workStatus === 'WIP' && (
        <div className="field">
          <label htmlFor={`resolution-note-${ticket.id}`}>처리 결과 <span className="small muted">(필수)</span></label>
          <textarea
            id={`resolution-note-${ticket.id}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            maxLength={4000}
            disabled={locked}
            placeholder="확인한 원인과 조치 결과를 입력해 주세요."
          />
        </div>
      )}
      {error && <div className="alert err" role="alert">{error}</div>}
      <button type="button" className="btn pri block" disabled={locked} onClick={submit}>
        {sending ? '요청 중…' : ticket.workStatus === 'RDY' ? '처리 시작' : '처리 완료'}
      </button>
      <p className="small muted">Jira에 반영된 것을 확인한 뒤 상태가 바뀌어요. 처리 완료 후에는 문의자가 해결 여부를 확인해요.</p>
    </section>
  )
}
