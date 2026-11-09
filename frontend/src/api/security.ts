/**
 * 보안·감사 알림 (관리자, 제안). (design/ITssue-Prototype.html 보안·감사 알림)
 * 문의가 접수되지 않았어도 ITssue 안에서 감지한 신호(민감정보 입력, 외부 전송 금지 문서 질의, 로그인 반복 실패 등)를 모아 본다.
 * 문의 서버 모드에서는 실제 /security-alerts API 를 사용한다. 모의 모드만 시연 데이터다.
 * 원문은 사유를 입력해야 볼 수 있고 열람 기록이 처리 이력에 남는다.
 */
import { request } from '../core/apiClient'
import { serverAction, serverCounts, serverGet, serverList, serverPath } from './securityServer'
import { USE_MOCK_INQUIRY } from '../core/config'
import { nowIso } from '../core/format'
import { subscribe, notify } from './mock/chatStore'
import { fail, ok, type ApiResult, type User } from './types'

export type SecSeverity = '높음' | '중간' | '낮음'
export type SecStatus = '신규' | '확인 중' | '종결'
export const SEC_TYPES = ['민감정보 입력', '외부 전송 금지 문서 질의', '로그인 반복 실패', '이용 제한 계정 접속 시도', '긴급 징후 후 접수 없이 종료', '비정상 대량 질의', '보안 사고 의심', '권한·승인 우회 요청', '보안 통제 해제·기록 은폐 요청', '제한 정보 추출 요청', '자료 반출 우회 요청', 'AI 통제 우회 요청', 'AI 답변 거절 문의'] as const
export type SecType = (typeof SEC_TYPES)[number]

export interface SecLog {
  at: string
  who: string
  what: string
}
export interface SecAlert {
  id: string
  /** 감지 시각 */
  at: string
  type: SecType
  severity: SecSeverity
  employeeNo: string
  name: string
  dept: string
  /** 민감정보를 가린 내용 */
  mask: string
  /** 감지 규칙 */
  rule: string
  status: SecStatus
  log: SecLog[]
  hasOriginal?: boolean
  hitCount?: number
}
/** 원문은 목록·상세에 싣지 않고 열람을 요청할 때만 준다 */
const RAW: Record<string, string> = {}

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()
let alerts: SecAlert[] = []

function seed(): SecAlert[] {
  const e = (n: number, h: number, type: SecType, severity: SecSeverity, employeeNo: string, name: string, dept: string, mask: string, raw: string, rule: string, status: SecStatus, log: [number, string, string][]): SecAlert => {
    RAW[`SEC-${n}`] = raw
    return { id: `SEC-${n}`, at: hoursAgo(h), type, severity, employeeNo, name, dept, mask, rule, status, log: log.map(([lh, who, what]) => ({ at: hoursAgo(lh), who, what })) }
  }
  return [
    e(30, 0.5, '비정상 대량 질의', '중간', 'EMP-1082', '공은서', '디자인팀', '3분간 41건 질의 (평소 일 3건)', '질의 41건 · 동일 문장 반복', '단시간 질의 임계치 초과', '신규', [[0.5, 'ITssue', '이벤트 감지 · 단시간 질의 임계치 초과']]),
    e(29, 2, '긴급 징후 후 접수 없이 종료', '높음', 'EMP-1003', '김민지', '인사팀', '피싱 의심 링크를 눌렀다고 입력 후 담당자 연결을 거절하고 종료', '피싱 의심 링크를 눌렀어요 → 미연결 (종료) (시연 가상 문장)', '긴급 징후 + 연결 거절', '신규', [[2, 'ITssue', '이벤트 감지 · 긴급 징후 + 연결 거절']]),
    e(28, 4, '민감정보 입력', '높음', 'EMP-1003', '김민지', '인사팀', '대화에 6자리 인증번호로 보이는 값 입력 (●●●●●●)', 'OTP 번호 123456 입력함 (시연용 가짜 값)', '인증번호 패턴 감지', '확인 중', [[3.8, '정보보안팀', '확인 시작 · 정보보안팀 정담당'], [4, 'ITssue', '이벤트 감지 · 인증번호 패턴 감지']]),
    e(27, 20, '로그인 반복 실패', '중간', 'EMP-1037', '황지윤', '영업1팀', '10분 사이 5회 실패로 계정 잠금', '실패 5회 · 접속 IP 사내망', '5회 실패 잠금', '신규', [[20, 'ITssue', '이벤트 감지 · 5회 실패 잠금']]),
    e(26, 24, '이용 제한 계정 접속 시도', '낮음', 'EMP-1005', '최하준', '영업2팀', '이용 제한 상태 계정으로 로그인 2회 시도', '로그인 시도 2회 차단', '이용 제한 계정 시도', '종결', [[23, '서비스데스크', '종결 · 본인 확인 완료, 제한 사유 안내함'], [24, 'ITssue', '이벤트 감지 · 이용 제한 계정 시도']]),
    e(25, 28, '외부 전송 금지 문서 질의', '중간', 'EMP-1082', '공은서', '디자인팀', '보안 예외·USB 반출 정책 질의 (AI 답변 차단, 담당자 연결 제안)', '보안 예외 USB 반출 절차 알려줘 (시연 가상 문장)', '전송 금지 문서 질의', '종결', [[26, '정보보안팀', '종결 · 정상 문의 확인 (접수 연결됨)'], [28, 'ITssue', '이벤트 감지 · 전송 금지 문서 질의']]),
  ]
}

