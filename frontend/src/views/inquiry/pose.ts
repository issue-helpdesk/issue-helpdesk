/**
 * 대화 속 잇슈의 모습 (design/ITssue-Prototype.html 의 poseOf·poseLbl 과 같은 규칙).
 * 접수 진행 카드가 나오기 전은 기본, 카드부터는 처리 중, 그 카드의 Ticket 이 해결 완료(CLS)이면 완료다.
 */
import type { Inquiry } from '../../api/chatTypes'
import type { Pose } from '../../ui/poseImages'

/** idx 번째 메시지에 붙는 잇슈의 모습 */
export function poseOf(inquiry: Inquiry, idx: number): Pose {
  const m = inquiry.messages[idx]
  if (m?.card === 'ticket') {
    const t = m.ticketSnapshot ?? inquiry.ticket
    return t?.workStatus === 'CLS' ? 'done' : 'handoff'
  }
  for (let k = 0; k < idx; k++) if (inquiry.messages[k].card === 'ticket') return 'handoff'
  return 'base'
}

/** 모습이 바뀐 첫 답변에만 붙는 작은 상태 글 ("처리 중" · "완료"). 같은 모습이 이어지면 비운다. */
export function poseLabel(inquiry: Inquiry, idx: number, pose: Pose): string {
  if (pose === 'base') return ''
  const text = pose === 'done' ? '완료' : '처리 중'
  for (let j = idx - 1; j >= 0; j--) {
    const p = inquiry.messages[j]
    if (p.role === 'assistant' && !p.typing) return poseOf(inquiry, j) === pose ? '' : text
  }
  return text
}

/** 대화 화면 상단에 보여 줄 모습: 마지막 AI 답변의 모습 */
export function latestPose(inquiry: Inquiry): Pose {
  for (let k = inquiry.messages.length - 1; k >= 0; k--) if (inquiry.messages[k].role === 'assistant') return poseOf(inquiry, k)
  return 'base'
}
