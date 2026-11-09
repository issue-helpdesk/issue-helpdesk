import type { TicketSummary } from '../../api/ticketTypes'

/** 확인이 필요한 이유 한 줄 */
export const linkWhy = (t: TicketSummary) => (t.transitionStatus === 'NEEDS_ADMIN' ? 'ITSM 동기화 확인 필요' : t.jiraSyncStatus === 'NEEDS_ADMIN' ? 'ITSM 생성 요청 응답 시간 초과 · 생성 여부 확인 필요' : 'ITSM 생성 결과 확인 중')
