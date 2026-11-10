import { useToast } from '../../ui/useToast'
import { useState } from 'react'
import type { TicketDetail } from '../../api/ticketTypes'
import { classificationReport, requestClassificationMock, rejectClassificationMock } from '../../api/mock/classificationMock'
import { getTicket } from '../../api/tickets'
import { SelectBox } from '../../ui/SelectBox'
import { Modal } from '../../ui/Modal'
import { ReassignDialog } from '../admin/ReassignDialog'
import { ClassificationForm } from '../admin/ClassificationForm'
import { CATEGORIES } from '../../api/catalog'
import { useAuth } from '../../core/session'

export function ClassificationMockSection({ticket,onUpdated}:{ticket:TicketDetail;onUpdated:(ticket:TicketDetail)=>void}) {
 const {say}=useToast()
 const {user}=useAuth();const admin=user?.serviceRole==='ADMIN'
 const [dialog,setDialog]=useState<null|'request'|'classify'|'reject'|'assign'>(null)
 const [reason,setReason]=useState('');const [type,setType]=useState('');const [error,setError]=useState('');const [,redraw]=useState(0)
 const report=classificationReport(ticket.id)
 const open=(kind:typeof dialog)=>{setDialog(kind);setReason('');setType('');setError('')}
 const close=()=>{setDialog(null);setError('')}
 const done=(t:TicketDetail)=>{onUpdated(t);redraw(n=>n+1);close()}
 const assignmentDone=()=>{if(user)void getTicket(user,ticket.id).then(r=>{if(r.ok){done(r.data);say(ticket.assignee?'재배정했어요. 진행 상태는 그대로 유지돼요.':'담당자를 지정했어요.')}})}
 const submit=()=>{try{if(dialog==='request')requestClassificationMock(ticket.id,reason);else rejectClassificationMock(ticket.id,reason);redraw(n=>n+1);close()}catch(e){setError(e instanceof Error?e.message:'처리하지 못했어요.')}}
 if(ticket.workStatus!=='RDY')return null
 return <section className="classification-assignment-group" aria-label="재분류와 담당자 지정">
 <h4>{admin?'분류·담당자 지정':'재분류'}</h4>
 {report&&<div className="alert info"><div><b>{report.status==='OPEN'?'재분류 검토 대기예요.':report.status==='REJECTED'?'재분류 요청이 반려됐어요.':'재분류 요청을 처리했어요.'}</b><p style={{marginTop:8}}>{report.status==='REJECTED'?report.resolution:report.reason}</p></div></div>}
 {report?.status==='OPEN'&&!admin&&<p className="small muted">관리자의 검토가 끝날 때까지 처리 시작·완료를 할 수 없어요. 문의는 처리 대기 상태로 유지돼요.</p>}
 {report?.status==='REJECTED'&&!admin&&<p className="small muted">관리자가 재분류 요청을 반려했어요. 같은 문의에서는 다시 요청할 수 없어요.</p>}
 {admin?<><p className="small muted">{!ticket.category?'분류를 지정하면 해당 처리 그룹에서 담당자를 자동배정해요.':'분류를 변경하면 새 처리 그룹의 담당자를 자동배정해요. 같은 그룹이면 현재 담당자를 유지해요.'}</p>
 <button className="btn pri block" onClick={()=>open('classify')}>{!ticket.category?'분류 지정':report?.status==='OPEN'?'재분류 검토':'분류 변경'}</button>
 {report?.status==='OPEN'&&<button className="btn sec dng block" onClick={()=>open('reject')}>재분류 반려</button>}
 {ticket.category&&<button className="btn pri block" onClick={()=>open('assign')}>{ticket.assignee?'담당자 변경':'담당자 지정'}</button>}
 </>:<button className="btn sec block" disabled={report?.status==='OPEN'||report?.status==='REJECTED'} onClick={()=>open('request')}>{report?.status==='OPEN'?'재분류 검토 대기':report?.status==='REJECTED'?'재분류 요청 반려됨':'재분류 요청'}</button>}
 {dialog==='assign'?<ReassignDialog initialMode="assignee" t={ticket} mode={ticket.assignee?'reassign':'assign'} onClose={close} onDone={assignmentDone}/>:dialog&&<Modal title={dialog==='request'?'재분류 요청':dialog==='reject'?'재분류 반려':!ticket.category?'미분류 문의 분류 지정':'재분류 검토'} onClose={close}>
 {dialog==='classify'?<ClassificationForm ticket={ticket} onCancel={close} onDone={done}/>:<>
 <p className="small muted" style={{margin:0}}>{ticket.receiptNo} · {ticket.category?.name??'미분류'}</p>
 {dialog==='request'&&<div className="field"><label htmlFor="mock-classification-type">맞다고 보는 유형 (선택)</label><SelectBox id="mock-classification-type" value={type} options={Object.entries(CATEGORIES).map(([value,info])=>({value,label:info.name,accent:value}))} onChange={setType}/></div>}
 <div className="field"><label htmlFor="mock-classification-reason">{dialog==='reject'?'반려 사유 (필수)':'요청 사유 (필수)'}</label><textarea className="inp" id="mock-classification-reason" rows={3} value={reason} onChange={e=>setReason(e.target.value)}/></div>
 <p className="small muted" style={{margin:0}}>{dialog==='request'?'요청하면 처리 대기 상태를 유지하고 관리자 검토 전까지 처리를 시작할 수 없어요.':'사유는 담당자에게 표시돼요. 반려 후 처리를 시작할 수 있지만 재분류 요청은 다시 할 수 없어요.'}</p>
 {error&&<div className="ferr" role="alert">{error}</div>}
 <div className="acts"><button className="btn sec" onClick={close}>취소</button><button className="btn pri" onClick={submit}>{dialog==='request'?'재분류 요청':'반려'}</button></div>
 </>}
 </Modal>}
 </section>
}