/** 시연 알림을 처음 상태로 되돌린다 (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetSecurityMock() {
  Object.keys(RAW).forEach((k) => delete RAW[k])
  alerts = seed()
}
resetSecurityMock()

/** 보안 알림이 바뀔 때 알려 준다 (사이드바 배지·대시보드 띠가 다시 읽는다). 구독하자마자 한 번 알린다 */
export function watchSecurity(onChange: () => void): () => void {
  onChange()
  const unsubscribe = subscribe(onChange)
  const timer = USE_MOCK_INQUIRY ? undefined : window.setInterval(onChange, 30_000)
  return () => { unsubscribe(); window.clearInterval(timer) }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const adminOnly = (u: User) => (u.serviceRole === 'ADMIN' ? null : fail('FORBIDDEN', '관리자만 볼 수 있어요.'))
const find = (id: string) => alerts.find((a) => a.id === id)
const strip = (a: SecAlert): SecAlert => ({ ...a, log: a.log.map((l) => ({ ...l })) })
const RANK: Record<SecStatus, number> = { 신규: 0, '확인 중': 1, 종결: 2 }
const SEV: Record<SecSeverity, number> = { 높음: 0, 중간: 1, 낮음: 2 }

export interface SecCounts {
  신규: number
  '확인 중': number
  종결: number
  /** 미종결 중 심각도 높음 */
  high: number
  total: number
}

export interface SecPage { items: SecAlert[]; counts: SecCounts; page?: number; totalPages?: number; totalCount?: number }

/** 알림 목록. 기본 순서: 아직 끝나지 않은 것(신규 → 확인 중) 먼저, 같은 상태에서는 심각도 높은 것, 최근 것 먼저. 종결은 맨 아래 */
export async function listSecurityAlerts(user: User, filter: { status?: SecStatus | ''; type?: SecType | ''; page?: number } = {}): Promise<ApiResult<SecPage>> {
  await sleep(120)
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_INQUIRY) return serverList(filter)
  const items = alerts
    .filter((a) => (!filter.status || a.status === filter.status) && (!filter.type || a.type === filter.type))
    .sort((a, b) => RANK[a.status] - RANK[b.status] || SEV[a.severity] - SEV[b.severity] || Date.parse(b.at) - Date.parse(a.at))
    .map(strip)
  const n = (s: SecStatus) => alerts.filter((a) => a.status === s).length
  return ok({ items, counts: { 신규: n('신규'), '확인 중': n('확인 중'), 종결: n('종결'), high: alerts.filter((a) => a.severity === '높음' && a.status !== '종결').length, total: alerts.length } })
}

