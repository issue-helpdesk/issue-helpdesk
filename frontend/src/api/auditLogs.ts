/**
 * 운영 기록 (관리자). (design/ITssue-Prototype.html viewAudit, docs/api/05 OP-04)
 *   GET /audit-logs   AI 판단·접수 확정·담당자 배정 같은 주요 처리 기록. 원문은 없고 결과(result)와 사유(reason)만 있다
 * 관리자만 열 수 있다. 서버는 page·size(최대 100)·sort(createdAt,desc)·eventType(반복)·targetType·targetId·actorId·createdFrom/To 를 받는다.
 *
 * 서버가 주는 값은 영문 코드(eventType)와 코드·내부 번호(result·targetId)라서, 화면 말은 이 파일의 사전(EVENT_LABEL)과
 * describeAudit()으로 바꾼다. 사전은 서버의 운영 기록 이벤트를 기준으로 한다 (backend services 의 audit_logs.add 호출).
 * 서버에 새 이벤트가 생기면 여기에 한 줄 추가한다. 사전에 없는 이벤트·값은 서버가 준 글 그대로 보여 준다.
 * 모의 모드는 서버가 주는 모양 그대로의 시연 기록 24건으로 같은 조건을 걸러 준다.
 */
import { request } from '../core/apiClient'
import { findStaffTicket } from './mock/staffTickets'
import { USE_MOCK_OPS } from '../core/config'
import type { Page } from './inquiries'
import type { UserRef } from './ticketTypes'
import { ROLE_LABEL } from '../core/roles'
import { fail, ok, type ApiResult, type ServiceRole, type User } from './types'

export interface AuditLog {
  id: number
  eventType: string
  targetType: string | null
  targetId: number | null
  /** 접수 대상은 그 접수, 문의 대상은 지금 연결된 접수 (R-40). 연결이 없거나 그 밖의 대상이면 null. 서버가 아직 안 주면 없다 */
  ticketId?: number | null
  receiptNo?: string | null
  actorId: number | null
  /** null 이면 시스템이 한 일 */
  actor: UserRef | null
  result: string | null
  reason: string | null
  createdAt: string
}

/** 대상 종류 (서버 값 → 화면 말) */
export const TARGET_LABEL: Record<string, string> = { inquiry: '문의', ticket: '접수', document: '문서', user: '사용자', faq: 'FAQ', guide_cluster: 'AI 가이드 제안', security_alert: '보안 알림' }
export const TARGET_KINDS = ['inquiry', 'ticket', 'document', 'user', 'faq', 'guide_cluster', 'security_alert'] as const
/**
 * 이벤트 → 화면 이름·배지 색 (대상별로 묶어 둔다). 선택 상자도 이 순서로 보인다.
 * 서버 코드는 화면에서 이름 아래에 작게 같이 보여 준다.
 */
