/**
 * 모의 접수의 업무 상태 이력 기록장 (서버의 ticket_status_history 와 같은 역할).
 * 담당자 화면에서 바꾼 상태뿐 아니라 문의자 화면에서 누른 해결·미해결, 시연의 단계 진행도 여기에 남겨서,
 * 접수 상세의 처리 이력이 실제 서버처럼 모든 상태 변화를 보여 준다. (staffTickets·chatEngine 이 함께 쓴다)
 */
import type { StatusHistory } from '../ticketTypes'

/** 문의자 접수의 접수 id = 이 값 + 문의 id */
export const CHAT_ID_BASE = 100_000

const explicitHistory = new Map<number, StatusHistory[]>()
let histSeq = 1

export function addHistory(ticketId: number, h: Omit<StatusHistory, 'id' | 'ticketId'>) {
  const list = explicitHistory.get(ticketId) ?? []
  list.push({ ...h, id: 9000 + histSeq++, ticketId })
  explicitHistory.set(ticketId, list)
}
export const explicitHistoryOf = (ticketId: number): StatusHistory[] => explicitHistory.get(ticketId) ?? []
export function resetHistoryLog() {
  explicitHistory.clear()
  histSeq = 1
}
