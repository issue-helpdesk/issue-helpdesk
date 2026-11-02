/**
 * FAQ API 어댑터 (제안 기능, PRD 4.16 · SRS FAQ-01).
 * 본인에게 열람이 허용된 Guide를 출처로 하는 FAQ 목록을 돌려준다. 열람해도 문의는 접수되지 않는다.
 *   GET /faqs         FQ-01 FAQ 목록 (Page). 출처는 주지 않는다
 *   GET /faqs/{id}    FQ-02 FAQ 상세. 근거 Guide 출처(sources)가 들어 있다
 * 서버 모드에서는 목록을 모두 읽어 화면의 모양으로 바꾸고, 출처는 FAQ 를 열 때 상세에서 읽는다 (FAQ 마다 요청하지 않으려고).
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK_FAQ } from '../core/config'
import type { Page } from './inquiries'
import { MOCK_FAQS } from './mock/faqs'
import type { CategoryCode, GuideSource } from './chatTypes'
import { ok, type ApiResult, type Faq } from './types'

/** 서버 FAQ (FQ-01·02) 중 화면이 쓰는 부분 */
interface ServerFaq {
  id: number
  faqCode: string
  categoryCode: CategoryCode
  question: string
  answer: string
  isActive: boolean
}
interface ServerFaqDetail extends ServerFaq {
  sources: { documentId: number; docCode: string; title: string; version: string; location: string | null }[]
}

/** 한 번에 읽는 개수 (서버 최대) */
const PAGE_SIZE = 100
/** 안전장치: 이 쪽수를 넘게 읽지 않는다 */
const MAX_PAGES = 5

const toFaq = (f: ServerFaq): Faq => ({ id: f.faqCode, serverId: f.id, categoryCode: f.categoryCode, question: f.question, answer: f.answer, sources: [] })

export async function listFaqs(): Promise<ApiResult<Faq[]>> {
  if (USE_MOCK_FAQ) {
    await sleep(200) // 응답 지연 흉내
    return ok(MOCK_FAQS)
  }
  const out: Faq[] = []
  for (let page = 1; page <= MAX_PAGES; page++) {
    const r = await request<Page<ServerFaq>>(`/faqs?page=${page}&size=${PAGE_SIZE}&sort=faqCode,asc`)
    if (!r.ok) return r
    // 관리자는 비게시 FAQ 도 받는다. 이 화면은 게시 중인 것만 보여 준다
    out.push(...r.data.items.filter((f) => f.isActive).map(toFaq))
    if (page >= r.data.totalPages) break
  }
  return ok(out)
}

/** FAQ 한 건의 근거 Guide 출처. 서버 모드에서만 쓴다 (모의 FAQ 는 출처를 이미 갖고 있다) */
export async function getFaqSources(serverId: number): Promise<ApiResult<GuideSource[]>> {
  const r = await request<ServerFaqDetail>(`/faqs/${serverId}`)
  if (!r.ok) return r
  return ok(r.data.sources.map((s) => ({ docCode: s.docCode, title: s.title, version: s.version, section: s.location ?? '', excerpt: '' })))
}
