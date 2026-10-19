/**
 * FAQ API 어댑터 (제안 기능, PRD 4.16 · SRS FAQ-01).
 * 본인에게 열람이 허용된 Guide를 출처로 하는 FAQ 목록을 돌려준다. 열람해도 문의는 접수되지 않는다.
 * 실제 경로(GET /faqs)는 백엔드와 협의 후 확정한다. (시스템 설계서 9장 Endpoint 후보)
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK } from '../core/config'
import { MOCK_FAQS } from './mock/faqs'
import { ok, type ApiResult, type Faq } from './types'

export async function listFaqs(): Promise<ApiResult<Faq[]>> {
  if (USE_MOCK) {
    await sleep(200) // 응답 지연 흉내
    return ok(MOCK_FAQS)
  }
  return request<Faq[]>('/faqs')
}
