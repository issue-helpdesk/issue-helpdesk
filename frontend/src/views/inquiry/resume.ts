/**
 * 이어갈 수 있는 문의를 다시 열 때 보이는 선택 창 (design 프로토타입의 이어가기 창과 같은 규칙).
 * 미확인·미해결·미접수 종료 문의를 문의 내역이나 사이드바에서 열면 뜨고, 방금 만든 대화에서는 뜨지 않는다.
 * AI 해결과 해결 완료(CLS)는 이어갈 수 없다.
 */
import { isUnconfirmed } from '../../api/inquiryState'
import type { Inquiry } from '../../api/chatTypes'

/** ua=미확인(해결·미해결 선택 전), un=미해결, no=접수 초안 확인에서 접수하지 않고 종료 */
export type EntryKind = 'ua' | 'un' | 'no'

export function entryKindOf(inq: Inquiry): EntryKind | null {
  if (inq.ticket) return null
  if (isUnconfirmed(inq)) return 'ua'
  if (inq.status === 'CLOSED_UNRESOLVED') return inq.draftState === 'cancel' ? 'no' : 'un'
  return null
}

export const ENTRY_POPUP: Record<EntryKind, { title: string; body: string }> = {
  ua: { title: '이전 문의를 이어서 진행할까요?', body: '아직 해결 여부를 확인하지 않은 문의가 있어요. 이전 대화를 이어가거나 새 문의를 시작할 수 있어요.' },
  un: { title: '해결되지 않은 문의를 이어갈까요?', body: '이전 상담에서 문제가 해결되지 않았어요. 대화를 이어가면 담당자 연결을 다시 안내해 드릴게요.' },
  no: { title: '이전 문의를 다시 이어갈까요?', body: '담당자 연결을 위한 티켓을 접수하지 않고 종료한 문의예요. 대화를 이어가거나 새 문의를 시작할 수 있어요.' },
}

/** 끝난 문의의 입력창 자리에 보여 주는 상태 안내. 이어갈 수 있는 문의도 입력창은 잠그고 안내만 한다. */
export function endedMessage(inq: Inquiry): string | null {
  if (inq.ticket) return inq.ticket.workStatus === 'CLS' ? '처리가 완료되어 종료된 문의예요.' : null
  if (inq.status === 'AI_RESOLVED') return 'AI 안내로 해결된 문의예요.'
  if (inq.status === 'CLOSED_UNRESOLVED') return inq.draftState === 'cancel' ? '티켓을 접수하지 않고 종료한 문의예요.' : '아직 해결되지 않은 문의예요. 대화를 이어갈 수 있어요.'
  return inq.step === 'closed' ? '종료된 문의예요.' : null
}
