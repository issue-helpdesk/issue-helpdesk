import { request } from '../core/apiClient'
import { ok, type ApiResult } from './types'
import type { SecAlert, SecCounts, SecSeverity, SecStatus, SecType } from './security'

type Ref = { id: number; employeeNo: string; name: string }
export interface ServerAlert {
  id: number
  alertType: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  status: 'NEW' | 'IN_REVIEW' | 'CLOSED'
  subject: Ref
  subjectDepartmentName: string | null
  summary: string
  rule: string
  occurrenceCount: number
  firstDetectedAt: string
  lastDetectedAt: string
  hasOriginal: boolean
  history: { kind: string; actor: Ref | null; reason: string | null; createdAt: string }[]
}
const labels: Record<string, SecType> = {
  S01: '보안 사고 의심', S02: '권한·승인 우회 요청', S03: '보안 통제 해제·기록 은폐 요청',
  S04: '제한 정보 추출 요청', S05: '자료 반출 우회 요청', S06: 'AI 통제 우회 요청',
  SENSITIVE_INPUT: '민감정보 입력', BLOCKED_DOC_QUERY: '외부 전송 금지 문서 질의', ACCOUNT_LOCKED: '로그인 반복 실패',
  LOGIN_BLOCKED: '이용 제한 계정 접속 시도', URGENT_CLOSED: '긴급 징후 후 접수 없이 종료', MASS_QUERY: '비정상 대량 질의',
}
const statuses: Record<ServerAlert['status'], SecStatus> = { NEW: '신규', IN_REVIEW: '확인 중', CLOSED: '종결' }
const severities: Record<ServerAlert['severity'], SecSeverity> = { HIGH: '높음', MEDIUM: '중간', LOW: '낮음' }
const historyNames: Record<string, string> = { DETECTED: '이벤트 감지', REVIEW: '확인 시작', CLOSE: '종결', VIEW_ORIGINAL: '저장된 문의 열람' }
export const serverPath = (id: string) => `/security-alerts/${encodeURIComponent(id.replace(/^SEC-/, ''))}`
export function toAlert(a: ServerAlert): SecAlert {
  return { id: `SEC-${a.id}`, at: a.firstDetectedAt, type: labels[a.alertType] ?? a.rule as SecType,
    severity: severities[a.severity], status: statuses[a.status], name: a.subject.name, employeeNo: a.subject.employeeNo,
    dept: a.subjectDepartmentName ?? '—', mask: a.summary, rule: `${a.alertType} · ${a.rule}`, hitCount: a.occurrenceCount,
    hasOriginal: a.hasOriginal,
    log: (a.history ?? []).map((h) => ({ at: h.createdAt, who: h.actor?.name ?? 'ITssue',
      what: `${historyNames[h.kind] ?? h.kind}${h.reason ? ` · ${h.reason}` : ''}` })) }
}
export async function serverCounts(): Promise<ApiResult<SecCounts>> {
  const r = await request<{ new: number; inReview: number; closed: number; openHigh: number; total: number }>('/security-alerts/counts')
  return r.ok ? ok({ 신규: r.data.new, '확인 중': r.data.inReview, 종결: r.data.closed, high: r.data.openHigh, total: r.data.total }) : r
}
export async function serverList(filter: { status?: SecStatus | ''; type?: SecType | ''; page?: number }) {
  const q = new URLSearchParams({ size: '100', page: String(filter.page ?? 1) })
  if (filter.status) q.set('status', Object.keys(statuses).find((key) => statuses[key as ServerAlert['status']] === filter.status)!)
  if (filter.type) q.set('alertType', Object.keys(labels).find((key) => labels[key] === filter.type)!)
  const [r, counts] = await Promise.all([
    request<{ items: ServerAlert[]; page: number; totalPages: number; totalCount: number }>(`/security-alerts?${q}`), serverCounts(),
  ])
  if (!r.ok) return r
  if (!counts.ok) return counts
  return ok({ ...r.data, items: r.data.items.map(toAlert), counts: counts.data })
}
export async function serverGet(id: string): Promise<ApiResult<SecAlert>> {
  const r = await request<ServerAlert>(serverPath(id))
  return r.ok ? ok(toAlert(r.data)) : r
}
export async function serverAction(id: string, action: 'review' | 'close', reason?: string): Promise<ApiResult<SecAlert>> {
  const r = await request<ServerAlert>(`${serverPath(id)}/${action}`, { method: 'POST', body: reason ? JSON.stringify({ reason }) : undefined })
  return r.ok ? ok(toAlert(r.data)) : r
}