export const EVENT_LABEL: Record<string, { label: string; tone: string }> = {
  // 보안 알림 관리 API가 남기는 처리 기록이다.
  SECURITY_ALERT_REVIEW: { label: '보안 알림 확인 시작', tone: 'prog' },
  SECURITY_ALERT_CLOSE: { label: '보안 알림 종결', tone: 'ok' },
  SECURITY_ALERT_VIEW: { label: '보안 알림 문의 열람', tone: 'recv' },
  // 문의
  SENSITIVE_INPUT: { label: '민감정보 가림', tone: 'recv' },
  BLOCK: { label: '근거 차단', tone: 'urg' },
  FAIL: { label: 'AI 실패', tone: 'urg' },
  URGENT_CLOSED: { label: '긴급 건 종료', tone: 'warn' },
  // 접수
  CONFIRM: { label: '접수 확정', tone: 'ok' },
  REASSIGN: { label: '재배정', tone: 'warn' },
  INTEGRATION_RETRY: { label: '연동 재처리', tone: 'asg' },
  // 문서
  DOCUMENT_ACTIVATE: { label: '문서 활성화', tone: 'ok' },
  DOCUMENT_DEACTIVATE: { label: '문서 비활성화', tone: 'recv' },
  DOCUMENT_VERSION_ACTIVATE: { label: '현행 버전 전환', tone: 'prog' },
  DOCUMENT_VERSION_RETRY: { label: '버전 재처리', tone: 'asg' },
  DOCUMENT_POLICY_CHANGE: { label: '열람·전송 정책 변경', tone: 'warn' },
  // 해결 사례 가이드화: 예전 단건 등록 기록과 현재 묶음 검토 기록을 함께 지원한다.
  CASE_GUIDE_REGISTER: { label: '해결 사례 가이드 등록', tone: 'ok' },
  GUIDE_CLUSTER_REGISTER: { label: 'AI 가이드 초안 등록', tone: 'ok' },
  GUIDE_CLUSTER_REBASE: { label: 'AI 제안 기준 다시 맞추기', tone: 'prog' },
  GUIDE_CLUSTER_TARGET_CHANGE: { label: 'AI 제안 넣을 문서 변경', tone: 'prog' },
  GUIDE_CLUSTER_REJECT: { label: 'AI 제안 반영 안함', tone: 'recv' },
  GUIDE_CLUSTER_APPLY: { label: 'AI 제안 직접 반영 표시', tone: 'ok' },
  // 사용자
  USER_CREATE: { label: '계정 생성', tone: 'ok' },
  USER_ROLE_CHANGE: { label: '역할 변경', tone: 'prog' },
  USER_STATUS_CHANGE: { label: '계정 상태 변경', tone: 'warn' },
  PASSWORD_RESET: { label: '임시 비밀번호 재발급', tone: 'asg' },
  LOGIN_BLOCKED: { label: '로그인 차단', tone: 'urg' },
  ACCOUNT_LOCKED: { label: '계정 잠김', tone: 'urg' },
  // FAQ
  FAQ_DELETE: { label: 'FAQ 삭제', tone: 'warn' },
  FAQ_AUTO_UNPUBLISH: { label: 'FAQ 자동 중단', tone: 'warn' },
}

const ACCOUNT_STATUS: Record<string, string> = { ACTIVE: '정상', LOCKED: '잠김', INACTIVE: '이용 제한' } // 계정 관리 화면과 같은 말
const SCOPE_LABEL: Record<string, string> = { ALL: '전 직원', AGENT: '담당자 이상', ADMIN: '관리자만' }
const POLICY_LABEL: Record<string, string> = { ALLOWED: '허용', MASKED: '마스킹 후 허용', BLOCKED: '금지' }
const SENSITIVE_LABEL: Record<string, string> = { PASSWORD: '비밀번호', OTP: '인증번호', API_KEY: 'API 키', PRIVATE_KEY: '비공개 키', RRN: '주민등록번호', CARD: '카드번호', ACCOUNT: '계좌번호' }

/** 화면에 보일 말: name 은 구분 칸 둘째 줄의 식별 이름(서버가 결과에 담아 준 접수번호·문서 코드·FAQ 번호), out 은 결과, reason 은 사유 */
interface AuditText {
  name: string
  out: string
  reason: string
}

/**
 * 서버가 준 결과·사유 값을 화면 말로 바꾼다. 서버가 주지 않은 값(접수번호·사용자 이름 등)은 만들어 내지 않는다.
 * 모르는 이벤트·값은 서버가 준 글 그대로 둔다. (서버 값의 뜻은 docs/api/06 의 "운영 기록 표시 문구 확인" 참고)
 */
