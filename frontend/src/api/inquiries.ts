/**
 * 문의 목록 API 어댑터 (사이드바의 "최근 문의"와 문의 내역). (시스템 설계서 9.2: GET /inquiries)
 * 문의 한 건의 대화·접수는 chat.ts 에 있다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import { mapSummaries, type SSummary } from './inquiryServer'
import { toSummary } from './inquiryState'
import { aiRows, type AiKind, type AiRow } from './mock/aiRows'
import { recordsOf, subscribe } from './mock/chatStore'
import './mock/chatMock'
import { CATEGORIES } from './catalog'
import type { CategoryCode } from './chatTypes'
import { formatRelative } from '../core/format'
import { pollHints, visiblePoll } from '../core/poll'
import { listUnread, watchUnread } from './notifications'
import { ok, type ApiResult, type DisplayStatus, type InquirySummary } from './types'

/** 서버를 다시 읽는 간격(ms) */
/**
 * 서버 모드에서 사이드바 문의 목록을 다시 읽는 안전 간격(ms).
 * 서버가 변화를 알려 주는 방법(푸시·알림)이 아직 없어서 이벤트로 읽는다: 처음 열 때, 탭이 다시 보일 때, 화면을 옮길 때,
 * 대화 화면이 상태 변화를 알아챘을 때(refreshInquiryList). 이 간격은 그 사이에 놓친 변화를 잡는 용도라 길게 둔다.
 */
const POLL_MS = 120_000
/** 간격·탭 복귀 조회 사이의 최소 간격(ms). 탭을 연타해도 이 안에서는 다시 읽지 않는다 */
const MIN_GAP_MS = 15_000

/** 로그인한 사용자의 문의 목록 (최근 활동 순). 서버는 토큰으로 사용자를 구분한다. */
export async function listMyInquiries(employeeNo: string): Promise<ApiResult<InquirySummary[]>> {
  if (USE_MOCK_INQUIRY) {
    await sleep(150) // 응답 지연 흉내
    return ok(recordsOf(employeeNo).map((r) => toSummary(r.inquiry)))
  }
  // 서버는 Page 로 준다. 사이드바는 최근 활동 순 몇 건만 쓴다
  const [r, news] = await Promise.all([request<Page<SSummary>>('/inquiries?size=5&sort=updatedAt,desc'), listUnread()])
  if (!r.ok) return r
  const items = mapSummaries(r.data).items
  // 처리 완료(FIN) 같은 화면 알림이 안 읽힌 문의는 새 답변 표시(unread)를 켠다
  const unread = new Map<number, number>()
  if (news.ok) for (const n of news.data) unread.set(n.inquiryId, (unread.get(n.inquiryId) ?? 0) + 1)
  return ok(items.map((i) => ({ ...i, unread: unread.get(i.id) ?? i.unread })))
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
  { key: 'unresolved', label: '미연결 종료', statuses: ['unresolved'] },
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
  if (!USE_MOCK_INQUIRY) {
    const r = await request<Page<SSummary>>(`/inquiries?${toQueryString(query)}`)
    return r.ok ? ok(mapSummaries(r.data)) : r
  }
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
  // 읽기가 겹치지 않게 합치고(읽는 중에 또 요청이 오면 끝난 뒤 한 번만 더 읽는다), 늦게 온 옛 응답이 최신 목록을 덮지 않게 한다
  let running = false
  let again = false
  let seq = 0
  let lastLoad = 0
  const load = () => {
    if (running) {
      again = true
      return
    }
    running = true
    lastLoad = Date.now()
    const mine = ++seq
    listMyInquiries(employeeNo)
      .then((r) => {
        if (r.ok && mine === seq) onChange(r.data)
      })
      .finally(() => {
        running = false
        if (again) {
          again = false
          load()
        }
      })
  }
  load()
  if (USE_MOCK_INQUIRY) return subscribe(load)
  // 간격·탭 복귀로 읽는 조회: 대화 화면이 열려 있으면 그 화면이 자기 문의를 직접 읽으니 건너뛰고, 15초 안에 또 읽지 않는다
  const poll = () => {
    if (pollHints.chatViews > 0 || Date.now() - lastLoad < MIN_GAP_MS) return
    load()
  }
  pollHints.listLoaders.add(load)
  const stop = visiblePoll(poll, POLL_MS)
  // 알림 개수(NT-02)는 가볍게 읽을 수 있으니 따로 보고, 안 읽은 알림이 바뀌면 목록을 다시 읽는다(처음 한 번은 위에서 이미 읽는다)
  let first = true
  const offUnread = watchUnread(() => {
    if (first) first = false
    else load()
  })
  return () => {
    stop()
    offUnread()
    pollHints.listLoaders.delete(load)
  }
}

/* ------------------------------------------------------------------ 관리자: AI 처리한 상담 (전체 문의의 "AI 처리") */
export type { AiKind, AiRow }

