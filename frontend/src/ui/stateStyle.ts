/**
 * 문의 진행 상태를 색 토큰 이름으로 바꾼다.
 * 색은 assets/tokens.css 의 `--s-{이름}-fg / -dot` 변수이며, 의미는 항상 글자 라벨이 함께 전한다. (디자인 가이드)
 */
import type { InquiryStateKind } from '../api/types'

export const STATE_TONE: Record<InquiryStateKind, string> = {
  progress: 'prog', // 처리 중
  assigned: 'asg', // 담당자 배정
  received: 'recv', // 접수
  resolved: 'ok', // 해결 완료
  ai: 'ok', // AI 해결
  warn: 'warn', // 미확인 · 주의
}
