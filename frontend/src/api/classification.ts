/** 재분류는 모의·서버에서 같은 화면을 사용한다. TK-15~18, RF-02. */
import { request } from '../core/apiClient'
import { SERVER_INTAKE, USE_MOCK_TICKET } from '../core/config'
import type { CategoryCode } from './chatTypes'
import type { ClassificationReport, TicketDetail, UserRef } from './ticketTypes'
import { fail, ok, type ApiResult } from './types'
import { refreshTickets } from './tickets'
import { findStaffTicket, mutateSeed } from './mock/staffTickets'
import { mockInquiryTypes } from './mock/inquiryTypes'
import { changeClassificationMock, confirmClassificationMock, classificationReport, classificationEvents, requestClassificationMock, rejectClassificationMock } from './mock/classificationMock'

export interface ClassificationType { id: number; code: string; name: string; categoryCode: CategoryCode; defaultGroup: { id: number; name: string }; isActive: boolean }
const unavailable = () => fail('NOT_IMPLEMENTED', '준비 중이에요. 아직 변경 내용은 저장되지 않아요.')
const readyOnly = (ticket: TicketDetail) => ticket.workStatus === 'RDY' ? null : fail('TICKET_INVALID_TRANSITION', '처리 대기 상태에서만 재분류할 수 있어요.')

export async function listClassificationTypes() {
  if (USE_MOCK_TICKET) return ok(mockInquiryTypes())
  const r = await request<{ items: ClassificationType[] }>('/inquiry-types?isActive=true')
  return r.ok ? ok(r.data.items.filter((t) => t.isActive)) : r
}

export async function listClassificationReports(id: number): Promise<ApiResult<ClassificationReport[]>> {
  if (!USE_MOCK_TICKET) {
    const r = await request<{ items: ClassificationReport[] }>(`/tickets/${id}/classification-reports`)
    return r.ok ? ok(r.data.items) : r
  }
  const report = classificationReport(id)
  const ticket = findStaffTicket(id)
  if (!report || !ticket) return ok([])
  const events = classificationEvents(id)
  return ok([{
    id, ticketId: id, reporter: report.reporter ?? ticket.assignee ?? ticket.requester,
    reason: report.reason, suggestedInquiryType: report.suggestedInquiryType ?? null, status: report.status,
    resolvedBy: report.resolvedBy ?? null, resolutionNote: report.resolution ?? null,
    createdAt: events[0]?.at ?? ticket.createdAt,
    resolvedAt: report.status === 'OPEN' ? null : events.at(-1)?.at ?? null,
  }])
}

export async function requestClassification(ticket: TicketDetail, reason: string, suggested: ClassificationType | undefined, reporter: UserRef): Promise<ApiResult<ClassificationReport>> {
  const blocked = readyOnly(ticket)
  if (blocked) return blocked
  if (!reason.trim() || reason.trim().length > 1000) return fail('VALIDATION_ERROR', '요청 사유를 1~1,000자로 입력해 주세요.')
  if (!USE_MOCK_TICKET && !SERVER_INTAKE) return unavailable()
  // 반려 이력은 상세의 열린 신고에 없으므로 제출 직전에도 전체 신고 이력을 확인한다.
  const history = await listClassificationReports(ticket.id)
  if (!history.ok) return history
  if (history.data.some((r) => r.status === 'REJECTED')) return fail('CLASSIFICATION_REPORT_REJECTED', '반려된 문의는 다시 재분류를 요청할 수 없어요.')
  if (history.data.some((r) => r.status === 'OPEN')) return fail('CLASSIFICATION_REPORT_ALREADY_OPEN', '이미 재분류 검토 중이에요.')
  if (!USE_MOCK_TICKET) {
    const r = await request<ClassificationReport>(`/tickets/${ticket.id}/classification-reports`, { method: 'POST', body: JSON.stringify({ reason: reason.trim(), ...(suggested ? { suggestedInquiryTypeId: suggested.id } : {}) }) })
    if (r.ok) refreshTickets()
    return r
  }
  requestClassificationMock(ticket.id, reason, suggested, reporter)
  refreshTickets()
  const r = await listClassificationReports(ticket.id)
  return r.ok ? ok(r.data[0]) : r
}

export async function rejectClassification(ticket: TicketDetail, reportId: number, reason: string, actor: UserRef): Promise<ApiResult<ClassificationReport>> {
  const blocked = readyOnly(ticket)
  if (blocked) return blocked
  if (!reason.trim() || reason.trim().length > 1000) return fail('VALIDATION_ERROR', '반려 사유를 1~1,000자로 입력해 주세요.')
  if (!USE_MOCK_TICKET && !SERVER_INTAKE) return unavailable()
  if (!USE_MOCK_TICKET) {
    const r = await request<ClassificationReport>(`/tickets/${ticket.id}/classification-reports/${reportId}`, { method: 'PATCH', body: JSON.stringify({ status: 'REJECTED', resolutionNote: reason.trim() }) })
    if (r.ok) refreshTickets()
    return r
  }
  rejectClassificationMock(ticket.id, reason, actor)
  refreshTickets()
  const r = await listClassificationReports(ticket.id)
  return r.ok ? ok(r.data[0]) : r
}

export async function saveClassification(ticket: TicketDetail, type: ClassificationType, reason: string) {
  const blocked = readyOnly(ticket)
  if (blocked) return blocked
  if (!reason.trim() || reason.trim().length > 500) return fail('VALIDATION_ERROR', '분류 지정 사유를 1~500자로 입력해 주세요.')
  if (USE_MOCK_TICKET) {
    changeClassificationMock(ticket.id, type.categoryCode, reason)
    const t = confirmClassificationMock(ticket.id)
    mutateSeed(ticket.id, (row) => { row.inquiryType = { code: type.code, name: type.name } })
    t.inquiryType = { code: type.code, name: type.name }
    refreshTickets()
    return ok(t)
  }
  if (!SERVER_INTAKE) return unavailable()
  const r = await request<TicketDetail>(`/tickets/${ticket.id}/classification`, { method: 'PUT', body: JSON.stringify({ inquiryTypeId: type.id, reason: reason.trim() }) })
  if (r.ok) refreshTickets()
  return r
}
