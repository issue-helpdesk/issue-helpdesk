/**
 * 이어갈 수 있는 문의를 다시 열 때 보이는 선택 창 (design 프로토타입의 이어가기 창과 같은 규칙).
 * 미확인 문의(AI 답변 뒤 해결·미해결 선택 전)를 문의 내역이나 사이드바에서 열면 뜨고, 방금 만든 대화에서는 뜨지 않는다.
 * 담당자 연결 없이 종료한 문의(미연결·접수 취소)와 AI 해결, 해결 완료는 이어갈 수 없다. 서버(IQ-06)도 이 문의들을 받지 않는다 (요청 R-28).
 */
import { isUnconfirmed } from '../../api/inquiryState'
import type { Inquiry } from '../../api/chatTypes'

/** ua=미확인(해결·미해결 선택 전) */
export type EntryKind = 'ua'

export function entryKindOf(inq: Inquiry): EntryKind | null {
  if (inq.ticket) return null
  return isUnconfirmed(inq) ? 'ua' : null
}

export const ENTRY_POPUP: Record<EntryKind, { title: string; body: string }> = {
  ua: { title: '이전 문의를 이어서 진행할까요?', body: '아직 해결 여부를 확인하지 않은 문의가 있어요. 이전 대화를 이어가거나 새 문의를 시작할 수 있어요.' },
}

/** 끝난 문의의 입력창 자리에 보여 주는 상태 안내. 입력창은 잠그고 안내만 한다. */
export function endedMessage(inq: Inquiry): string | null {
  if (inq.ticket) return inq.ticket.workStatus === 'CLS' ? '처리가 완료되어 종료된 문의예요.' : null
  if (inq.status === 'AI_RESOLVED') return 'AI 안내로 해결된 문의예요.'
  if (inq.status === 'CLOSED_UNRESOLVED') return inq.draftState === 'cancel' ? '티켓을 접수하지 않고 종료한 문의예요. 새 문의로 시작해 주세요.' : '담당자 연결 없이 종료한 문의예요. 이어갈 수 없어서 새 문의로 시작해 주세요.'
  return inq.step === 'closed' ? '종료된 문의예요.' : null
}
