import { request } from '../core/apiClient'
import { SERVER_INTAKE, USE_MOCK_TICKET } from '../core/config'
import type { CategoryCode } from './chatTypes'
import type { TicketDetail } from './ticketTypes'
import { fail, ok } from './types'
import { refreshTickets } from './tickets'
import { mutateSeed } from './mock/staffTickets'
import { mockInquiryTypes } from './mock/inquiryTypes'
import { changeClassificationMock, confirmClassificationMock } from './mock/classificationMock'

export interface ClassificationType {id:number;code:string;name:string;categoryCode:CategoryCode;defaultGroup:{id:number;name:string};isActive:boolean}
export async function listClassificationTypes() {
 if(USE_MOCK_TICKET)return ok(mockInquiryTypes())
 const r=await request<{items:ClassificationType[]}>('/inquiry-types?isActive=true')
 return r.ok?ok(r.data.items.filter(t=>t.isActive)):r
}
export async function saveClassification(ticket:TicketDetail,type:ClassificationType,reason:string) {
 if(ticket.workStatus!=='RDY')return fail('TICKET_INVALID_TRANSITION','처리 대기 상태에서만 분류를 변경할 수 있어요.')
 if(!reason.trim())return fail('VALIDATION_ERROR','분류 지정 사유를 입력해 주세요.')
 if(USE_MOCK_TICKET){
  changeClassificationMock(ticket.id,type.categoryCode,reason)
  // 유형·그룹은 RF와 같은 목 메타데이터를 사용하고, 자동배정 결과까지 모의 처리한다.
  const t=confirmClassificationMock(ticket.id)
  mutateSeed(ticket.id,row=>{row.inquiryType={code:type.code,name:type.name}})
  t.inquiryType={code:type.code,name:type.name}
  refreshTickets()
  return ok(t)
 }
 if(!SERVER_INTAKE)return fail('NOT_IMPLEMENTED','준비 중입니다. 아직 변경 내용은 저장되지 않습니다.')
 const r=await request<TicketDetail>(`/tickets/${ticket.id}/classification`,{method:'PUT',body:JSON.stringify({inquiryTypeId:type.id,reason:reason.trim()})})
 if(r.ok)refreshTickets()
 return r
}
