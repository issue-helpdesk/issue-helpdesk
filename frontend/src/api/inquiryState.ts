/**
 * 문의 한 건의 "화면 표시 상태"를 정한다. (PRD 4.8)
 * 접수 후에는 Ticket 업무 상태(처리 대기·처리 중·해결 확인 대기·해결 완료)를 따르고, 그 전에는 문의 상태를 따른다.
 * 실제 서버에서는 문의 목록 응답이 stateLabel·stateKind 를 직접 준다.
 */
import { INQUIRY_STATUS_LABEL, WORK_STATUS } from './catalog'
import type { Inquiry } from './chatTypes'
import type { InquirySummary, InquiryStateKind } from './types'

/** 상태 배지 색 이름(tone) → 목록용 상태 종류 */
const TONE_KIND: Record<string, InquiryStateKind> = { recv: 'received', prog: 'progress', need: 'awaiting_confirm', ok: 'resolved', asg: 'assigned', warn: 'warn' }

export function inquiryState(inq: Inquiry): { label: string; kind: InquiryStateKind; tone: string } {
  const t = inq.ticket
  if (t) {
    // Jira 생성이나 배정에 실패하거나 생성 결과를 아직 모르면(VERIFYING) 관리자가 확인한다.
    // 문의자에게는 실패와 불명확을 나누지 않고 모두 확인 중으로 안내한다.
    if (t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING' || t.assignStatus === 'NEEDS_ADMIN') return { label: '담당자 확인 중', kind: 'assigned', tone: 'asg' }
    if (t.needReply) return { label: '추가 답변 필요', kind: 'needs_reply', tone: 'need' }
    if (t.workStatus && t.assignStatus === 'ASSIGNED') {
      const s = WORK_STATUS[t.workStatus]
      return { label: s.label, kind: TONE_KIND[s.tone], tone: s.tone }
    }
  }
  const label = INQUIRY_STATUS_LABEL[inq.status]
  switch (inq.status) {
    case 'AI_RESOLVED':
      return { label, kind: 'ai', tone: 'ok' }
    case 'UNCONFIRMED':
      return { label, kind: 'warn', tone: 'warn' }
    case 'CLOSED_UNRESOLVED':
      return { label, kind: 'received', tone: 'recv' }
    case 'RECEIVED':
    case 'HANDED_OFF':
      return { label, kind: 'assigned', tone: 'asg' }
    default:
      return { label, kind: 'progress', tone: 'prog' }
  }
}

/** 문의를 사이드바·목록용 요약으로 바꾼다 */
export function toSummary(inq: Inquiry): InquirySummary {
  const s = inquiryState(inq)
  return { id: inq.id, title: inq.title, stateLabel: s.label, stateKind: s.kind, unread: inq.unread, updatedAt: inq.updatedAt }
}
