/**
 * 문의 진행 상태를 색 토큰 이름으로 바꾼다.
 * 색은 assets/tokens.css 의 `--s-{이름}-fg / -dot` 변수이며, 의미는 항상 글자 라벨이 함께 전한다. (디자인 가이드)
 */
import type { DisplayStatus, InquiryStateKind } from '../api/types'

export const STATE_TONE: Record<InquiryStateKind, string> = {
  progress: 'prog', // 처리 중
  assigned: 'asg', // 담당자 배정
  received: 'recv', // 접수
  resolved: 'ok', // 해결 완료
  ai: 'ok', // AI 해결
  warn: 'warn', // 주의
  needs_reply: 'need', // 추가 답변 필요
  reassigned: 're', // 재배정
  awaiting_confirm: 'need', // 해결 확인 대기
}

/**
 * 화면에 보일 상태 이름·색·보조 라벨 (디자인 가이드 v1.4 "표시명과 내부 코드").
 * 서버가 준 stateLabel·stateKind 는 그대로 두고, 상태 값(displayStatus)으로 화면 표시만 정한다.
 * - unconfirmed(AI 답변 뒤 선택 전) · awaiting_confirm(담당자 처리 완료 뒤 선택 전)은 이름을 "해결 확인 대기"로 통일하고
 *   보조 라벨 "AI 안내" / "담당자 처리"로 구분한다. 두 코드와 필터 값은 합치지 않는다.
 * - 서버 이름이 "담당자 배정"(RDY)이면 "담당자 배정 완료" + 보조 라벨 "처리 대기"로 보인다. "담당자 확인 중" 등은 그대로 둔다.
 */
export function stateView(s: { displayStatus: DisplayStatus; stateLabel: string; stateKind: InquiryStateKind }): { label: string; tone: string; sub: string } {
  if (s.displayStatus === 'unconfirmed') return { label: '해결 확인 대기', tone: 'need', sub: 'AI 안내' }
  if (s.displayStatus === 'awaiting_confirm') return { label: '해결 확인 대기', tone: 'need', sub: '담당자 처리' }
  if (s.displayStatus === 'assigned' && s.stateKind === 'assigned' && (s.stateLabel === '담당자 배정' || s.stateLabel === '담당자 배정 완료')) {
    return { label: '담당자 배정 완료', tone: 'asg', sub: '처리 대기' }
  }
  return { label: s.stateLabel, tone: STATE_TONE[s.stateKind], sub: '' }
}
