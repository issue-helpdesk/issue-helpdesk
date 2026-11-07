/** 가이드 관리의 "해결 사례 → 가이드 초안" 탭 이름 옆에 보일 검토 대기 건수 */
import { useSyncExternalStore } from 'react'
import { getCases, subscribeCases } from '../../api/mock/caseGuides'

export function useReviewCount() {
  return useSyncExternalStore(subscribeCases, getCases).filter((c) => c.state === 'review').length
}
