import { useEffect, useId, useRef, useState } from 'react'
import { CATEGORIES } from '../../api/catalog'
import { listClassificationTypes, saveClassification, type ClassificationType } from '../../api/classification'
import { NETWORK_WRITE } from '../../api/errorText'
import type { TicketDetail } from '../../api/ticketTypes'
import { SERVER_INTAKE, USE_MOCK_TICKET } from '../../core/config'
import { SelectBox } from '../../ui/SelectBox'

/** 목·서버가 같은 입력 화면을 사용하고, 데이터 어댑터만 교체한다. */
export function ClassificationForm({ticket,suggestedCode,onCancel,onDone}:{ticket:TicketDetail;suggestedCode?:string;onCancel:()=>void;onDone:(t:TicketDetail)=>void}) {
 const id=useId();const [types,setTypes]=useState<ClassificationType[]|null>(null);const [pick,setPick]=useState('');const [reason,setReason]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);const sending=useRef(false)
 const notReady=!USE_MOCK_TICKET&&!SERVER_INTAKE
 const [reasonError,setReasonError]=useState('')
 useEffect(()=>{let alive=true;void listClassificationTypes().then(r=>{if(!alive)return;if(r.ok){setTypes(r.data);const proposed=r.data.find(t=>t.code===suggestedCode&&t.code!==ticket.inquiryType?.code);if(proposed)setPick(String(proposed.id))}else setError(r.error.message)});return()=>{alive=false}},[suggestedCode,ticket.inquiryType?.code])
 const selected=types?.find(t=>String(t.id)===pick)
 const submit=async()=>{if(notReady||sending.current)return;if(!selected)return setError('세부 유형을 선택해 주세요.');if(!reason.trim())return setReasonError(ticket.category?'재분류 사유를 입력해 주세요.':'분류 지정 사유를 입력해 주세요.');sending.current=true;setBusy(true);setError('');try{const r=await saveClassification(ticket,selected,reason);if(r.ok)onDone(r.data);else setError(r.error.message)}catch{setError(NETWORK_WRITE)}finally{sending.current=false;setBusy(false)}}
 return <>
 <p className="small muted" style={{margin:0}}>{ticket.receiptNo} · 현재 분류 {ticket.category?.name??'미분류'}</p>
 {notReady&&<div className="alert info" role="status"><div>준비 중이에요. 아직 변경 내용은 저장되지 않아요.</div></div>}
 <div className="field"><label htmlFor={id+'-type'}>세부 유형 (필수)</label><SelectBox id={id+'-type'} value={pick} disabled={busy||types===null} options={(types??[]).filter(t=>t.code!==ticket.inquiryType?.code).map(t=>({value:String(t.id),label:`${CATEGORIES[t.categoryCode]?.name??t.categoryCode} / ${t.name}`,accent:t.categoryCode}))} onChange={setPick}/></div>
 {selected&&<p className="small muted" style={{margin:0}}>처리 그룹: {selected.defaultGroup.name}. {ticket.group?.id===selected.defaultGroup.id?'같은 처리 그룹이므로 현재 담당자를 유지해요.':'처리 그룹이 바뀌면 새 그룹에서 담당자를 자동배정해요.'}</p>}
 <div className="field"><label htmlFor={id+'-reason'}>{ticket.category?'재분류 사유 (필수)':'분류 지정 사유 (필수)'}</label><textarea className={`ta${reasonError?' err':''}`} id={id+'-reason'} rows={3} maxLength={500} disabled={busy} value={reason} aria-invalid={!!reasonError} aria-describedby={`${id}-count${reasonError?` ${id}-error`:''}`} onChange={e=>{setReason(e.target.value);setReasonError('')}}/>
 <div className="wcnt"><span className="hint">처리 이력과 운영 기록에 남아요.</span><span className="hint" id={id+'-count'}>{reason.length}/500</span></div>
 {reasonError&&<div className="ferr" id={id+'-error'} role="alert">{reasonError}</div>}
 </div>
 <p className="small muted" style={{margin:0}}>분류와 배정 결과는 ITSM에 순차 반영돼요. 반영에는 시간이 걸릴 수 있어요. 진행 상태는 처리 대기로 유지돼요.</p>
 {error&&<div className="ferr" role="alert">{error}</div>}
 <div className="acts"><button className="btn sec" disabled={busy} onClick={onCancel}>취소</button><button className="btn pri" disabled={notReady||busy||types===null} onClick={()=>void submit()}>{busy?'저장 중…':ticket.category?'재분류 지정':'분류 지정'}</button></div>
 </>
}
