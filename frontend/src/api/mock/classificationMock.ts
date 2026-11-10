/** 프론트 목 모드 전용 재분류 데이터. 서버 요청·브라우저 영구 저장 없음. */
import { USE_MOCK_TICKET } from '../../core/config'
import { CATEGORIES } from '../catalog'
import type { CategoryCode } from '../chatTypes'
import type { UserRef } from '../ticketTypes'
import { allStaffTickets, findStaffTicket, GROUP_ID, GROUP_STAFF, mutateSeed, workloadOf } from './staffTickets'

export interface MockClassificationReport { status: 'OPEN'|'REJECTED'|'RESOLVED'; reason: string; resolution?: string; suggestedInquiryType?: { code: string; name: string }; reporter?: UserRef; resolvedBy?: UserRef }
export interface ClassificationEvent { at:string; title:string; reason:string }
const events = new Map<number,ClassificationEvent[]>()
export const classificationEvents = (id:number) => events.get(id) ?? []
const record = (id:number,title:string,reason:string) => events.set(id,[...(events.get(id)??[]),{at:new Date().toISOString(),title,reason}])
const requireReady = (id:number) => {if(findStaffTicket(id)?.workStatus!=='RDY')throw new Error('처리 대기 상태에서만 재분류할 수 있어요.')}
const reports = new Map<number, MockClassificationReport>()
const pending = new Set<number>()
const touch = (id: number) => mutateSeed(id, (t) => { t.classificationReportOpen = reports.get(id)?.status === 'OPEN' })
const enabled = () => { if (!USE_MOCK_TICKET) throw new Error('목 모드에서만 사용할 수 있어요.') }
export function resetClassificationMock() {
  reports.clear(); pending.clear(); events.clear()
  if (!USE_MOCK_TICKET) return
  mutateSeed(5039, t => {t.summary='계정 인증 오류 · 미분류 문의';t.category=null;t.inquiryType=null;t.assignee=null;t.group={id:1,name:'서비스데스크'};t.workStatus='RDY';t.jiraSyncStatus='SYNCED';t.assignStatus='NEEDS_ADMIN';t.needsAdmin=true})
  for(const id of [5005,5008])mutateSeed(id,t=>{t.workStatus='RDY';t.displayStatus='assigned';t.resolutionNote=null;t.finishedAt=null;t.closedAt=null})
  reports.set(5005,{status:'OPEN',reason:'VPN보다 계정 인증 문제로 보여 재분류 검토를 요청해요.'})
  reports.set(5008,{status:'REJECTED',reason:'다른 처리 그룹의 검토가 필요해 보여 요청했어요.',resolution:'네트워크 장비 확인이 필요한 문의로 현재 분류를 유지합니다.'})
  for(const [id,report] of reports){record(id,'재분류 요청',report.reason);if(report.status==='REJECTED')record(id,'재분류 반려',report.resolution??'');touch(id)}
}
resetClassificationMock()
export const classificationReport = (id: number) => reports.get(id)
export const classificationPending = (id: number) => pending.has(id)
export const unclassifiedMockTickets = () => USE_MOCK_TICKET ? allStaffTickets().filter(t=>t.workStatus!=='CLS'&&(!t.category||!t.inquiryType)) : []
// 기존 시드의 inquiryType은 대부분 null이므로, 목 시연에서 미분류는 category=null인 접수로 한정한다.
export const missingCategoryMockTickets = () => unclassifiedMockTickets().filter(t=>!t.category)
export const openClassificationMockTickets = () => USE_MOCK_TICKET ? allStaffTickets().filter(t=>reports.get(t.id)?.status==='OPEN') : []
export function requestClassificationMock(id:number, reason:string, suggestedInquiryType?: { code: string; name: string }, reporter?: UserRef) {
  enabled();requireReady(id);if(!reason.trim())throw new Error('요청 사유를 입력해 주세요.')
  if(reports.get(id)?.status==='OPEN')throw new Error('이미 재분류 검토 중이에요.')
  if(reports.get(id)?.status==='REJECTED')throw new Error('반려된 문의는 다시 요청할 수 없어요.')
  reports.set(id,{status:'OPEN',reason:reason.trim(),suggestedInquiryType,reporter});record(id,'재분류 요청',reason.trim());touch(id)
}
export function rejectClassificationMock(id:number, reason:string, resolvedBy?: UserRef) {
  enabled();requireReady(id);const report=reports.get(id)
  if(!reason.trim())throw new Error('반려 사유를 입력해 주세요.')
  if(report?.status!=='OPEN')throw new Error('검토할 요청이 없어요.')
  reports.set(id,{...report,status:'REJECTED',resolution:reason.trim(),resolvedBy});record(id,'재분류 반려',reason.trim());touch(id)
}
export function changeClassificationMock(id:number, code:CategoryCode, reason:string) {
  enabled();const t=findStaffTicket(id)
  if(!t)throw new Error('접수를 찾을 수 없어요.')
  requireReady(id)
  if(t.jiraSyncStatus!=='SYNCED')throw new Error('ITSM 연동 완료 후 변경할 수 있어요.')
  if(!reason.trim())throw new Error('변경 사유를 입력해 주세요.')
  if(pending.has(id))throw new Error('분류 반영을 먼저 확인해 주세요.')
  const label=t.category?'재분류':'분류 지정'
  const info=CATEGORIES[code]
  mutateSeed(id,t=>{const changed=t.group?.name!==info.groupName;t.category={code,name:info.name};t.inquiryType={code:code+'-01',name:info.name+' 문의'};t.group={id:GROUP_ID[info.groupName],name:info.groupName};if(changed){t.assignee=null;t.assignStatus='PENDING'};t.needsAdmin=!t.assignee})
  pending.add(id)
  record(id,label,reason.trim())
  const report=reports.get(id);if(report?.status==='OPEN')reports.set(id,{...report,status:'RESOLVED',resolution:reason.trim()})
  touch(id)
  return {...findStaffTicket(id)!}
}
export function confirmClassificationMock(id:number) {
  enabled();requireReady(id);pending.delete(id)
  // 그룹이 달라지면 가용한 담당자를 자동 선정한다. 같은 그룹이면 유지한다.
  mutateSeed(id,t=>{if(!t.assignee){const m=(GROUP_STAFF[t.group?.name??'']??[]).filter(m=>m.jira&&m.avail).sort((a,b)=>{const x=workloadOf(a.id),y=workloadOf(b.id);return (x.rdy+x.wip)-(y.rdy+y.wip)||a.employeeNo.localeCompare(b.employeeNo)})[0];if(m)t.assignee={id:m.id,name:m.name,employeeNo:m.employeeNo}}t.assignStatus=t.assignee?'ASSIGNED':'NEEDS_ADMIN';t.needsAdmin=!t.assignee})
  return {...findStaffTicket(id)!}
}
