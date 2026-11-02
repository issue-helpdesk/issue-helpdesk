/**
 * 문의 목록 API 어댑터 (사이드바의 "최근 문의"와 문의 내역). (시스템 설계서 9.2: GET /inquiries)
 * 문의 한 건의 대화·접수는 chat.ts 에 있다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import { toSummary } from './inquiryState'
import { recordsOf, subscribe } from './mock/chatStore'
import './mock/chatMock'
import { CATEGORIES } from './catalog'
import type { CategoryCode } from './chatTypes'
import { ok, type ApiResult, type DisplayStatus, type InquirySummary } from './types'

/** 서버를 다시 읽는 간격(ms) */
const POLL_MS = 8000

/** 로그인한 사용자의 문의 목록 (최근 활동 순). 서버는 토큰으로 사용자를 구분한다. */
export async function listMyInquiries(employeeNo: string): Promise<ApiResult<InquirySummary[]>> {
  if (USE_MOCK_INQUIRY) {
    await sleep(150) // 응답 지연 흉내
    return ok(recordsOf(employeeNo).map((r) => toSummary(r.inquiry)))
  }
  return request<InquirySummary[]>('/inquiries')
}

/* ------------------------------------------------------------------ 문의 내역 (조건 조회) */

/** 문의 내역의 상태 분류. API 의 displayStatus 여러 개를 묶은 것이다. */
export type ListGroup = 'in_progress' | 'ai_resolved' | 'staff' | 'awaiting_confirm' | 'resolved' | 'unresolved'

export const LIST_GROUPS: { key: ListGroup; label: string; statuses: DisplayStatus[] }[] = [
  { key: 'in_progress', label: '진행 중', statuses: ['in_progress'] },
  { key: 'ai_resolved', label: 'AI 해결', statuses: ['ai_resolved'] },
  { key: 'staff', label: '담당자 처리', statuses: ['received', 'assigned', 'progress'] },
  // 해결 확인 대기: 담당자 처리 완료 뒤(awaiting_confirm)와 AI 답변 뒤(unconfirmed). 두 값은 그대로 보내고 화면 이름만 같다.
  { key: 'awaiting_confirm', label: '해결 확인 대기', statuses: ['awaiting_confirm', 'unconfirmed'] },
  { key: 'resolved', label: '해결 완료', statuses: ['resolved'] },
  { key: 'unresolved', label: '미해결', statuses: ['unresolved'] },
]

/** 문의 한 건이 속한 상태 분류 */
export const groupOf = (s: DisplayStatus): ListGroup => LIST_GROUPS.find((g) => g.statuses.includes(s))!.key

/**
 * 문의 목록 조건 (GET /inquiries 의 Query, API 02 IQ-02).
 * 서버가 걸러 주므로 화면은 이 조건만 보낸다. 모의 모드에서는 이 파일이 같은 조건으로 걸러 준다.
 * sort 는 "기준,방향"이다. API 가 지원하는 기준은 createdAt·updatedAt·urgency 이고, title·category·displayStatus 는
 * 프로토타입의 열 정렬을 위한 임시 값이다 (서버 연결 때 지원 여부를 정한다).
 */
export interface InquiryListQuery {
  page?: number
  size?: number
  sort?: string
  displayStatus?: DisplayStatus[]
  categoryCode?: CategoryCode[]
  /** 이 날짜 00:00부터 (YYYY-MM-DD, KST) */
  createdFrom?: string
  /** 이 날짜 24:00까지 */
  createdTo?: string
  /** 제목·접수번호·가이드 문서 번호 부분 일치 */
  q?: string
}

export interface Page<T> {
  items: T[]
  page: number
  size: number
  totalCount: number
  totalPages: number
}

const toQueryString = (q: InquiryListQuery) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x))
    else p.set(k, String(v))
  }
  return p.toString()
}

/** 날짜(YYYY-MM-DD)를 그날 00:00(로컬)의 시각으로 */
const dayStart = (d: string) => new Date(`${d}T00:00:00`).getTime()

/** 문의 내역: 조건에 맞는 내 문의를 한 쪽씩 돌려준다. */
export async function listInquiries(employeeNo: string, query: InquiryListQuery = {}): Promise<ApiResult<Page<InquirySummary>>> {
  if (!USE_MOCK_INQUIRY) return request<Page<InquirySummary>>(`/inquiries?${toQueryString(query)}`)
  await sleep(150) // 응답 지연 흉내
  const { page = 1, size = 20, sort = 'updatedAt,desc', displayStatus, categoryCode, createdFrom, createdTo, q } = query
  const needle = (q ?? '').trim().toLowerCase()
  let rows = recordsOf(employeeNo).map((r) => {
    const summary = toSummary(r.inquiry)
    // 검색 대상: 제목, 접수번호, Jira 번호, 분류 이름, 근거로 쓴 가이드 문서 번호
    const docs = r.inquiry.messages.flatMap((m) => m.sources?.map((s) => s.docCode) ?? [])
    const hay = [summary.title, summary.receiptNo, summary.jiraKey, summary.categoryCode && CATEGORIES[summary.categoryCode].name, ...docs]
    return { summary, hay }
  })
  rows = rows.filter(({ summary: s, hay }) => {
    if (displayStatus?.length && !displayStatus.includes(s.displayStatus)) return false
    if (categoryCode?.length && !(s.categoryCode && categoryCode.includes(s.categoryCode))) return false
    const created = new Date(s.createdAt).getTime()
    if (createdFrom && created < dayStart(createdFrom)) return false
    if (createdTo && created >= dayStart(createdTo) + 86_400_000) return false
    if (needle && !hay.some((x) => x && String(x).toLowerCase().includes(needle))) return false
    return true
  })
  const [key, dir] = sort.split(',')
  const sign = dir === 'asc' ? 1 : -1
  const val = (s: InquirySummary): string | number => {
    switch (key) {
      case 'title':
        return s.title
      case 'category':
        return s.categoryCode ? CATEGORIES[s.categoryCode].name : '힣' // 미분류는 맨 뒤
      case 'displayStatus':
        return s.stateLabel
      case 'createdAt':
        return new Date(s.createdAt).getTime()
      default:
        return new Date(s.updatedAt).getTime()
    }
  }
  rows.sort((a, b) => {
    const x = val(a.summary)
    const y = val(b.summary)
    return (x < y ? -1 : x > y ? 1 : 0) * sign
  })
  const totalCount = rows.length
  const totalPages = Math.max(1, Math.ceil(totalCount / size))
  const p = Math.min(Math.max(1, page), totalPages)
  return ok({ items: rows.slice((p - 1) * size, p * size).map((r) => r.summary), page: p, size, totalCount, totalPages })
}

/**
 * 문의 목록이 바뀔 때마다 알려 준다. (새 문의, 담당자 진행 상황, 새 답변 표시)
 * 모의 모드에서는 저장소 변경을, 서버 모드에서는 주기적 조회를 쓴다. 돌려주는 함수를 부르면 구독이 끝난다.
 */
export function watchMyInquiries(employeeNo: string, onChange: (list: InquirySummary[]) => void): () => void {
  const load = () => {
    listMyInquiries(employeeNo).then((r) => {
      if (r.ok) onChange(r.data)
    })
  }
  load()
  if (USE_MOCK_INQUIRY) return subscribe(load)
  const timer = setInterval(load, POLL_MS)
  return () => clearInterval(timer)
}
