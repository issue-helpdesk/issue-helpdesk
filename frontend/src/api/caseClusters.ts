/**
 * 해결 사례 묶음(AI 가이드 제안) 서버 연결 (관리자). docs/api/04 4A장
 *   GET   /guide-clusters                    GC-01 묶음 목록 (근거 티켓 많은 순)
 *   GET   /guide-clusters/{id}               GC-02 묶음 상세 (초안·AI 판단·근거 티켓)
 *   PATCH /guide-clusters/{id}               GC-05 초안 수정 저장 (draftRevision 으로 동시 수정 확인)
 *   POST  /guide-clusters/{id}/reject        GC-03 거절 (사유 필수)
 *   POST  /guide-clusters/{id}/apply         GC-04 직접 반영 표시 (등록하지 않은 묶음만)
 * 서버에 아직 없는 것: 초안을 가이드 버전으로 등록하는 승인 API, 넣을 문서 변경 API. 그래서 이 화면은 초안을 등록하지 못한다.
 * 화면은 모의(api/mock/caseGuides.ts)와 같은 CaseItem 으로 그린다. 서버 값을 화면 말로 옮기는 규칙은 이 파일 한 곳에 둔다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_GUIDE } from '../core/config'
import type { CategoryCode } from './chatTypes'
import { getCases as getMockCases, subscribeCases as subscribeMockCases, type CaseItem, type CaseKind, type CaseState, type CaseTicket } from './mock/caseGuides'
import { fail, ok, type ApiResult } from './types'

type Judgment = 'ADD_ITEM' | 'CHANGE' | 'NEW_GUIDE' | 'MANUAL_CANDIDATE' | 'SEC_MANUAL'
type Status = 'REVIEWING' | 'APPLIED' | 'REJECTED'
interface SVersionRef {
  id: number
  version: string
  isCurrent: boolean
  ingestStatus: 'DONE' | 'PENDING' | 'FAILED'
}
interface SSummary {
  id: number
  category: { code: CategoryCode; name?: string }
  judgment: Judgment
  status: Status
  title: string
  ticketCount: number
  targetDocument: { id: number; docCode: string; title: string } | null
  registeredVersion: SVersionRef | null
}
interface SDetail extends SSummary {
  draftMd: string | null
  draftRevision: number
  reviewInfo: Record<string, unknown> | null
  baseVersion: SVersionRef | null
  currentVersion: SVersionRef | null
  baseChanged: boolean
  rejectReason: string | null
  reviewedBy: { name?: string; employeeNo?: string } | null
  reviewedAt: string | null
  tickets: { ticketId: number; receiptNo: string; summary: string; symptom?: string | null; resolutionNote?: string | null }[]
}

const KIND: Record<Judgment, CaseKind> = { ADD_ITEM: 'amend', CHANGE: 'amend', NEW_GUIDE: 'new', MANUAL_CANDIDATE: 'manual', SEC_MANUAL: 'sec' }
const JUDGMENT_LABEL: Record<Judgment, string> = { ADD_ITEM: '항목 추가', CHANGE: '변경', NEW_GUIDE: '새 가이드', MANUAL_CANDIDATE: '매뉴얼 후보', SEC_MANUAL: 'SEC 직접 검토' }
const PREP_FAIL = '문서 변환 중 오류가 나서 검색 준비를 마치지 못했어요. 같은 버전으로 다시 시도할 수 있어요.'

/** 서버 상태를 화면 상태로: 등록한 버전이 있으면 그 버전의 검색 준비·현행 여부를 따른다 */
function stateOf(s: SSummary): CaseState {
  if (s.status === 'REJECTED') return 'dropped'
  if (s.status === 'APPLIED') return s.registeredVersion?.isCurrent ? 'live' : 'applied'
  const v = s.registeredVersion
  if (!v) return 'review'
  if (v.ingestStatus === 'PENDING') return 'preparing'
  if (v.ingestStatus === 'FAILED') return 'failed'
  return v.isCurrent ? 'live' : 'ready'
}

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '') : [])

function fromSummary(s: SSummary, prev?: CaseItem): CaseItem {
  const kind = KIND[s.judgment] ?? 'amend'
  const state = stateOf(s)
  const reg = s.registeredVersion
  const keep = prev?.server?.detail ? prev : undefined
  return {
    id: String(s.id),
    cat: s.category.code,
    topic: s.title,
    kind,
    state,
    tickets: keep?.tickets ?? [],
    ticketCount: s.ticketCount,
    target: s.targetDocument ? { docCode: s.targetDocument.docCode, title: s.targetDocument.title, baseVersion: keep?.target?.baseVersion ?? '', latestVersion: keep?.target?.latestVersion ?? '', section: '' } : undefined,
    after: keep?.after ?? '',
    title: kind === 'new' ? s.title : undefined,
    reason: keep?.reason ?? '',
    warnings: keep?.warnings ?? [],
    // 열람 범위·외부 전송 정책은 묶음이 아니라 등록한 가이드 버전에 있다
    scope: '관리자만',
    tx: '금지',
    registered: reg && s.targetDocument ? { docId: s.targetDocument.id, versionId: reg.id, docCode: s.targetDocument.docCode, version: reg.version } : undefined,
    failReason: state === 'failed' ? PREP_FAIL : undefined,
    dropReason: keep?.dropReason ?? (s.status === 'REJECTED' ? '' : undefined),
    server: { judgmentLabel: JUDGMENT_LABEL[s.judgment] ?? '', baseChanged: keep?.server?.baseChanged ?? false, draftRevision: keep?.server?.draftRevision ?? 0, hasDraft: keep?.server?.hasDraft ?? s.judgment !== 'MANUAL_CANDIDATE', detail: !!keep },
  }
}

