/**
 * 모의 접수의 업무 상태 이력 기록장 (서버의 ticket_status_history 와 같은 역할).
 * 담당자 화면에서 바꾼 상태뿐 아니라 문의자 화면에서 누른 해결·미해결, 시연의 단계 진행도 여기에 남겨서,
 * 접수 상세의 처리 이력이 실제 서버처럼 모든 상태 변화를 보여 준다. (staffTickets·chatEngine 이 함께 쓴다)
 */
import type { AssignmentLog, StatusHistory } from '../ticketTypes'

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
/** 모의 접수의 담당자 배정 이력 (서버의 assignment_logs). 이 화면에서 한 재배정을 남긴다 */
const assignLogs = new Map<number, AssignmentLog[]>()
let assignSeq = 1
export function addAssignmentLog(ticketId: number, a: Omit<AssignmentLog, 'id' | 'ticketId'>) {
  const list = assignLogs.get(ticketId) ?? []
  list.push({ ...a, id: 7000 + assignSeq++, ticketId })
  assignLogs.set(ticketId, list)
}
export const assignmentLogsOf = (ticketId: number): AssignmentLog[] => assignLogs.get(ticketId) ?? []
export function resetHistoryLog() {
  explicitHistory.clear()
  histSeq = 1
  assignLogs.clear()
  assignSeq = 1
}
