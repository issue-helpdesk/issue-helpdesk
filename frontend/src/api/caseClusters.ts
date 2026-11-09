/**
 * 해결 사례 묶음(AI 가이드 제안) 서버 연결 (관리자). docs/api/04 4A장
 *   GET   /guide-clusters                    GC-01 묶음 목록 (근거 티켓 많은 순)
 *   GET   /guide-clusters/{id}               GC-02 묶음 상세 (초안·AI 판단·근거 티켓)
 *   PATCH /guide-clusters/{id}               GC-05 초안 수정 저장 (draftRevision 으로 동시 수정 확인)
 *   POST  /guide-clusters/{id}/reject        GC-03 거절 (사유 필수)
 *   POST  /guide-clusters/{id}/apply         GC-04 직접 반영 표시 (등록하지 않은 묶음만)
 *   POST  /guide-clusters/{id}/register      GC-06 초안 등록 (가이드의 현행이 아닌 새 버전으로, 검색 준비 시작)
 *   POST  /guide-clusters/{id}/rebase        GC-07 다시 맞추기 (기준 버전이 바뀐 제안)
 *   POST  /guide-clusters/{id}/target        GC-08 넣을 문서 변경 (새 가이드는 문서 연결)
 * 화면은 모의(api/mock/caseGuides.ts)와 같은 CaseItem 으로 그린다. 서버 값을 화면 말로 옮기는 규칙은 이 파일 한 곳에 둔다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_GUIDE } from '../core/config'
import type { CategoryCode } from './chatTypes'
import type { GuideScope, GuideTx } from './guides'
import { getCases as getMockCases, subscribeCases as subscribeMockCases, type CaseItem, type CaseKind, type CaseState, type CaseTicket, type ReviewExtras } from './mock/caseGuides'
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
interface SConflict {
  section: string
  kind: string
  message: string
  oldMd: string
  newMd: string
}
interface SDetail extends SSummary {
  /** 변경(CHANGE)할 항목 번호와 그 항목의 초안 기준 원문 */
  targetSection?: string | null
  targetMd?: string | null
  conflicts?: SConflict[]
  /** 등록·다시 맞추기·문서 변경 응답에만 있다 (저장되지 않는다) */
  warnings?: string[]
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
const text = (v: unknown): string | undefined => (typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined)

