/**
 * 가이드 적재(검색 준비) 결과 추적. 관리자가 업로드·다시 시도한 버전이 "준비 완료"가 됐는지 "준비 실패"가 됐는지를
 * 어느 화면에 있든 알려 주기 위한 화면 쪽 장치다.
 *
 * 서버 목록(DC-01)은 버전의 적재 상태를 주지 않아서, 이 브라우저에서 올리거나 다시 시도하거나 열어 본 버전만 추적한다.
 * - pending: 아직 적재 중인 버전. 몇 초마다 DC-06 으로 다시 읽어 결과를 확인한다.
 * - failed : 적재에 실패한 버전. 같은 버전이 "준비 완료"가 되면 사라진다. 새로 실패하면 seen=false 라서 알림 창이 뜬다.
 * 두 목록은 이 브라우저(localStorage)에 기억해 새로고침해도 이어진다. 저장소를 못 쓰면 이번 화면에서만 동작한다.
 * 다른 관리자가 올린 버전의 실패나, 이 브라우저가 열어 본 적 없는 버전의 실패는 알 수 없다 (서버가 목록에서 알려 줘야 한다).
 */
import { visiblePoll } from '../core/poll'
import type { CategoryCode } from './chatTypes'
import { listGuideVersions, type GuideVersion } from './guides'
import type { User } from './types'

interface IngestWatch {
  docId: number
  versionId: number
  docCode: string
  title: string
  cat: CategoryCode
  version: string
  /** 추적을 시작한 시각(ms). 오래 걸릴수록 조회 간격을 늘리고, 너무 오래되면 멈춘 것으로 본다 */
  since?: number
}
interface IngestFailure extends IngestWatch {
  error: string
  /** false 면 아직 알림 창으로 알리지 않았다 */
  seen: boolean
  /** 실패가 아니라 오래 끝나지 않아 멈춘 것으로 본 경우 */
  stalled?: boolean
}

/** 서버가 10분 넘게 PENDING 이면 적재가 멈춘 것으로 보는 기준(백엔드 STALE_PENDING)과 같다 */
export const STALL_MS = 10 * 60_000
export const STALL_MESSAGE = '10분이 넘도록 준비 중이에요. 서버에서 적재가 멈췄을 수 있어요. 서버 로그를 확인하거나 서버 관리자에게 알려 주세요.'
/** 얼마나 기다렸는지에 따른 조회 간격: 처음 30초는 3초, 2분까지는 10초, 그 뒤는 30초 (서버에 불필요한 조회를 줄인다) */
export function pollInterval(ageMs: number): number {
  return ageMs < 30_000 ? 3_000 : ageMs < 120_000 ? 10_000 : 30_000
}
const lastPoll = new Map<number, number>()

/** 실패 사유를 문장마다 줄을 바꿔 읽기 쉽게 한다 ("…못했습니다. PDF라면 …" → 두 줄). 화면에서 줄바꿈(pre-line)과 함께 쓴다 */
export const breakSentences = (s: string) => s.replace(/([.!?])\s+(?=\S)/g, '$1\n')

const KEY = 'itssue-guide-watch'

function load(): { pending: IngestWatch[]; failed: IngestFailure[] } {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const d = JSON.parse(raw) as { pending?: IngestWatch[]; failed?: IngestFailure[] }
      return { pending: Array.isArray(d.pending) ? d.pending : [], failed: Array.isArray(d.failed) ? d.failed : [] }
    }
  } catch {
    /* 저장소를 못 쓰거나 값이 깨졌으면 비어 있는 것으로 시작한다 */
  }
  return { pending: [], failed: [] }
}

let { pending, failed } = load()
const listeners = new Set<() => void>()
let snapshot = failed

function commit() {
  snapshot = [...failed]
  try {
    localStorage.setItem(KEY, JSON.stringify({ pending, failed }))
  } catch {
    /* 저장하지 못해도 이번 화면에서는 그대로 동작한다 */
  }
  listeners.forEach((f) => f())
}

/** 지금 실패한 버전들 (같은 배열을 바뀔 때만 새로 만든다) */
export const getIngestFailures = (): IngestFailure[] => snapshot
/** 바뀔 때 알려 준다 */
export function watchIngest(onChange: () => void): () => void {
  listeners.add(onChange)
  return () => {
    listeners.delete(onChange)
  }
}

const same = (a: { versionId: number }, b: { versionId: number }) => a.versionId === b.versionId

/** 업로드·다시 시도를 시작한 버전을 추적한다. 예전 실패 기록은 지운다 */
export function trackIngest(w: IngestWatch) {
  failed = failed.filter((f) => !same(f, w))
  lastPoll.delete(w.versionId)
  const t = { ...w, since: Date.now() }
  pending = [...pending.filter((p) => !same(p, w)), t]
  commit()
}