export function describeAudit(x: Pick<AuditLog, 'eventType' | 'result' | 'reason'>): AuditText {
  const res = x.result ?? ''
  const reason = x.reason ?? ''
  const t = (name: string, out: string, why = reason): AuditText => ({ name, out, reason: why })
  switch (x.eventType) {
    case 'SECURITY_ALERT_REVIEW':
    case 'SECURITY_ALERT_CLOSE':
    case 'SECURITY_ALERT_VIEW':
      return t('', ({ REVIEW: '확인 시작', CLOSE: '종결', VIEW_ORIGINAL: '저장된 문의 열람' } as Record<string, string>)[res] ?? res)
    case 'CONFIRM':
      return t(res, '접수 확정')
    case 'DOCUMENT_ACTIVATE':
      return t(res, '활성화')
    case 'DOCUMENT_DEACTIVATE':
      return t(res, '비활성화')
    case 'FAQ_DELETE':
      return t(res, '삭제')
    case 'FAQ_AUTO_UNPUBLISH':
      return t(res, '자동으로 게시 중단')
    // 담당자 배정 이력의 종류: 담당자가 없던 접수는 배정, 있던 접수는 재배정, 정할 사람이 없으면 배정 실패
    case 'REASSIGN':
      return t('', { ASSIGN: '배정', REASSIGN: '재배정', FAIL: '배정 실패' }[res] ?? res)
    case 'INTEGRATION_RETRY':
      return t('', { QUEUED: '재처리 예약', ALREADY_APPLIED: '이미 반영돼 있음', LINKED_EXISTING: '기존 ITSM 이슈에 연결' }[res] ?? res)
    case 'BLOCK':
      if (res === 'DOC_BLOCKED') return t('', '근거 문서 차단', reason ? `문서 ${reason}` : '')
      return t('', res === 'ALL_BLOCKED' ? '근거 전체 차단, 담당자 연결 제안' : res)
    case 'FAIL':
      // 사유 앞의 "④ "는 서버 내부의 민감정보 필터 적용 지점 번호라 관리자에게는 뜻이 없어 뗀다 (docs/api/06 확인 문구 4번)
      return t('', { FILTER_FAILED: '민감정보 필터 실패', AI_FAILED: 'AI 답변 실패' }[res] ?? res, reason.replace(/^[①-⑳]\s*/, ''))
    case 'SENSITIVE_INPUT':
      return t('', `가린 항목: ${SENSITIVE_LABEL[res] ?? res}`)
    case 'URGENT_CLOSED':
      return t('', '긴급 징후가 있었는데 담당자 연결 없이 종료')
    case 'DOCUMENT_VERSION_ACTIVATE':
      return t('', `현행 ${res}`)
    case 'DOCUMENT_VERSION_RETRY':
      return t('', res.replace('파일 교체', '— 파일을 바꿔 재처리').replace('같은 파일', '— 같은 파일로 재처리'))
    case 'DOCUMENT_POLICY_CHANGE': {
      // 예: "v2 ALL/ALLOWED → ADMIN/BLOCKED" = 버전 열람 범위/외부 전송 정책 이전 → 이후
      const m = res.match(/^(\S+) (\w+)\/(\w+) → (\w+)\/(\w+)$/)
      return t('', m ? `${m[1]} · 열람 ${SCOPE_LABEL[m[2]] ?? m[2]} → ${SCOPE_LABEL[m[4]] ?? m[4]} / 외부 전송 ${POLICY_LABEL[m[3]] ?? m[3]} → ${POLICY_LABEL[m[5]] ?? m[5]}` : res)
    }
    case 'CASE_GUIDE_REGISTER':
      return t('', res)
    case 'GUIDE_CLUSTER_REGISTER':
    case 'GUIDE_CLUSTER_REBASE':
    case 'GUIDE_CLUSTER_TARGET_CHANGE':
    case 'GUIDE_CLUSTER_REJECT':
    case 'GUIDE_CLUSTER_APPLY':
      // 결과의 알려진 코드만 바꾸고, 버전·내부 번호·모르는 값과 사유는 원문을 유지한다.
      return t('', res.replace(/\b(ADD_ITEM|CHANGE|NEW_GUIDE|MANUAL_CANDIDATE|SEC_MANUAL|REVIEWING|REJECTED|APPLIED)\b/g, (code) => ({
        ADD_ITEM: '항목 추가', CHANGE: '항목 변경', NEW_GUIDE: '새 가이드', MANUAL_CANDIDATE: '매뉴얼 후보',
        SEC_MANUAL: '보안 사고 직접 검토', REVIEWING: '검토 중', REJECTED: '반영 안함', APPLIED: '반영 완료',
      })[code] ?? code))
    case 'USER_CREATE':
      return t('', `계정 생성 (역할: ${ROLE_LABEL[res as ServiceRole] ?? res})`)
    case 'USER_ROLE_CHANGE':
      return t('', `역할 → ${ROLE_LABEL[res as ServiceRole] ?? res}`)
    case 'USER_STATUS_CHANGE':
      return t('', `상태 → ${ACCOUNT_STATUS[res] ?? res}`)
    case 'PASSWORD_RESET':
      return t('', `임시 비밀번호 재발급 (상태: ${ACCOUNT_STATUS[res] ?? res})`)
    case 'LOGIN_BLOCKED':
      return t('', `로그인 차단 (상태: ${ACCOUNT_STATUS[res] ?? res})`)
    case 'ACCOUNT_LOCKED':
      return t('', '연속 실패로 잠김')
    default:
      return t('', res)
  }
}

