/** 가이드 관리의 "AI 가이드 제안" 탭 이름 옆에 보일 검토 대기 건수. 서버 연결 환경에서는 처음 한 번 목록을 읽어 온다 */
import { useEffect, useSyncExternalStore } from 'react'
import { CASES_FROM_SERVER, getAllCases, loadCases, subscribeAllCases } from '../../api/caseClusters'

export function useReviewCount() {
  useEffect(() => {
    if (CASES_FROM_SERVER) void loadCases()
  }, [])
  return useSyncExternalStore(subscribeAllCases, getAllCases).filter((c) => c.state === 'review').length
}
