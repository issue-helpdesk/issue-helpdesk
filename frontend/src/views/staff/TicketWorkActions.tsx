/**
 * 담당자 패널의 상태 변경 요청. 상태 확정과 권한 검증은 서버가 맡는다.
 * 처리 시작은 바로 요청하고, 처리 완료는 창을 띄워 처리 결과(문의자에게 보이는 내용)를 적게 한다.
 */
import { useEffect, useRef, useState } from 'react'
import { changeTicketStatus, refreshTickets } from '../../api/tickets'
import type { TicketDetail } from '../../api/ticketTypes'
import type { User } from '../../api/types'
import { Modal } from '../../ui/Modal'

export function TicketWorkActions({ ticket, user, onRequested }: {
  ticket: TicketDetail
  user: User
  onRequested: (ticket: TicketDetail) => void
}) {
  const [note, setNote] = useState('')
  const [modal, setModal] = useState(false)
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
  const finishing = ticket.workStatus === 'WIP'

  const submit = async () => {
    if (locked || inFlight.current) return
    const result = note.trim()
    if (finishing && (!result || result.length > 4000)) {
      setError('처리 결과를 1~4,000자로 입력해 주세요.')
      return
    }
    inFlight.current = true
    setSending(true)
    setError('')
    try {
      const response = await changeTicketStatus(user, ticket.id, finishing ? { workStatus: 'FIN', resolutionNote: result } : { workStatus: 'WIP' })
      if (!active.current) return
      if (response.ok) {
        setModal(false)
        onRequested(response.data)
      } else {
        setError(response.error.message)
        // 다른 화면의 변경·진행 중 작업·응답 유실도 서버 최신 값으로 다시 확인한다.
        refreshTickets()
      }
    } finally {
      inFlight.current = false
      if (active.current) setSending(false)
    }
  }

  const close = () => {
    if (sending) return
    setModal(false)
    setError('')
  }

  return (
    <section aria-label="문의 처리" style={{ marginTop: 12 }}>
      {!modal && error && <div className="alert err" role="alert">{error}</div>}
      <button type="button" className="btn pri block" disabled={locked} onClick={finishing ? () => setModal(true) : submit}>
        {sending && !modal ? '요청 중…' : finishing ? '처리 완료' : '처리 시작'}
      </button>
      <p className="small muted">Jira에 반영된 것을 확인한 뒤 상태가 바뀌어요. 처리 완료 후에는 문의자가 해결 여부를 확인해요.</p>
      {modal && (
        <Modal title="처리 결과 등록" onClose={close}>
          <p className="small muted">문의자에게 보이는 내용이에요. 비밀번호·인증번호는 적지 마세요.</p>
          <div className="field">
            <label htmlFor={`resolution-note-${ticket.id}`}>처리 결과 <span className="small muted">(필수)</span></label>
            <textarea
              id={`resolution-note-${ticket.id}`}
              className={`ta${error ? ' err' : ''}`}
              value={note}
              onChange={(e) => { setNote(e.target.value); setError('') }}
              maxLength={4000}
              disabled={sending}
              placeholder="어떤 원인을 어떻게 조치했는지 적어 주세요"
              aria-invalid={!!error}
            />
            {error && <div className="errtx" role="alert">{error}</div>}
          </div>
          <div className="acts">
            <button type="button" className="btn sec" disabled={sending} onClick={close}>취소</button>
            <button type="button" className="btn pri" disabled={locked} onClick={submit}>
              {sending ? '요청 중…' : '등록하고 해결 확인 요청'}
            </button>
          </div>
        </Modal>
      )}
    </section>
  )
}