interface AuditQuery {
  page?: number
  size?: number
  eventType?: string
  targetType?: string
  /** 오늘부터 며칠 전까지 (0=오늘, 7=최근 7일). 비우면 전체 기간 */
  days?: number
}

const PAGE_SIZE = 50
const ago = (d: number, h: number, m: number) => new Date(Date.now() - d * 86_400_000 - h * 3_600_000 - m * 60_000).toISOString()
const ADMIN: UserRef = { id: 3, employeeNo: 'EMP-1178', name: '이건우' }
const user = (id: number, employeeNo: string, name: string): UserRef => ({ id, employeeNo, name })
const row = (id: number, createdAt: string, eventType: string, targetType: string, targetId: number, actor: UserRef | null, result: string, reason: string | null = null): AuditLog => ({
  id,
  eventType,
  targetType,
  targetId,
  actorId: actor?.id ?? null,
  actor,
  result,
  reason,
  createdAt,
})
/** 시연 기록 24건 (최근 것부터). 서버가 주는 모양 그대로다: 결과는 코드, 대상은 내부 번호, 처리자가 없으면 시스템 */
const MOCK: AuditLog[] = [
  row(24, ago(0, 0, 12), 'CONFIRM', 'ticket', 5001, user(7, 'EMP-1003', '김민지'), 'RCPT-0881'),
  row(23, ago(0, 0, 16), 'INTEGRATION_RETRY', 'ticket', 5001, ADMIN, 'QUEUED', 'ITSM 응답 시간 초과 후 재시도'),
  row(22, ago(0, 0, 31), 'REASSIGN', 'ticket', 5002, ADMIN, 'REASSIGN', '기존 담당자 휴가'),
  row(21, ago(0, 0, 45), 'REASSIGN', 'ticket', 5003, ADMIN, 'FAIL', '해당 분류 담당 가능자 없음'),
  row(20, ago(0, 0, 56), 'INTEGRATION_RETRY', 'ticket', 5004, ADMIN, 'LINKED_EXISTING', 'ITSM 이슈를 수동으로 만든 것 확인'),
  row(19, ago(0, 1, 12), 'BLOCK', 'inquiry', 214, null, 'DOC_BLOCKED', 'IT-SEC-003'),
  row(18, ago(0, 1, 12), 'BLOCK', 'inquiry', 215, null, 'ALL_BLOCKED'),
  row(17, ago(0, 1, 28), 'FAIL', 'inquiry', 216, null, 'FILTER_FAILED', '검색 근거 IT-SEC-003'),
  row(16, ago(0, 1, 46), 'FAIL', 'inquiry', 217, null, 'AI_FAILED', 'TIMEOUT'),
  row(15, ago(0, 2, 4), 'SENSITIVE_INPUT', 'inquiry', 218, user(11, 'EMP-1156', '최하은'), 'PASSWORD', '1건'),
  row(14, ago(0, 2, 25), 'URGENT_CLOSED', 'inquiry', 219, user(12, 'EMP-1049', '박서연'), 'CLOSED_UNRESOLVED'),
  row(13, ago(0, 2, 46), 'DOCUMENT_ACTIVATE', 'document', 12, ADMIN, 'IT-ACC-001'),
  row(12, ago(0, 2, 50), 'DOCUMENT_DEACTIVATE', 'document', 9, ADMIN, 'IT-HW-003'),
  row(11, ago(1, 3, 6), 'DOCUMENT_VERSION_ACTIVATE', 'document', 12, ADMIN, 'v1 → v2'),
  row(10, ago(1, 3, 21), 'DOCUMENT_VERSION_RETRY', 'document', 12, ADMIN, 'v3 파일 교체'),
  row(9, ago(1, 3, 36), 'DOCUMENT_POLICY_CHANGE', 'document', 7, ADMIN, 'v2 ALL/ALLOWED → ADMIN/BLOCKED', '민감 문서로 분류'),
  row(8, ago(2, 3, 5), 'USER_CREATE', 'user', 10, ADMIN, 'EMPLOYEE'),
  row(7, ago(2, 3, 23), 'USER_ROLE_CHANGE', 'user', 10, ADMIN, 'AGENT', '팀 이동'),
  row(6, ago(3, 3, 45), 'USER_STATUS_CHANGE', 'user', 6, ADMIN, 'INACTIVE', '퇴사'),
  row(5, ago(3, 4, 4), 'PASSWORD_RESET', 'user', 7, ADMIN, 'ACTIVE', '분실 신고'),
  row(4, ago(4, 4, 27), 'LOGIN_BLOCKED', 'user', 6, null, 'INACTIVE'),
  row(3, ago(4, 4, 58), 'ACCOUNT_LOCKED', 'user', 5, null, 'LOCKED'),
  row(2, ago(5, 5, 20), 'FAQ_DELETE', 'faq', 7, ADMIN, 'FAQ-007'),
  row(1, ago(5, 5, 42), 'FAQ_AUTO_UNPUBLISH', 'faq', 12, ADMIN, 'FAQ-012', '문서 12 변경으로 공개 출처 없음'),
]

