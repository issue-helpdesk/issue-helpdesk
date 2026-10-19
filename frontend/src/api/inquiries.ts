/**
 * 문의 목록 API 어댑터 (사이드바의 "최근 문의"와 문의 내역). (시스템 설계서 9.2: GET /inquiries)
 * 문의 한 건의 대화·접수는 chat.ts 에 있다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK } from '../core/config'
import { toSummary } from './inquiryState'
import { recordsOf, subscribe } from './mock/chatStore'
import './mock/chatMock'
import { ok, type ApiResult, type InquirySummary } from './types'

/** 서버를 다시 읽는 간격(ms) */
const POLL_MS = 8000

/** 로그인한 사용자의 문의 목록 (최근 활동 순). 서버는 토큰으로 사용자를 구분한다. */
export async function listMyInquiries(userId: string): Promise<ApiResult<InquirySummary[]>> {
  if (USE_MOCK) {
    await sleep(150) // 응답 지연 흉내
    return ok(recordsOf(userId).map((r) => toSummary(r.inquiry)))
  }
  return request<InquirySummary[]>('/inquiries')
}

/**
 * 문의 목록이 바뀔 때마다 알려 준다. (새 문의, 담당자 진행 상황, 새 답변 표시)
 * 모의 모드에서는 저장소 변경을, 서버 모드에서는 주기적 조회를 쓴다. 돌려주는 함수를 부르면 구독이 끝난다.
 */
export function watchMyInquiries(userId: string, onChange: (list: InquirySummary[]) => void): () => void {
  const load = () => {
    listMyInquiries(userId).then((r) => {
      if (r.ok) onChange(r.data)
    })
  }
  load()
  if (USE_MOCK) return subscribe(load)
  const timer = setInterval(load, POLL_MS)
  return () => clearInterval(timer)
}