/** 검토 정보(reviewInfo)의 추가 항목 (키는 서버가 snake_case 로 준다, backend/app/agent/guide/README.md) */
function extrasOf(info: Record<string, unknown>): ReviewExtras {
  return {
    manualNote: text(info.manual_note),
    manualItems: strings(info.manual_items),
    changeNote: text(info.change_note),
    guideTitle: text(info.guide_title),
    differences: strings(info.differences),
    guessed: strings(info.guessed),
  }
}

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
    target: s.targetDocument ? { docCode: s.targetDocument.docCode, title: s.targetDocument.title, baseVersion: keep?.target?.baseVersion ?? '', latestVersion: keep?.target?.latestVersion ?? '', section: keep?.target?.section ?? '' } : undefined,
    before: keep?.before,
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
    server: { judgmentLabel: JUDGMENT_LABEL[s.judgment] ?? '', baseChanged: keep?.server?.baseChanged ?? false, draftRevision: keep?.server?.draftRevision ?? 0, hasDraft: keep?.server?.hasDraft ?? s.judgment !== 'MANUAL_CANDIDATE', detail: !!keep, judgment: s.judgment, conflicts: keep?.server?.conflicts, fresh: keep?.server?.fresh, info: keep?.server?.info },
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
    target: d.targetDocument ? { docCode: d.targetDocument.docCode, title: d.targetDocument.title, baseVersion: d.baseVersion?.version ?? '', latestVersion: d.currentVersion?.version ?? '', section: d.targetSection ?? '' } : undefined,
    before: d.targetMd ?? undefined,
    after: d.draftMd ?? '',
    title: base.kind === 'new' ? (text(info.guide_title) ?? base.title) : undefined,
    reason: typeof info.reason === 'string' ? info.reason : '',
    warnings: strings(info.warnings),
    dropReason: d.status === 'REJECTED' ? (d.rejectReason ?? '') : undefined,
    server: {
      judgmentLabel: JUDGMENT_LABEL[d.judgment] ?? '',
      baseChanged: d.baseChanged,
      draftRevision: d.draftRevision,
      hasDraft: d.draftMd !== null,
      detail: true,
      judgment: d.judgment,
      conflicts: d.conflicts ?? [],
      fresh: d.warnings,
      info: extrasOf(info),
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

const SCOPE_API = { '전 직원': 'ALL', '담당자 이상': 'AGENT', '관리자만': 'ADMIN' } as const
const TX_API = { 허용: 'ALLOWED', '마스킹 후 허용': 'MASKED', 금지: 'BLOCKED' } as const

/** 서버 응답(상세 + 경고)을 저장소에 반영한다 */
const take = (d: SDetail): ApiResult<CaseItem> => {
  const c = fromDetail(d)
  put(c)
  return ok(c)
}
/** 초안이 다른 관리자와 어긋났거나 기준이 바뀌었으면 최신 상세로 다시 읽는다 */
const RELOAD_ON = new Set(['GUIDE_CLUSTER_DRAFT_CONFLICT', 'GUIDE_CLUSTER_BASE_CHANGED', 'GUIDE_CLUSTER_CONFLICT_UNRESOLVED', 'GUIDE_CLUSTER_REGISTERED', 'GUIDE_CLUSTER_NOT_REVIEWING'])

/**
 * 승인하고 초안 등록 (GC-06): 저장된 초안을 가이드의 현행이 아닌 새 버전으로 등록하고 검색 준비를 시작한다.
 * 글은 보내지 않는다 — 화면에서 고친 글이 있으면 먼저 saveCaseDraft 로 저장하고, 그 응답의 draftRevision 을 넘겨야 한다.
 * 거절한 묶음이 있는 버전의 남은 묶음에 다시 부르면 같은 버전을 거절 항목 없이 다시 만든다.
 */
export async function registerCase(id: string, draftRevision: number, scope: GuideScope, tx: GuideTx): Promise<ApiResult<CaseItem>> {
  const r = await request<SDetail>(`/guide-clusters/${id}/register`, { method: 'POST', body: JSON.stringify({ draftRevision, viewScope: SCOPE_API[scope], transferPolicy: TX_API[tx] }) })
  if (!r.ok) {
    if (RELOAD_ON.has(r.error.code)) await loadCaseDetail(id)
    return r
  }
  return take(r.data)
}

/** 다시 맞추기 (GC-07): 초안을 만든 뒤 현행이 바뀐 제안의 기준을 지금 현행으로 맞춘다. 글은 바꾸지 않는다. 충돌은 conflicts 로 온다 */
export async function rebaseServerCase(id: string, draftRevision: number): Promise<ApiResult<CaseItem>> {
  const r = await request<SDetail>(`/guide-clusters/${id}/rebase`, { method: 'POST', body: JSON.stringify({ draftRevision }) })
  if (!r.ok) {
    if (RELOAD_ON.has(r.error.code)) await loadCaseDetail(id)
    return r
  }
  return take(r.data)
}

/** 넣을 문서 변경 (GC-08). 변경(CHANGE)은 항목 번호도 함께. 성공하면 draftRevision 이 오른다 */
export async function changeCaseTarget(id: string, draftRevision: number, documentId: number, targetSection?: string): Promise<ApiResult<CaseItem>> {
  const body: Record<string, unknown> = { draftRevision, documentId }
  if (targetSection?.trim()) body.targetSection = targetSection.trim()
  const r = await request<SDetail>(`/guide-clusters/${id}/target`, { method: 'POST', body: JSON.stringify(body) })
  if (!r.ok) {
    if (RELOAD_ON.has(r.error.code)) await loadCaseDetail(id)
    return r
  }
  return take(r.data)
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
