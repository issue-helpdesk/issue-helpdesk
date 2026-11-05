/**
 * FAQ API 어댑터 (제안 기능, PRD 4.16 · SRS FAQ-01).
 * 본인에게 열람이 허용된 Guide를 출처로 하는 FAQ 목록을 돌려준다. 열람해도 문의는 접수되지 않는다.
 *   GET /faqs         FQ-01 FAQ 목록 (Page). 출처는 주지 않는다
 *   GET /faqs/{id}    FQ-02 FAQ 상세. 근거 Guide 출처(sources)가 들어 있다
 *   POST /faqs        FQ-03 FAQ 등록 (관리자)
 *   PATCH /faqs/{id}  FQ-04 FAQ 수정. 게시 중단·재게시는 isActive
 *   DELETE /faqs/{id} FQ-05 FAQ 삭제 (관리자)
 * 서버 모드에서는 목록을 모두 읽어 화면의 모양으로 바꾸고, 출처는 FAQ 를 열 때 상세에서 읽는다 (FAQ 마다 요청하지 않으려고).
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK_FAQ } from '../core/config'
import type { Page } from './inquiries'
import { MOCK_FAQS } from './mock/faqs'
import type { CategoryCode, GuideSource } from './chatTypes'
import { fail, ok, type ApiResult, type Faq } from './types'

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

const toFaq = (f: ServerFaq): Faq => ({ id: f.faqCode, serverId: f.id, categoryCode: f.categoryCode, question: f.question, answer: f.answer, sources: [], active: f.isActive })

/** 모의 FAQ 저장소 (등록·게시 중단·삭제가 이 목록을 바꾼다). 새로고침하면 처음으로 돌아간다 */
let mockStore: Faq[] = MOCK_FAQS.map((f) => ({ ...f, active: true }))
/** 테스트에서 모의 FAQ 를 처음 상태로 되돌린다 */
export function resetFaqMock() {
  mockStore = MOCK_FAQS.map((f) => ({ ...f, active: true }))
}

/** 게시 출처 조건을 못 채워 서버가 거절했을 때 보여 줄 안내 (409 FAQ_SOURCE_NOT_PUBLIC) */
const SOURCE_HINT = '전 직원용 가이드 출처가 연결되어 있어야 게시할 수 있어요. 먼저 "게시 안 함"으로 등록하고, 가이드를 올려 출처가 연결된 뒤에 게시해 주세요.'
const explain = <T,>(r: ApiResult<T>): ApiResult<T> => (!r.ok && r.error.code === 'FAQ_SOURCE_NOT_PUBLIC' ? fail(r.error.code, SOURCE_HINT) : r)

/**
 * FAQ 목록. 관리자(admin=true)는 게시 중단된 FAQ 도 함께 받아 다시 게시할 수 있다. 그 밖에는 게시 중인 FAQ 만 보인다.
 */
export async function listFaqs(admin = false): Promise<ApiResult<Faq[]>> {
  if (USE_MOCK_FAQ) {
    await sleep(200) // 응답 지연 흉내
    return ok(mockStore.filter((f) => admin || f.active !== false).map((f) => ({ ...f })))
  }
  const out: Faq[] = []
  for (let page = 1; page <= MAX_PAGES; page++) {
    const r = await request<Page<ServerFaq>>(`/faqs?page=${page}&size=${PAGE_SIZE}&sort=faqCode,asc`)
    if (!r.ok) return r
    // 서버는 관리자에게 비게시 FAQ 도 준다. 관리자 화면만 그것을 보여 준다
    out.push(...r.data.items.filter((f) => admin || f.isActive).map(toFaq))
    if (page >= r.data.totalPages) break
  }
  return ok(out)
}

/** FAQ 한 건의 근거 Guide 출처. 서버 모드에서만 쓴다 (모의 FAQ 는 출처를 이미 갖고 있다) */
export async function getFaqSources(serverId: number): Promise<ApiResult<GuideSource[]>> {
  const r = await request<ServerFaqDetail>(`/faqs/${serverId}`)
  if (!r.ok) return r
  return ok(r.data.sources.map((s) => ({ docCode: s.docCode, title: s.title, version: s.version, section: s.location ?? '', excerpt: '', documentId: s.documentId })))
}

