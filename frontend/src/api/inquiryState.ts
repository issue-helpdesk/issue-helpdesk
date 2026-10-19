/**
 * 문의 한 건의 "화면 표시 상태"를 정한다. (PRD 4.8)
 * 접수 후에는 Ticket 상태(처리 대기·처리 중·해결 확인 대기·해결 완료)를 따르고, 그 전에는 대화 상태를 따른다.
 * 실제 서버에서는 문의 목록 응답이 stateLabel·stateKind 를 직접 준다.
 */
import { TICKET_STATUS } from './catalog'
import type { Inquiry } from './chatTypes'
import type { InquirySummary, InquiryStateKind } from './types'

/** 상태 배지 색 이름(tone) → 목록용 상태 종류 */
const TONE_KIND: Record<string, InquiryStateKind> = { recv: 'received', prog: 'progress', need: 'need', ok: 'resolved', asg: 'assigned', warn: 'warn' }

export function inquiryState(inq: Inquiry): { label: string; kind: InquiryStateKind; tone: string } {
  const t = inq.ticket
  if (t?.status) {
    if (t.needReply) return { label: '추가 답변 필요', kind: 'need', tone: 'need' }
    const s = TICKET_STATUS[t.status]
    return { label: s.label, kind: TONE_KIND[s.tone], tone: s.tone }
  }
  switch (inq.state) {
    case 'AI 해결':
      return { label: 'AI 해결', kind: 'ai', tone: 'ok' }
    case '미확인':
      return { label: '미확인', kind: 'warn', tone: 'warn' }
    case '미해결 종료':
      return { label: '미해결 종료', kind: 'received', tone: 'recv' }
    case '접수 완료':
    case '담당자 이관':
      return { label: inq.state, kind: 'assigned', tone: 'asg' }
    default:
      return { label: '진행 중', kind: 'progress', tone: 'prog' }
  }
}

/** 문의를 사이드바·목록용 요약으로 바꾼다 */
export function toSummary(inq: Inquiry): InquirySummary {
  const s = inquiryState(inq)
  return { id: inq.id, title: inq.title, stateLabel: s.label, stateKind: s.kind, unread: inq.unread, when: inq.when }
}
