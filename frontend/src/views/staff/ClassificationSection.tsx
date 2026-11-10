/** 담당자는 검토를 요청하고, 관리자는 분류를 바꾸거나 반려한다. 모의·서버의 표시를 공유한다. */
import { useEffect, useId, useRef, useState } from 'react'
import { CATEGORIES } from '../../api/catalog'
import { listClassificationTypes, requestClassification, rejectClassification, type ClassificationType } from '../../api/classification'
import { NETWORK_WRITE } from '../../api/errorText'
import { getTicket } from '../../api/tickets'
import type { ClassificationReport, TicketDetail } from '../../api/ticketTypes'
import { SERVER_INTAKE, USE_MOCK_TICKET } from '../../core/config'
import { formatDateTime } from '../../core/format'
import { useAuth } from '../../core/session'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'
import { useToast } from '../../ui/useToast'
import { ClassificationForm } from '../admin/ClassificationForm'
import { ReassignDialog } from '../admin/ReassignDialog'

export function ClassificationSection({ ticket, reports, reportError, onReload, onUpdated }: {
  ticket: TicketDetail
  reports: ClassificationReport[] | null
  reportError: string
  onReload: () => void
  onUpdated: (ticket: TicketDetail) => void
}) {
  const { user } = useAuth()
  const { say } = useToast()
  const uid = useId()
  const [dialog, setDialog] = useState<null | 'request' | 'classify' | 'reject' | 'assign'>(null)
  const [types, setTypes] = useState<ClassificationType[] | null>(null)
  const [typeError, setTypeError] = useState('')
  const [type, setType] = useState('')
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const admin = user?.serviceRole === 'ADMIN'
  const openReport = ticket.openClassificationReport ?? reports?.find((r) => r.status === 'OPEN')
  const rejected = reports?.find((r) => r.status === 'REJECTED')
  const unavailable = !USE_MOCK_TICKET && !SERVER_INTAKE
  const pending = ticket.assignStatus === 'PENDING' || ticket.transitionStatus === 'PENDING'
  const locked = busy || reports === null || !!reportError || unavailable

  useEffect(() => {
    if (dialog !== 'request') return
    let alive = true
    listClassificationTypes().then((r) => {
      if (!alive) return
      if (r.ok) { setTypes(r.data); setTypeError('') }
      else setTypeError(r.error.message)
    })
    return () => { alive = false }
  }, [dialog])

  if (!user || user.serviceRole === 'EMPLOYEE' || ticket.workStatus !== 'RDY') return null
  const close = () => { if (!sending.current) { setDialog(null); setError('') } }
  const open = (kind: typeof dialog) => {
    setDialog(kind); setReason(''); setType(''); setReasonError(''); setError(''); setTypeError('')
  }
  const done = (updated: TicketDetail) => { onUpdated(updated); setDialog(null) }
  const submit = async () => {
    if (locked || sending.current || (dialog === 'request' && (types === null || !!typeError))) return
    if (!reason.trim()) { setReasonError(dialog === 'reject' ? '반려 사유를 입력해 주세요.' : '요청 사유를 입력해 주세요.'); return }
    if (reason.trim().length > 1000) { setReasonError('사유는 1,000자까지 입력해 주세요.'); return }
    if (dialog === 'reject' && !openReport) return
    sending.current = true; setBusy(true); setError('')
    try {
      const r = dialog === 'request'
        ? await requestClassification(ticket, reason, types?.find((t) => String(t.id) === type), user)
        : await rejectClassification(ticket, openReport!.id, reason, user)
      if (!r.ok) { setError(r.error.message); return }
      const isOpen = r.data.status === 'OPEN'
      onUpdated({ ...ticket, classificationReportOpen: isOpen, openClassificationReport: isOpen ? r.data : null })
      say(isOpen ? '재분류 검토를 요청했어요.' : '재분류 요청을 반려했어요.')
      setDialog(null)
    } catch { setError(NETWORK_WRITE) }
    finally { sending.current = false; setBusy(false) }
  }

  return <section className="classification-assignment-group" aria-label="재분류와 담당자 지정">
    <h4>{admin ? '분류·담당자 지정' : '재분류'}</h4>
    {reportError ? <div className="alert err" role="alert"><div>{reportError}<button type="button" className="btn sec sm" onClick={onReload}>다시 불러오기</button></div></div>
      : reports === null && <p className="small muted" role="status">재분류 이력을 확인하고 있어요…</p>}
    {openReport && <div className="alert info"><div>
      <b>재분류 검토 대기예요.</b>
      <p>{openReport.reason}</p>
      {openReport.suggestedInquiryType && <p>제안 유형: {openReport.suggestedInquiryType.name}</p>}
      <small>{openReport.reporter.name} · {formatDateTime(openReport.createdAt)}</small>
    </div></div>}
    {!openReport && rejected && <div className="alert info"><div><b>재분류 요청이 반려됐어요.</b><p>{rejected.resolutionNote}</p></div></div>}
    {!admin && <p className="small muted">{openReport ? '관리자의 검토가 끝날 때까지 처리 시작·완료를 할 수 없어요. 문의는 처리 대기 상태로 유지돼요.' : rejected ? '관리자가 재분류 요청을 반려했어요. 같은 문의에서는 다시 요청할 수 없어요.' : '분류가 맞지 않으면 관리자에게 검토를 요청해 주세요.'}</p>}
    {unavailable && <p className="small muted">아직 서버 변경 요청을 사용할 수 없는 환경이에요.</p>}
    {admin ? <>
      <p className="small muted">{!ticket.category ? '분류를 지정하면 해당 처리 그룹에서 담당자를 자동배정해요.' : '분류를 변경하면 새 처리 그룹의 담당자를 자동배정해요. 같은 그룹이면 현재 담당자를 유지해요.'}</p>
      <button type="button" className="btn pri block" disabled={locked || pending || ticket.jiraSyncStatus !== 'SYNCED'} onClick={() => open('classify')}>{!ticket.category ? '분류 지정' : openReport ? '재분류 검토' : '분류 변경'}</button>
      {openReport && <button type="button" className="btn sec dng block" disabled={locked} onClick={() => open('reject')}>재분류 반려</button>}
      {ticket.category && <button type="button" className="btn sec block" disabled={busy || unavailable || pending} onClick={() => open('assign')}>{ticket.assignee ? '담당자 변경' : '담당자 지정'}</button>}
    </> : <button type="button" className="btn sec block" disabled={locked || !!openReport || !!rejected || !!ticket.classificationReportOpen} onClick={() => open('request')}>{openReport || ticket.classificationReportOpen ? '재분류 검토 대기' : rejected ? '재분류 요청 반려됨' : '재분류 요청'}</button>}
    {dialog === 'assign' ? <ReassignDialog t={ticket} mode={ticket.assignee ? 'reassign' : 'assign'} onClose={close} onDone={async (registered, kind) => {
      setDialog(null)
      say(kind === 'classification' ? '분류 변경을 요청했어요.' : registered ? '담당자 변경을 요청했어요. ITSM 반영을 기다려 주세요.' : ticket.assignee ? '재배정했어요. 진행 상태는 그대로 유지돼요.' : '담당자를 지정했어요.')
      const r = await getTicket(user, ticket.id)
      if (r.ok) done(r.data)
      else onReload()
    }} /> : dialog && <Modal title={dialog === 'request' ? '재분류 요청' : dialog === 'reject' ? '재분류 반려' : !ticket.category ? '미분류 문의 분류 지정' : '재분류 검토'} onClose={close}>
      {dialog === 'classify' ? <ClassificationForm ticket={ticket} suggestedCode={openReport?.suggestedInquiryType?.code} onCancel={close} onDone={done} /> : <>
        <p className="small muted">{ticket.receiptNo} · {ticket.category?.name ?? '미분류'}</p>
        {dialog === 'request' && <div className="field"><label htmlFor={`${uid}-type`}>맞다고 보는 세부 유형 (선택)</label>
          <SelectBox id={`${uid}-type`} value={type} disabled={busy || types === null} options={[{ value: '', label: '유형을 제안하지 않음' }, ...(types ?? []).map((t) => ({ value: String(t.id), label: `${CATEGORIES[t.categoryCode]?.name ?? t.categoryCode} / ${t.name}`, accent: t.categoryCode }))]} onChange={setType} />
          {typeError && <div className="ferr" role="alert">{typeError}</div>}
        </div>}
        <div className="field"><label htmlFor={`${uid}-reason`}>{dialog === 'reject' ? '반려 사유 (필수)' : '요청 사유 (필수)'}</label>
          <textarea className={`ta${reasonError ? ' err' : ''}`} id={`${uid}-reason`} rows={3} maxLength={1000} disabled={busy} value={reason} aria-invalid={!!reasonError} aria-describedby={`${uid}-count${reasonError ? ` ${uid}-error` : ''}`} onChange={(e) => { setReason(e.target.value); setReasonError('') }} />
          <div className="wcnt"><span className="hint">{dialog === 'reject' ? '사유는 담당자에게 표시돼요. 반려 후에는 재요청할 수 없어요.' : '요청하면 관리자 검토 전까지 처리를 시작할 수 없어요.'}</span><span className="hint" id={`${uid}-count`}>{reason.length}/1000</span></div>
          {reasonError && <div className="ferr" id={`${uid}-error`} role="alert">{reasonError}</div>}
        </div>
        {error && <div className="ferr" role="alert">{error}</div>}
        <div className="acts"><button type="button" className="btn sec" disabled={busy} onClick={close}>취소</button><button type="button" className={`btn ${dialog === 'reject' ? 'sec dng' : 'pri'}`} disabled={locked || (dialog === 'request' && (types === null || !!typeError))} onClick={() => void submit()}>{busy ? '처리 중' : dialog === 'request' ? '재분류 요청' : '반려'}</button></div>
      </>}
    </Modal>}
  </section>
}
