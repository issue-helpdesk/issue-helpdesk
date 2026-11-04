/**
 * 가이드 관리 API 어댑터 (관리자). (design/ITssue-Prototype.html 가이드 관리, docs/api/04 DC-01~09)
 *   GET   /documents                              DC-01 문서 목록 (현행 버전의 열람 범위·전송 정책 포함)
 *   POST  /documents                              DC-02 문서 등록 (문서 번호·종류·제목·분류)
 *   GET   /documents/{id}/versions                DC-06 버전 목록 (적재 상태 포함)
 *   POST  /documents/{id}/versions                DC-07 새 버전 업로드 (multipart, 202)
 *   PATCH /documents/{id}/versions/{versionId}    DC-09 현행 전환·열람 범위·외부 전송 정책 변경
 *   POST  /documents/{id}/versions/{versionId}/retry  DC-10 적재(검색 준비)에 실패한 버전 다시 시도
 * 서버에 없는 것: 버전 메모(관리자가 적는 한 줄), 정책을 느슨하게 바꿀 때의 변경 사유 저장, 해결 사례 → 가이드 초안(GUIDE-03).
 * 이 세 가지는 서버 모드에서 안내만 한다. (요청 R-21·R-22)
 */
import { request } from '../core/apiClient'
import { USE_MOCK_GUIDE } from '../core/config'
import type { CategoryCode } from './chatTypes'
import { subscribe, notify } from './mock/chatStore'
import { fail, ok, type ApiResult, type User } from './types'

export type GuideState = '현행' | '초안' | '만료'
export type GuideReady = '준비 완료' | '준비 중' | '준비 실패'
export type GuideScope = '관리자 전용' | '사내 제한' | '사내 일반'
export type GuideTx = '허용' | '마스킹 후 허용' | '금지'
export const GUIDE_SCOPES: GuideScope[] = ['관리자 전용', '사내 제한', '사내 일반']
export const GUIDE_TXS: GuideTx[] = ['금지', '마스킹 후 허용', '허용']
/** 외부 전송 정책의 엄격한 순서: 금지 < 마스킹 후 허용 < 허용. 값이 커지면 더 느슨해진다 */
export const TX_RANK: Record<GuideTx, number> = { 금지: 0, '마스킹 후 허용': 1, 허용: 2 }

export interface GuideVersion {
  id: number
  version: string
  state: GuideState
  ready: GuideReady
  scope: GuideScope
  tx: GuideTx
  note: string
  /** 적재 실패 사유 */
  error?: string
}
export interface Guide {
  id: number
  docCode: string
  title: string
  cat: CategoryCode
  /** 현행 버전 (없으면 null) */
  current: { version: string; tx: GuideTx } | null
  /** 서버 모드에서는 가이드를 펼칠 때 읽는다 */
  versions: GuideVersion[] | null
}

const SCOPE_FROM = { ALL: '사내 일반', AGENT: '사내 제한', ADMIN: '관리자 전용' } as const
const SCOPE_TO = { '사내 일반': 'ALL', '사내 제한': 'AGENT', '관리자 전용': 'ADMIN' } as const
const TX_FROM = { ALLOWED: '허용', MASKED: '마스킹 후 허용', BLOCKED: '금지' } as const
const TX_TO = { 허용: 'ALLOWED', '마스킹 후 허용': 'MASKED', 금지: 'BLOCKED' } as const

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const adminOnly = (u: User) => (u.serviceRole === 'ADMIN' ? null : fail('FORBIDDEN', '관리자만 볼 수 있어요.'))
const notReady = (what: string) => fail('NOT_READY', `${what}은(는) 서버에 아직 없어서 서버 모드에서는 사용할 수 없어요.`)