/** 알림 창으로 알린 실패를 "알림 확인"으로 표시한다 (실패 표시는 해결될 때까지 남는다) */
export function markFailuresSeen() {
  if (failed.every((f) => f.seen)) return
  failed = failed.map((f) => ({ ...f, seen: true }))
  commit()
}

/** 한 버전의 최신 적재 상태를 반영한다. fromPending: 추적 중이던 버전의 결과이면 새 실패를 알림 창으로 알린다 */
function apply(meta: Omit<IngestWatch, 'versionId' | 'version'>, v: GuideVersion, fromPending: boolean) {
  const w: IngestWatch = { ...meta, versionId: v.id, version: v.version }
  if (v.ready === '준비 실패') {
    pending = pending.filter((p) => !same(p, w))
    const old = failed.find((f) => same(f, w))
    failed = old ? failed.map((f) => (same(f, w) ? { ...f, error: v.error ?? f.error } : f)) : [...failed, { ...w, error: v.error ?? '', seen: !fromPending }]
  } else if (v.ready === '준비 완료') {
    pending = pending.filter((p) => !same(p, w))
    failed = failed.filter((f) => !same(f, w))
  } else if (!pending.some((p) => same(p, w))) {
    pending = [...pending, { ...w, since: Date.now() }]
  }
}

/** 화면에서 한 가이드의 버전 목록을 읽었을 때 그 결과를 반영한다 (열어 본 가이드의 실패도 표시 대상이 된다) */
export function recordVersions(meta: Omit<IngestWatch, 'versionId' | 'version'>, versions: GuideVersion[]) {
  const before = JSON.stringify([pending, failed])
  // 서버 목록에 더는 없는 버전(지워지거나 바뀐 버전)의 기록은 지운다. 안 지우면 빨간 점이 계속 남는다
  const exists = (x: { docId: number; versionId: number }) => x.docId !== meta.docId || versions.some((v) => v.id === x.versionId)
  pending = pending.filter(exists)
  failed = failed.filter(exists)
  // 이미 추적 중이던 버전의 결과면 (화면이 먼저 읽었더라도) 새 실패로 알린다
  versions.forEach((v) => apply(meta, v, pending.some((p) => p.versionId === v.id)))
  if (JSON.stringify([pending, failed]) !== before) commit()
}

/** 추적 중인 버전들의 결과를 서버에서 다시 읽는다 */
export async function pollIngest(user: User): Promise<void> {
  if (user.serviceRole !== 'ADMIN' || !pending.length) return
  const now = Date.now()
  const before = JSON.stringify([pending, failed])
  // 너무 오래 끝나지 않은 버전은 멈춘 것으로 알리고 더 조회하지 않는다
  for (const p of pending.filter((x) => now - (x.since ?? now) > STALL_MS)) {
    pending = pending.filter((x) => !same(x, p))
    lastPoll.delete(p.versionId)
    if (!failed.some((f) => same(f, p))) failed = [...failed, { ...p, error: STALL_MESSAGE, seen: false, stalled: true }]
  }
  // 조회할 차례가 된 버전만 읽는다
  const due = pending.filter((p) => now - (lastPoll.get(p.versionId) ?? 0) >= pollInterval(now - (p.since ?? now)))
  due.forEach((p) => lastPoll.set(p.versionId, now))
  const docs = new Map<number, IngestWatch>()
  due.forEach((p) => docs.set(p.docId, p))
  for (const [docId, meta] of docs) {
    const r = await listGuideVersions(user, docId)
    if (!r.ok) continue
    const ids = new Set(pending.filter((p) => p.docId === docId).map((p) => p.versionId))
    r.data.filter((v) => ids.has(v.id)).forEach((v) => apply({ docId, docCode: meta.docCode, title: meta.title, cat: meta.cat }, v, true))
  }
  if (JSON.stringify([pending, failed]) !== before) commit()
}

/** 관리자일 때만 몇 초마다 추적 중인 버전의 결과를 확인한다 (화면이 보일 때만) */
export function startIngestPolling(user: User): () => void {
  if (user.serviceRole !== 'ADMIN') return () => {}
  return visiblePoll(() => void pollIngest(user), 3000)
}

/** 실패 목록 창(관리자가 점을 보고 직접 여는 창)이 열려 있는지 */
let listOpen = false
const listListeners = new Set<() => void>()
export const isFailureListOpen = () => listOpen
export function setFailureListOpen(open: boolean) {
  if (listOpen === open) return
  listOpen = open
  listListeners.forEach((f) => f())
}
export function watchFailureList(onChange: () => void): () => void {
  listListeners.add(onChange)
  return () => {
    listListeners.delete(onChange)
  }
}

/** 테스트에서 추적 기록을 비운다 */
export function resetIngestWatch() {
  pending = []
  failed = []
  lastPoll.clear()
  listOpen = false
  commit()
}