/** 운영 기록 목록. 관리자가 아니면 막는다 (서버도 403) */
export async function listAuditLogs(user: User, q: AuditQuery = {}): Promise<ApiResult<Page<AuditLog>>> {
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 볼 수 있어요.')
  const page = q.page ?? 1
  const size = q.size ?? PAGE_SIZE
  if (!USE_MOCK_OPS) {
    const p = new URLSearchParams({ page: String(page), size: String(size), sort: 'createdAt,desc' })
    if (q.eventType) p.append('eventType', q.eventType)
    if (q.targetType) p.set('targetType', q.targetType)
    if (q.days !== undefined) {
      const day = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10)
      p.set('createdFrom', day(q.days))
      p.set('createdTo', day(0))
    }
    return request<Page<AuditLog>>(`/audit-logs?${p}`)
  }
  const from = q.days === undefined ? 0 : Date.now() - (q.days + 1) * 86_400_000
  const rows = MOCK.filter((r) => (!q.eventType || r.eventType === q.eventType) && (!q.targetType || r.targetType === q.targetType) && Date.parse(r.createdAt) >= from)
  const start = (page - 1) * size
  // 서버(R-40)처럼 접수 대상에는 접수 ID·접수번호를 붙인다 (모의는 실제 시연 접수와 맞춘다)
  const link = (r: AuditLog): AuditLog => {
    const t = r.targetType === 'ticket' && r.targetId !== null ? findStaffTicket(r.targetId) : undefined
    return t ? { ...r, ticketId: t.id, receiptNo: t.receiptNo } : { ...r, ticketId: null, receiptNo: null }
  }
  return ok({ items: rows.slice(start, start + size).map(link), page, size, totalCount: rows.length, totalPages: Math.max(1, Math.ceil(rows.length / size)) })
}