/* ------------------------------------------------------------------ 모의 */
interface MockGuide extends Omit<Guide, 'current' | 'versions'> {
  versions: GuideVersion[]
}
const v = (id: number, version: string, state: GuideState, scope: GuideScope, tx: GuideTx, ready: GuideReady, note: string): GuideVersion => ({ id, version, state, scope, tx, ready, note })
const seed = (): MockGuide[] => [
  { id: 1, docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드', cat: 'NET', versions: [v(13, 'v3', '초안', '사내 제한', '허용', '준비 중', '주간 분석: 해결 사례 8건 반영'), v(12, 'v2', '현행', '사내 일반', '허용', '준비 완료', 'guides 정리본 (2026-10-16)'), v(11, 'v1', '만료', '사내 일반', '허용', '준비 완료', '정리 전 팀원 원본')] },
  { id: 2, docCode: 'IT-ACC-001', title: '사내 SSO 로그인 오류 대응 가이드', cat: 'ACC', versions: [v(21, 'v2', '현행', '사내 일반', '허용', '준비 완료', '5회 실패 시 잠금, 10분 후 해제')] },
  { id: 3, docCode: 'IT-ACC-002', title: '비밀번호 변경·초기화 가이드', cat: 'ACC', versions: [v(31, 'v2', '현행', '사내 일반', '허용', '준비 완료', '12자 이상, 90일마다 변경')] },
  { id: 4, docCode: 'IT-ACC-003', title: 'MFA 인증 오류 대응 가이드', cat: 'ACC', versions: [v(41, 'v2', '현행', '사내 일반', '허용', '준비 완료', '')] },
  { id: 5, docCode: 'IT-SW-001', title: '업무용 SW 설치 가이드', cat: 'SW', versions: [v(51, 'v2', '현행', '사내 일반', '허용', '준비 완료', '소프트웨어 센터 설치')] },
  { id: 6, docCode: 'IT-HW-003', title: '프린터·복합기 이용 가이드', cat: 'HW', versions: [v(62, 'v2', '현행', '사내 일반', '허용', '준비 완료', '층별 복합기'), v(61, 'v1', '만료', '사내 일반', '허용', '준비 완료', '정리 전 팀원 원본')] },
  { id: 7, docCode: 'IT-ACS-001', title: '사내 시스템 접근권한 신청 가이드', cat: 'ACS', versions: [v(71, 'v2', '현행', '사내 일반', '허용', '준비 완료', '권한 부여는 담당자·승인자 업무')] },
  { id: 8, docCode: 'IT-SYS-001', title: '그룹웨어·ERP 이용 오류 대응 가이드', cat: 'SYS', versions: [v(81, 'v2', '현행', '사내 일반', '허용', '준비 완료', '')] },
  { id: 9, docCode: 'IT-SEC-004', title: '보안 예외 신청·정책 안내 가이드', cat: 'SEC', versions: [v(91, 'v2', '현행', '사내 제한', '금지', '준비 완료', '시연용: 외부 모델 전송 금지 문서로 가정')] },
  { id: 10, docCode: 'IT-SEC-001', title: '피싱·의심 메일 대응 가이드', cat: 'SEC', versions: [v(102, 'v2', '현행', '사내 일반', '마스킹 후 허용', '준비 완료', '시연용: 마스킹 후 전송 문서로 가정'), v(103, 'v3', '초안', '사내 일반', '허용', '준비 중', '신고 채널 변경 반영 중')] },
]
let store: MockGuide[] = seed()
let seq = { doc: 10, ver: 200 }
const timers: ReturnType<typeof setTimeout>[] = []

/** 시연 가이드를 처음 상태로 되돌린다 (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetGuideMock() {
  timers.splice(0).forEach(clearTimeout)
  store = seed()
  seq = { doc: 10, ver: 200 }
}
/** 모의 가이드가 바뀔 때 알려 준다. 구독하자마자 한 번 알린다 */
export function watchGuides(onChange: () => void): () => void {
  onChange()
  return subscribe(onChange)
}
const curOf = (g: MockGuide) => g.versions.find((x) => x.state === '현행')
const toGuide = (g: MockGuide): Guide => {
  const c = curOf(g)
  return { id: g.id, docCode: g.docCode, title: g.title, cat: g.cat, current: c ? { version: c.version, tx: c.tx } : null, versions: g.versions.map((x) => ({ ...x })) }
}
const findV = (g: MockGuide, versionId: number) => g.versions.find((x) => x.id === versionId)

/* ------------------------------------------------------------------ 서버 */
interface SDoc {
  id: number
  docCode: string
  docType: string
  title: string
  categoryCode: CategoryCode | null
  currentVersion: { version: string; viewScope: keyof typeof SCOPE_FROM | null; transferPolicy: keyof typeof TX_FROM | null } | null
}
interface SVer {
  id: number
  version: string
  viewScope: keyof typeof SCOPE_FROM
  transferPolicy: keyof typeof TX_FROM
  isCurrent: boolean
  versionState: 'CURRENT' | 'DRAFT' | 'EXPIRED'
  ingestStatus: 'PENDING' | 'DONE' | 'FAILED'
  ingestError: string | null
}
const STATE_FROM = { CURRENT: '현행', DRAFT: '초안', EXPIRED: '만료' } as const
const READY_FROM = { DONE: '준비 완료', PENDING: '준비 중', FAILED: '준비 실패' } as const
const toVersion = (s: SVer): GuideVersion => ({ id: s.id, version: s.version, state: STATE_FROM[s.versionState], ready: READY_FROM[s.ingestStatus], scope: SCOPE_FROM[s.viewScope], tx: TX_FROM[s.transferPolicy], note: '', error: s.ingestError ?? undefined })

/** 가이드 목록. 서버는 문서 목록(분류가 있는 가이드·매뉴얼)을 모두 읽는다 */
export async function listGuides(user: User): Promise<ApiResult<Guide[]>> {
  const no = adminOnly(user)
  if (no) return no
  if (USE_MOCK_GUIDE) {
    await sleep(150)
    return ok(store.map(toGuide))
  }
  const out: Guide[] = []
  for (let page = 1; page <= 10; page++) {
    const r = await request<{ items: SDoc[]; totalPages: number }>(`/documents?size=100&page=${page}&docType=GUIDE&docType=MANUAL&sort=docCode,asc`)
    if (!r.ok) return r
    r.data.items.forEach((d) => {
      if (!d.categoryCode) return
      const c = d.currentVersion
      out.push({ id: d.id, docCode: d.docCode, title: d.title, cat: d.categoryCode, current: c ? { version: c.version, tx: c.transferPolicy ? TX_FROM[c.transferPolicy] : '금지' } : null, versions: null })
    })
    if (page >= r.data.totalPages) break
  }
  return ok(out)
}

/** 버전 목록 (가이드를 펼칠 때) */
export async function listGuideVersions(user: User, docId: number): Promise<ApiResult<GuideVersion[]>> {
  const no = adminOnly(user)
  if (no) return no
  if (USE_MOCK_GUIDE) {
    const g = store.find((x) => x.id === docId)
    return g ? ok(g.versions.map((x) => ({ ...x }))) : fail('DOCUMENT_NOT_FOUND', '문서를 찾을 수 없어요.')
  }
  const r = await request<{ items: SVer[] }>(`/documents/${docId}/versions`)
  return r.ok ? ok(r.data.items.map(toVersion)) : r
}

export interface UploadInput {
  file: File
  docCode: string
  title: string
  cat: CategoryCode
  scope: GuideScope
  tx: GuideTx
  /** 첫 버전 이름. 비우면 v1 */
  version?: string
}
/** 가이드 파일 업로드: 문서를 만들고(DC-02) 첫 버전 v1 을 올린다(DC-07). 검색 준비(적재)가 끝나기 전에는 현행으로 바꿀 수 없다 */
export async function uploadGuide(user: User, input: UploadInput): Promise<ApiResult<Guide>> {
  const no = adminOnly(user)
  if (no) return no
  const code = input.docCode.trim().toUpperCase()
  if (!/^IT-[A-Z]{2,4}-\d{3}(-M)?$/.test(code)) return fail('VALIDATION_ERROR', '문서 번호 형식이 맞지 않아요. 예) IT-NET-004', { details: [{ field: 'docCode', reason: 'INVALID_FORMAT', message: '문서 번호 형식이 맞지 않아요. 예) IT-NET-004' }] })
  if (USE_MOCK_GUIDE) {
    await sleep(250)
    if (store.some((g) => g.docCode === code)) return fail('DOCUMENT_CODE_DUPLICATE', '이미 있는 문서 번호예요.', { details: [{ field: 'docCode', reason: 'DUPLICATE', message: '이미 있는 문서 번호예요.' }] })
    const g: MockGuide = { id: ++seq.doc, docCode: code, title: input.title.trim(), cat: input.cat, versions: [v(++seq.ver, input.version?.trim() || 'v1', '초안', input.scope, input.tx, '준비 중', `업로드 · ${input.file.name}`)] }
    store.push(g)
    notify()
    // 검색 준비(텍스트 추출·색인)는 잠시 뒤에 끝난다
    timers.push(
      setTimeout(() => {
        const x = g.versions[0]
        if (x) x.ready = '준비 완료'
        notify()
      }, 2800),
    )
    return ok(toGuide(g))
  }
  const doc = await request<SDoc>('/documents', { method: 'POST', body: JSON.stringify({ docCode: code, docType: 'GUIDE', title: input.title.trim(), categoryCode: input.cat }) })
  if (!doc.ok) return doc
  const form = new FormData()
  form.append('file', input.file)
  form.append('version', input.version?.trim() || 'v1')
  form.append('viewScope', SCOPE_TO[input.scope])
  form.append('transferPolicy', TX_TO[input.tx])
  const ver = await request<SVer>(`/documents/${doc.data.id}/versions`, { method: 'POST', body: form })
  if (!ver.ok) return ver
  return ok({ id: doc.data.id, docCode: code, title: input.title.trim(), cat: input.cat, current: null, versions: [toVersion(ver.data)] })
}

const VERSION_DUP = { field: 'version', reason: 'DUPLICATE', message: '이미 있는 버전이에요. 다른 번호를 적어 주세요.' }

/** 기존 가이드에 새 버전 올리기 (DC-07). 같은 버전 이름이 있으면 DOCUMENT_VERSION_DUPLICATE. 현행 전환은 자동으로 하지 않는다 */
export async function uploadGuideVersion(user: User, docId: number, input: { file: File; version: string; scope: GuideScope; tx: GuideTx }): Promise<ApiResult<GuideVersion>> {
  const no = adminOnly(user)
  if (no) return no
  const version = input.version.trim()
  if (USE_MOCK_GUIDE) {
    await sleep(250)
    const g = store.find((x) => x.id === docId)
    if (!g) return fail('DOCUMENT_NOT_FOUND', '문서를 찾을 수 없어요.')
    if (g.versions.some((x) => x.version === version)) return fail('DOCUMENT_VERSION_DUPLICATE', VERSION_DUP.message, { details: [VERSION_DUP] })
    const x = v(++seq.ver, version, '초안', input.scope, input.tx, '준비 중', `업로드 · ${input.file.name}`)
    g.versions.unshift(x)
    notify()
    timers.push(
      setTimeout(() => {
        x.ready = '준비 완료'
        notify()
      }, 2800),
    )
    return ok({ ...x })
  }
  const form = new FormData()
  form.append('file', input.file)
  form.append('version', version)
  form.append('viewScope', SCOPE_TO[input.scope])
  form.append('transferPolicy', TX_TO[input.tx])
  const r = await request<SVer>(`/documents/${docId}/versions`, { method: 'POST', body: form })
  return r.ok ? ok(toVersion(r.data)) : r
}

/** 버전 이름을 v4 꼴로 정리한다. 숫자(점으로 이어도 됨)가 아니면 null */
export function normalizeVersion(raw: string): string | null {
  const m = /^v?(\d+(?:\.\d+)*)$/i.exec(raw.trim())
  return m ? `v${m[1]}` : null
}
/** 다음 버전 이름 (가장 큰 앞자리 숫자 + 1) */
export function nextVersion(versions: { version: string }[]): string {
  const top = Math.max(0, ...versions.map((x) => Number(/\d+/.exec(x.version)?.[0] ?? 0)))
  return `v${top + 1}`
}
/** 새 가이드의 문서 번호: 같은 분류의 다음 번호. 직접 적게 하면 겹치므로 화면이 정해 준다 (서버에 채번 API가 없다, R-22) */
export function nextDocCode(guides: { docCode: string }[], cat: CategoryCode): string {
  const top = Math.max(0, ...guides.map((g) => Number(new RegExp(`^IT-${cat}-(\\d{3})`).exec(g.docCode)?.[1] ?? 0)))
  return `IT-${cat}-${String(top + 1).padStart(3, '0')}`
}

/** 적재(검색 준비)에 실패한 버전을 같은 파일로 다시 적재한다 (DC-10). 실패한 버전만 되고, 끝나면 검색 준비가 완료로 바뀐다 */
export async function retryGuideIngest(user: User, docId: number, versionId: number): Promise<ApiResult<GuideVersion>> {
  const no = adminOnly(user)
  if (no) return no
  if (USE_MOCK_GUIDE) {
    await sleep(150)
    const g = store.find((x) => x.id === docId)
    const x = g && findV(g, versionId)
    if (!g || !x) return fail('DOCUMENT_VERSION_NOT_FOUND', '버전을 찾을 수 없어요.')
    if (x.ready !== '준비 실패') return fail('DOCUMENT_VERSION_NOT_RETRYABLE', '검색 준비에 실패한 버전만 다시 시도할 수 있어요.')
    x.ready = '준비 중'
    x.error = undefined
    notify()
    timers.push(
      setTimeout(() => {
        x.ready = '준비 완료'
        notify()
      }, 2800),
    )
    return ok({ ...x })
  }
  const r = await request<SVer>(`/documents/${docId}/versions/${versionId}/retry`, { method: 'POST' })
  return r.ok ? ok(toVersion(r.data)) : r
}

/** 열람 범위·외부 전송 정책 변경. 더 느슨하게 바꿀 때의 사유는 서버에 저장할 곳이 없어 모의에서만 남긴다 (R-22) */
export async function setGuideTransfer(user: User, docId: number, versionId: number, tx: GuideTx, reason: string): Promise<ApiResult<GuideVersion>> {
  void reason // 사유는 서버에 저장할 곳이 없다 (R-22)
  const no = adminOnly(user)
  if (no) return no
  if (USE_MOCK_GUIDE) {
    await sleep(150)
    const g = store.find((x) => x.id === docId)
    const x = g && findV(g, versionId)
    if (!g || !x) return fail('DOCUMENT_VERSION_NOT_FOUND', '버전을 찾을 수 없어요.')
    x.tx = tx
    notify()
    return ok({ ...x })
  }
  const r = await request<SVer>(`/documents/${docId}/versions/${versionId}`, { method: 'PATCH', body: JSON.stringify({ transferPolicy: TX_TO[tx] }) })
  return r.ok ? ok(toVersion(r.data)) : r
}

/** 현행 전환. 검색 준비가 끝난 버전만 되고, 이전 버전으로 되돌릴 수도 있다 */
export async function setGuideCurrent(user: User, docId: number, versionId: number): Promise<ApiResult<GuideVersion>> {
  const no = adminOnly(user)
  if (no) return no
  if (USE_MOCK_GUIDE) {
    await sleep(150)
    const g = store.find((x) => x.id === docId)
    const x = g && findV(g, versionId)
    if (!g || !x) return fail('DOCUMENT_VERSION_NOT_FOUND', '버전을 찾을 수 없어요.')
    if (x.ready !== '준비 완료') return fail('DOCUMENT_VERSION_NOT_READY', '검색 준비가 끝나야 현행으로 바꿀 수 있어요.')
    g.versions.forEach((y) => {
      if (y.state === '현행') y.state = '만료'
    })
    x.state = '현행'
    notify()
    return ok({ ...x })
  }
  const r = await request<SVer>(`/documents/${docId}/versions/${versionId}`, { method: 'PATCH', body: JSON.stringify({ isCurrent: true }) })
  return r.ok ? ok(toVersion(r.data)) : r
}

/** 버전 메모 (관리자가 적는 한 줄). 서버에 필드가 없어 서버 모드에서는 사용할 수 없다 (R-21) */
export async function setGuideNote(user: User, docId: number, versionId: number, note: string): Promise<ApiResult<GuideVersion>> {
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_GUIDE) return notReady('버전 메모')
  const g = store.find((x) => x.id === docId)
  const x = g && findV(g, versionId)
  if (!g || !x) return fail('DOCUMENT_VERSION_NOT_FOUND', '버전을 찾을 수 없어요.')
  x.note = note.trim()
  notify()
  return ok({ ...x })
}