/** 대시보드·사이드바용 건수 */
export async function countSecurityAlerts(user: User): Promise<SecCounts | null> {
  if (!USE_MOCK_INQUIRY) {
    if (adminOnly(user)) return null
    const r = await serverCounts()
    return r.ok ? r.data : null
  }
  const r = await listSecurityAlerts(user)
  return r.ok ? r.data.counts : null
}

/** 원문 열람: 사유 필수, 열람 기록이 처리 이력에 남는다 */
export async function viewSecurityRaw(user: User, id: string, reason: string): Promise<ApiResult<{ raw: string; alert: SecAlert }>> {
  await sleep(120)
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_INQUIRY) {
    if (!reason.trim()) return fail('VALIDATION_ERROR', '열람 사유를 입력해 주세요.')
    const r = await request<{ messages: { content: string }[] }>(`${serverPath(id)}/original`, { method: 'POST', body: JSON.stringify({ reason }) })
    if (!r.ok) return r
    const detail = await serverGet(id)
    notify()
    return detail.ok ? ok({ raw: r.data.messages.map((m) => m.content).join('\n\n') || '저장된 문의가 없어요.', alert: detail.data }) : detail
  }
  const a = find(id)
  if (!a) return fail('NOT_FOUND', '알림을 찾을 수 없어요.')
  if (!reason.trim()) return fail('VALIDATION_ERROR', '열람 사유를 입력해 주세요.')
  a.log.unshift({ at: nowIso(), who: user.name, what: `원문 열람 · 사유: ${reason.trim()}` })
  notify()
  return ok({ raw: RAW[id] ?? '', alert: strip(a) })
}

/** 확인 시작 (신규 → 확인 중) */
export async function startSecurityReview(user: User, id: string): Promise<ApiResult<SecAlert>> {
  await sleep(120)
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_INQUIRY) {
    const r = await serverAction(id, 'review')
    if (r.ok) notify()
    return r
  }
  const a = find(id)
  if (!a) return fail('NOT_FOUND', '알림을 찾을 수 없어요.')
  if (a.status !== '신규') return fail('INVALID_STATE', '신규 알림만 확인을 시작할 수 있어요.')
  a.status = '확인 중'
  a.log.unshift({ at: nowIso(), who: user.name, what: '확인 시작' })
  notify()
  return ok(strip(a))
}

/** 종결 (확인 중 → 종결): 사유 필수 */
export async function closeSecurityAlert(user: User, id: string, reason: string): Promise<ApiResult<SecAlert>> {
  await sleep(120)
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_INQUIRY) {
    if (!reason.trim()) return fail('VALIDATION_ERROR', '종결 사유를 입력해 주세요.')
    const r = await serverAction(id, 'close', reason)
    if (r.ok) notify()
    return r
  }
  const a = find(id)
  if (!a) return fail('NOT_FOUND', '알림을 찾을 수 없어요.')
  if (a.status !== '확인 중') return fail('INVALID_STATE', '확인 중인 알림만 종결할 수 있어요.')
  if (!reason.trim()) return fail('VALIDATION_ERROR', '종결 사유를 입력해 주세요.')
  a.status = '종결'
  a.log.unshift({ at: nowIso(), who: user.name, what: `종결 · ${reason.trim()}` })
  notify()
  return ok(strip(a))
}

/** 알림 하나 (상세 창이 다시 읽을 때) */
export async function getSecurityAlert(user: User, id: string): Promise<ApiResult<SecAlert>> {
  const no = adminOnly(user)
  if (no) return no
  if (!USE_MOCK_INQUIRY) {
    return serverGet(id)
  }
  const a = find(id)
  return a ? ok(strip(a)) : fail('NOT_FOUND', '알림을 찾을 수 없어요.')
}