function fromDetail(d: SDetail): CaseItem {
  const base = fromSummary(d)
  const info = d.reviewInfo ?? {}
  const tickets: CaseTicket[] = d.tickets.map((t) => ({ no: t.receiptNo, summary: t.summary, result: t.resolutionNote ?? '' }))
  return {
    ...base,
    tickets,
    ticketCount: d.ticketCount,
    target: d.targetDocument ? { docCode: d.targetDocument.docCode, title: d.targetDocument.title, baseVersion: d.baseVersion?.version ?? '', latestVersion: d.currentVersion?.version ?? '', section: '' } : undefined,
    after: d.draftMd ?? '',
    reason: typeof info.reason === 'string' ? info.reason : '',
    warnings: strings(info.warnings),
    dropReason: d.status === 'REJECTED' ? (d.rejectReason ?? '') : undefined,
    server: {
      judgmentLabel: JUDGMENT_LABEL[d.judgment] ?? '',
      baseChanged: d.baseChanged,
      draftRevision: d.draftRevision,
      hasDraft: d.draftMd !== null,
      detail: true,
      rejectReason: d.rejectReason ?? undefined,
      reviewedBy: d.reviewedBy?.name,
      reviewedAt: d.reviewedAt ?? undefined,
    },
  }
}

/* ------------------------------------------------------------------ 저장소 (서버 값의 사본) */
interface Load {
  loaded: boolean
  loading: boolean
  error: string
}
let items: CaseItem[] = []
let load: Load = { loaded: false, loading: false, error: '' }
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((f) => f())
const put = (next: CaseItem) => {
  items = items.some((c) => c.id === next.id) ? items.map((c) => (c.id === next.id ? next : c)) : [...items, next]
  emit()
}

export const subscribeServerCases = (f: () => void) => {
  listeners.add(f)
  return () => {
    listeners.delete(f)
  }
}
export const getServerCases = () => items
export const getServerLoad = () => load

/** 목록 전체를 다시 읽는다 (근거 티켓이 많은 순). 이미 열어 본 상세는 유지한다 */
export async function loadCases(): Promise<ApiResult<CaseItem[]>> {
  if (load.loading) return ok(items)
  load = { ...load, loading: true, error: '' }
  emit()
  const all: SSummary[] = []
  for (let page = 1; page <= 20; page++) {
    const r = await request<{ items: SSummary[]; totalPages: number }>(`/guide-clusters?size=100&page=${page}`)
    if (!r.ok) {
      load = { loaded: load.loaded, loading: false, error: r.error.message }
      emit()
      return r
    }
    all.push(...r.data.items)
    if (page >= r.data.totalPages) break
  }
  const prev = new Map(items.map((c) => [c.id, c]))
  items = all.map((s) => fromSummary(s, prev.get(String(s.id))))
  load = { loaded: true, loading: false, error: '' }
  emit()
  return ok(items)
}

/** 한 묶음의 상세(초안·AI 판단·근거 티켓)를 읽는다 */
export async function loadCaseDetail(id: string): Promise<ApiResult<CaseItem>> {
  const r = await request<SDetail>(`/guide-clusters/${id}`)
  if (!r.ok) return r
  const c = fromDetail(r.data)
  put(c)
  return ok(c)
}

/** 초안 임시 저장. 다른 관리자가 먼저 고쳤으면(409) 최신 초안을 다시 불러오고 알린다 */
export async function saveCaseDraft(id: string, draftMd: string, draftRevision: number): Promise<ApiResult<CaseItem>> {
  const r = await request<SDetail>(`/guide-clusters/${id}`, { method: 'PATCH', body: JSON.stringify({ draftMd, draftRevision }) })
  if (!r.ok) {
    if (r.error.code === 'GUIDE_CLUSTER_DRAFT_CONFLICT') await loadCaseDetail(id)
    return r
  }
  const c = fromDetail(r.data)
  put(c)
  return ok(c)
}

/** 거절: 사유(1~500자)를 남기고 닫는다 */
export async function rejectCase(id: string, reason: string): Promise<ApiResult<CaseItem>> {
  const text = reason.trim()
  if (!text) return fail('VALIDATION_ERROR', '사유를 입력해 주세요.')
  const r = await request<SDetail>(`/guide-clusters/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason: text }) })
  if (!r.ok) return r
  const c = fromDetail(r.data)
  put(c)
  return ok(c)
}

/** 직접 반영 표시: 관리자가 가이드(또는 매뉴얼)에 직접 반영한 묶음을 반영 완료로 바꾼다 */
export async function applyCase(id: string): Promise<ApiResult<CaseItem>> {
  const r = await request<SDetail>(`/guide-clusters/${id}/apply`, { method: 'POST' })
  if (!r.ok) return r
  const c = fromDetail(r.data)
  put(c)
  return ok(c)
}

/* ------------------------------------------------------------------ 화면이 쓰는 입구: 모의와 서버 중 켜진 쪽 */
/** 서버에 연결된 환경인지 (모의가 켜져 있으면 시연 데이터를 쓴다) */
export const CASES_FROM_SERVER = !USE_MOCK_GUIDE
export const subscribeAllCases = CASES_FROM_SERVER ? subscribeServerCases : subscribeMockCases
export const getAllCases = CASES_FROM_SERVER ? getServerCases : getMockCases
