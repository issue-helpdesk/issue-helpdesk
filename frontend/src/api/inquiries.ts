/**
 * 문의 API 어댑터 (지금은 사이드바의 "최근 문의" 목록만).
 * 대화·접수 기능을 만들면서 이 파일에 호출을 추가한다. (시스템 설계서 9.2: GET /inquiries)
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK } from '../core/config'
import { MOCK_INQUIRIES } from './mock/inquiries'
import { ok, type ApiResult, type InquirySummary } from './types'

/** 로그인한 사용자의 문의 목록 (최근 활동 순). 서버는 토큰으로 사용자를 구분한다. */
export async function listMyInquiries(userId: string): Promise<ApiResult<InquirySummary[]>> {
  if (USE_MOCK) {
    await sleep(150) // 응답 지연 흉내
    return ok(MOCK_INQUIRIES[userId] ?? [])
  }
  return request<InquirySummary[]>('/inquiries')
}
