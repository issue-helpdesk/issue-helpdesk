/**
 * 운영 기록 (관리자). (design/ITssue-Prototype.html viewAudit, docs/api/05 OP-04)
 *   GET /audit-logs   AI 판단·접수 확정·담당자 배정 같은 주요 처리 기록. 원문은 없고 결과(result)와 사유(reason)만 있다
 * 관리자만 열 수 있다. 서버는 page·size(최대 100)·sort(createdAt,desc)·eventType(반복)·targetType·targetId·actorId·createdFrom/To 를 받는다.
 * 모의 모드는 시연 기록 12건으로 같은 조건을 걸러 준다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_OPS } from '../core/config'
import type { Page } from './inquiries'
import type { UserRef } from './ticketTypes'
import { fail, ok, type ApiResult, type User } from './types'

export interface AuditLog {
  id: number
  eventType: string
  targetType: string | null
  targetId: number | null
  actorId: number | null
  /** null 이면 시스템이 한 일 */
  actor: UserRef | null
  result: string | null
  reason: string | null
  createdAt: string
}

/** 대상 종류 (서버 값 → 화면 말) */
export const TARGET_LABEL: Record<string, string> = { inquiry: '문의', ticket: '접수', document: '문서', user: '사용자', faq: 'FAQ' }
export const TARGET_KINDS = ['inquiry', 'ticket', 'document', 'user', 'faq'] as const
/** 자주 보는 이벤트 (서버가 더 많은 종류를 줄 수 있어, 모르는 이벤트는 서버가 준 이름 그대로 보여 준다) */
export const EVENT_LABEL: Record<string, { label: string; tone: string }> = {
  CLASSIFY: { label: '분류 판단', tone: 'prog' },
  CONFIRM: { label: '접수 확정', tone: 'ok' },
  ASSIGN: { label: '담당자 배정', tone: 'ok' },
  REASSIGN: { label: '재배정', tone: 'warn' },
  BLOCK: { label: '근거 차단', tone: 'urg' },
  FAIL: { label: 'AI 실패', tone: 'urg' },
}

export interface AuditQuery {
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

/** 시연 기록 (최근 것부터) */
const MOCK: AuditLog[] = [
  { id: 12, eventType: 'REASSIGN', targetType: 'ticket', targetId: 5001, actorId: 3, actor: ADMIN, result: '담당자 성민경 → 황민석', reason: '기존 담당자 휴가로 재배정', createdAt: ago(0, 0, 20) },
  { id: 11, eventType: 'ASSIGN', targetType: 'ticket', targetId: 5033, actorId: null, actor: null, result: '담당자 곽지민 지정 (자동 배정)', reason: '업무량이 가장 적은 근무자', createdAt: ago(0, 0, 50) },
  { id: 10, eventType: 'CONFIRM', targetType: 'inquiry', targetId: 9001, actorId: 7, actor: { id: 7, employeeNo: 'EMP-1003', name: '김민지' }, result: '접수 확정', reason: null, createdAt: ago(0, 1, 2) },
  { id: 9, eventType: 'CLASSIFY', targetType: 'inquiry', targetId: 9001, actorId: null, actor: null, result: '정보보안 · 긴급도 P3 → P1', reason: '보안 사고 의심은 최소 P2', createdAt: ago(0, 1, 3) },
  { id: 8, eventType: 'BLOCK', targetType: 'inquiry', targetId: 9005, actorId: null, actor: null, result: 'AI 답변 차단, 담당자 연결 제안', reason: '근거 문서가 모두 외부 전송 금지', createdAt: ago(0, 2, 40) },
  { id: 7, eventType: 'FAIL', targetType: 'inquiry', targetId: 9007, actorId: null, actor: null, result: 'AI 답변을 만들지 못함 (503)', reason: 'AI 서비스 응답 시간 초과', createdAt: ago(0, 5, 0) },
  { id: 6, eventType: 'ASSIGN', targetType: 'ticket', targetId: 5004, actorId: 3, actor: ADMIN, result: '담당자 곽지민 지정 (수동)', reason: '자동 배정 후보 없음', createdAt: ago(0, 5, 30) },
  { id: 5, eventType: 'CLASSIFY', targetType: 'inquiry', targetId: 9002, actorId: null, actor: null, result: '계정·로그인 · 긴급도 P3', reason: null, createdAt: ago(1, 1, 0) },
  { id: 4, eventType: 'CONFIRM', targetType: 'inquiry', targetId: 9002, actorId: 7, actor: { id: 7, employeeNo: 'EMP-1003', name: '김민지' }, result: '접수 확정', reason: null, createdAt: ago(1, 1, 30) },
  { id: 3, eventType: 'REASSIGN', targetType: 'ticket', targetId: 5010, actorId: 3, actor: ADMIN, result: '담당자 공다람 → 김토끼', reason: '팀 변경', createdAt: ago(1, 3, 0) },
  { id: 2, eventType: 'FAIL', targetType: 'document', targetId: 98, actorId: null, actor: null, result: '가이드 적재 실패', reason: '문서에서 글자를 찾지 못했습니다', createdAt: ago(2, 6, 0) },
  { id: 1, eventType: 'ASSIGN', targetType: 'ticket', targetId: 5020, actorId: null, actor: null, result: '담당자 성민경 지정 (자동 배정)', reason: '업무량이 가장 적은 근무자', createdAt: ago(5, 2, 0) },
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
  return ok({ items: rows.slice(start, start + size), page, size, totalCount: rows.length, totalPages: Math.max(1, Math.ceil(rows.length / size)) })
}