export interface FaqInput {
  categoryCode: CategoryCode
  question: string
  answer: string
  keywords: string[]
  /** 게시 여부. 서버는 게시하려면 전 직원용 가이드 출처가 이미 연결돼 있어야 한다 */
  isActive: boolean
  /** 출처로 연결할 가이드. 서버는 문서 ID 만 받고(최대 20개), 모의는 출처 줄을 만들 정보를 쓴다 */
  sources?: { documentId: number; docCode: string; title: string; version: string }[]
}

/** 서버로 보내는 본문. 화면용 출처 정보(sources)는 빼고 문서 ID 목록(sourceDocumentIds)으로 바꾼다 */
const bodyOf = (input: Partial<FaqInput>) => {
  const { sources, ...rest } = input
  return JSON.stringify(sources ? { ...rest, sourceDocumentIds: sources.map((s) => s.documentId) } : rest)
}
const toSources = (input: Partial<FaqInput>): GuideSource[] => (input.sources ?? []).map((s) => ({ docCode: s.docCode, title: s.title, version: s.version, section: '', excerpt: '', documentId: s.documentId }))

/** FAQ 등록 (FQ-03, 관리자). FAQ 번호는 서버가 다음 번호로 발급한다 */
export async function createFaq(input: FaqInput): Promise<ApiResult<Faq>> {
  if (USE_MOCK_FAQ) {
    await sleep(150)
    const n = Math.max(0, ...mockStore.map((f) => Number(f.id.replace(/\D/g, '')) || 0)) + 1
    const faq: Faq = { id: `FAQ-${String(n).padStart(3, '0')}`, categoryCode: input.categoryCode, question: input.question, answer: input.answer, sources: toSources(input), active: input.isActive }
    mockStore = [...mockStore, faq]
    return ok({ ...faq })
  }
  const r = await request<ServerFaq>('/faqs', { method: 'POST', body: bodyOf(input) })
  return explain(r.ok ? ok(toFaq(r.data)) : r)
}

/** FAQ 수정 (FQ-04). 보낸 항목만 바뀌고, 출처(sources)를 보내면 그 목록으로 통째로 바뀐다. 게시 여부(isActive)도 함께 보낼 수 있다 */
export async function updateFaq(f: Faq, input: Partial<FaqInput>): Promise<ApiResult<Faq>> {
  if (USE_MOCK_FAQ) {
    await sleep(150)
    const hit = mockStore.find((x) => x.id === f.id)
    if (!hit) return fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
    if (input.categoryCode) hit.categoryCode = input.categoryCode
    if (input.question !== undefined) hit.question = input.question
    if (input.answer !== undefined) hit.answer = input.answer
    if (input.sources) hit.sources = toSources(input)
    if (input.isActive !== undefined) hit.active = input.isActive
    return ok({ ...hit })
  }
  if (f.serverId === undefined) return fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
  const r = await request<ServerFaq>(`/faqs/${f.serverId}`, { method: 'PATCH', body: bodyOf(input) })
  return explain(r.ok ? ok(toFaq(r.data)) : r)
}

/** 게시 중단·다시 게시 (FQ-04). 게시 중단은 조건 없이 되고, 다시 게시할 때는 출처 조건을 서버가 확인한다 */
export async function setFaqActive(f: Faq, isActive: boolean): Promise<ApiResult<Faq>> {
  if (USE_MOCK_FAQ) {
    await sleep(120)
    const hit = mockStore.find((x) => x.id === f.id)
    if (!hit) return fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
    hit.active = isActive
    return ok({ ...hit })
  }
  if (f.serverId === undefined) return fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
  const r = await request<ServerFaq>(`/faqs/${f.serverId}`, { method: 'PATCH', body: JSON.stringify({ isActive }) })
  return explain(r.ok ? ok(toFaq(r.data)) : r)
}

/** FAQ 삭제 (FQ-05). 되돌릴 수 없다. 잠시 내리려면 게시 중단을 쓴다 */
export async function deleteFaq(f: Faq): Promise<ApiResult<null>> {
  if (USE_MOCK_FAQ) {
    await sleep(120)
    const before = mockStore.length
    mockStore = mockStore.filter((x) => x.id !== f.id)
    return mockStore.length < before ? ok(null) : fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
  }
  if (f.serverId === undefined) return fail('FAQ_NOT_FOUND', 'FAQ를 찾을 수 없어요.')
  return request<null>(`/faqs/${f.serverId}`, { method: 'DELETE' })
}