export interface AiListQuery {
  page?: number
  size?: number
  /** 기준,방향: title · cat · guide · when (모의). 서버는 createdAt·updatedAt·urgency 만 받는다 */
  sort?: string
  /** 접수 기간: 오늘 / 최근 30일 / 최근 1년 */
  per?: 'd' | 'm' | 'y' | ''
  kind?: '' | AiKind
  /** 분류 */
  categoryCode?: CategoryCode | ''
  /** 제목·번호·가이드 부분 일치 (서버는 제목·접수번호·가이드 문서 번호) */
  q?: string
}

export interface AiPage extends Page<AiRow> {
  /** 구분별 건수 (기간 조건만 적용, 구분 조건은 적용하지 않음) */
  counts: Record<'all' | AiKind, number>
}

const PER_DAYS = { d: 1, m: 30, y: 366 } as const
/** 구분 → 서버 화면 표시 상태: AI 해결 · 해결 확인 대기(AI 안내, unconfirmed) · 미해결 종료 */
const KIND_STATUS: Record<AiKind, DisplayStatus> = { ok: 'ai_resolved', pend: 'unconfirmed', unr: 'unresolved' }
const STATUS_KIND: Partial<Record<DisplayStatus, AiKind>> = { ai_resolved: 'ok', unconfirmed: 'pend', unresolved: 'unr' }

/**
 * 티켓 없이 AI 안내로 끝난 상담 (관리자). 서버는 문의 목록(IQ-02)을 displayStatus 로 걸러서 받는다.
 * 목록 응답에 사용한 가이드가 없어서 서버 모드에서는 '-' 로 보이고, 제목·분류·가이드 정렬은 서버가 받지 않는다.
 */
export async function listAiInquiries(query: AiListQuery = {}): Promise<ApiResult<AiPage>> {
  const { page = 1, size = 20, sort, per = '', kind = '', categoryCode = '', q = '' } = query
  if (!USE_MOCK_INQUIRY) {
    const from = per ? daysAgoDate(PER_DAYS[per] - 1) : undefined
    const one = (kinds: AiKind[], n: number, p: number, filtered = false) => {
      const qs = new URLSearchParams({ page: String(p), size: String(n) })
      kinds.forEach((k) => qs.append('displayStatus', KIND_STATUS[k]))
      if (sort) qs.set('sort', sort)
      if (from) qs.set('createdFrom', from)
      if (filtered && categoryCode) qs.set('categoryCode', categoryCode)
      if (filtered && q.trim()) qs.set('q', q.trim())
      return request<Page<SSummary>>(`/inquiries?${qs.toString()}`)
    }
    const all: AiKind[] = ['ok', 'pend', 'unr']
    const [list, ...cnt] = await Promise.all([one(kind ? [kind] : all, size, page, true), ...all.map((k) => one([k], 1, 1))])
    if (!list.ok) return list
    const counts = { all: 0, ok: 0, pend: 0, unr: 0 }
    cnt.forEach((r, i) => {
      if (r.ok) {
        counts[all[i]] = r.data.totalCount
        counts.all += r.data.totalCount
      }
    })
    const items: AiRow[] = list.data.items.map((s) => ({
      id: `INQ-${s.id}`,
      title: s.title ?? '새 문의',
      categoryCode: s.category?.code ?? null,
      guide: '-',
      kind: STATUS_KIND[s.displayStatus] ?? 'ok',
      when: formatRelative(s.updatedAt ?? s.createdAt),
      day: 0,
      at: Date.parse(s.updatedAt ?? s.createdAt),
    }))
    return ok({ ...list.data, items, counts })
  }
  await sleep(150)
  const base = aiRows().filter((r) => !per || r.day === -1 || r.day < PER_DAYS[per])
  const counts = { all: base.length, ok: base.filter((r) => r.kind === 'ok').length, pend: base.filter((r) => r.kind === 'pend').length, unr: base.filter((r) => r.kind === 'unr').length }
  const needle = q.trim().toLowerCase()
  let rows = base.filter((r) => (!kind || r.kind === kind) && (!categoryCode || r.categoryCode === categoryCode) && (!needle || [r.title, r.id, r.guide, r.categoryCode && CATEGORIES[r.categoryCode].name].some((v) => v && v.toLowerCase().includes(needle))))
  if (sort) {
    const [key, dir] = sort.split(',')
    const sign = dir === 'desc' ? -1 : 1
    const val = (r: AiRow): string | number => (key === 'title' ? r.title : key === 'cat' ? (r.categoryCode ?? '힣') : key === 'guide' ? r.guide : r.at)
    rows = rows.slice().sort((a, b) => {
      const x = val(a)
      const y = val(b)
      return (x < y ? -1 : x > y ? 1 : 0) * sign
    })
  }
  const totalPages = Math.max(1, Math.ceil(rows.length / size))
  const p = Math.min(Math.max(1, page), totalPages)
  return ok({ items: rows.slice((p - 1) * size, p * size), page: p, size, totalCount: rows.length, totalPages, counts })
}

/** n일 전 날짜 (YYYY-MM-DD) */
function daysAgoDate(n: number): string {
  const d = new Date(Date.now() - n * 86_400_000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