/** 해결 사례 묶음에서 가이드 초안 만들기 (GUIDE-03, 제안). 서버에 없어 서버 모드에서는 사용할 수 없다 (R-23) */
export async function createGuideDraft(user: User, draft: { cat: CategoryCode; title: string; existId: number | null; note: string }): Promise<ApiResult<{ guide: Guide; version: string }>> {
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_GUIDE) return notReady('해결 사례 가이드 초안 만들기')
  await sleep(200)
  let g = draft.existId ? store.find((x) => x.id === draft.existId) : undefined
  let version = 'v1'
  if (g) {
    const n = Math.max(0, ...g.versions.map((x) => Number(x.version.replace(/\D/g, '')) || 0)) + 1
    version = `v${n}`
    g.versions.unshift(v(++seq.ver, version, '초안', '사내 제한', '허용', '준비 중', draft.note))
  } else {
    const code = `IT-${draft.cat}-${String(900 + ++seq.doc).slice(-3)}`
    g = { id: seq.doc, docCode: code, title: draft.title, cat: draft.cat, versions: [v(++seq.ver, 'v1', '초안', '사내 제한', '허용', '준비 중', draft.note)] }
    store.push(g)
  }
  const made = g
  notify()
  timers.push(
    setTimeout(() => {
      made.versions.forEach((x) => {
        if (x.ready === '준비 중') x.ready = '준비 완료'
      })
      notify()
    }, 2800),
  )
  return ok({ guide: toGuide(made), version })
}

export const guideLabel = (g: Pick<Guide, 'docCode' | 'title'>) => `${g.docCode} ${g.title}`
