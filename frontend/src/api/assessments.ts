/**
 * AI 판단 이력 (관리자). (design/ITssue-Prototype.html 접수 상세의 "AI 판단 이력", docs/api/02 IQ-10)
 *   GET /inquiries/{inquiryId}/assessments   AI 원래 판단(aiOutput)과 규칙이 바꾼 내역(overrideReasons), createdAt 오름차순
 * 관리자만 열 수 있다 (다른 역할은 403). 문의자·담당자 화면에는 보여 주지 않는다.
 * facts·aiOutput·overrideReasons 는 서버가 저장한 JSON 의 키만 camelCase 로 바꿔 주므로, 값은 모르는 모양이 와도 화면이 깨지지 않게 다룬다.
 * 모의 모드는 접수의 분류·긴급도로 판단 1건을 만든다 (규칙이 바꾼 내역이 있는 경우와 없는 경우를 함께 시연).
 */
import { request } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import { findStaffTicket, allStaffTickets } from './mock/staffTickets'
import { fail, ok, type ApiResult, type User } from './types'

/** 규칙이 AI 판단을 바꾼 한 건 */
export interface OverrideReason {
  field: string
  ai: unknown
  final: unknown
  rule: string
  reason: string
}

export interface Assessment {
  id: number
  inquiryId: number
  facts: { summary?: string } & Record<string, unknown>
  missingItems: string[]
  urgentSignal: boolean
  categoryCode: string | null
  inquiryTypeId: number | null
  urgency: string | null
  urgencyReason: string | null
  /** ANSWER · ASK_MORE · ESCALATE · OUT_OF_SCOPE */
  action: string | null
  aiOutput: { urgencySuggested?: string; categoryCode?: string; action?: string; confidence?: number } & Record<string, unknown>
  overrideReasons: OverrideReason[]
  createdAt: string
}

export const ACTION_LABEL: Record<string, string> = { ANSWER: 'AI 답변', ASK_MORE: '추가 질문', ESCALATE: '담당자 연결', OUT_OF_SCOPE: '지원 범위 밖' }
/** AI 가 추가 질문으로 더 물어본 항목 (missing_items). 모르는 항목은 서버가 준 이름 그대로 */
export const MISSING_LABEL: Record<string, string> = { situation: '상황', target_system: '대상 시스템', symptom: '증상', occurred_at: '발생 시점', impact: '영향 범위', tried_actions: '시도한 조치' }
/** 규칙이 바꾼 항목 이름 (모르는 항목은 서버가 준 이름 그대로) */
export const FIELD_LABEL: Record<string, string> = {
  urgency: '긴급도',
  action: '처리 방향',
  categoryCode: '분류',
  category: '분류',
  inquiryTypeId: '문의 유형',
  title: '제목',
  group: '담당 그룹',
}

/** 관리자가 아니면 403 처럼 닫는다 (서버도 같다) */
export async function listAssessments(user: User, inquiryId: number): Promise<ApiResult<Assessment[]>> {
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 볼 수 있어요.')
  if (!USE_MOCK_INQUIRY) {
    const r = await request<{ items: Assessment[] }>(`/inquiries/${inquiryId}/assessments`)
    return r.ok ? ok(r.data.items) : r
  }
  const t = allStaffTickets().find((x) => x.inquiryId === inquiryId) ?? findStaffTicket(inquiryId)
  if (!t) return fail('INQUIRY_NOT_FOUND', '문의를 찾을 수 없어요.')
  const cat = t.category?.code ?? null
  const final = t.urgency ?? 'P3'
  // 보안 문의는 최소 P2, P1 은 업무 중단·다수 영향 규칙이 올린 것으로 보여 준다 (시연용)
  let ai: string = final
  let over: OverrideReason[] = []
  if (cat === 'SEC' && (final === 'P1' || final === 'P2')) {
    ai = 'P3'
    over = [{ field: 'urgency', ai, final, rule: 'SEC_MIN_P2', reason: '보안 사고 의심은 최소 높음' }]
  } else if (final === 'P1') {
    ai = 'P2'
    over = [{ field: 'urgency', ai, final, rule: 'WORK_STOPPED_P1', reason: '업무 중단·다수 영향은 긴급' }]
  }
  return ok([
    {
      id: t.id,
      inquiryId: t.inquiryId,
      facts: { summary: t.summary },
      missingItems: [],
      urgentSignal: over.length > 0,
      categoryCode: cat,
      inquiryTypeId: null,
      urgency: final,
      urgencyReason: over[0]?.reason ?? null,
      action: 'ESCALATE',
      aiOutput: { urgencySuggested: ai, categoryCode: cat ?? undefined, action: 'ESCALATE', confidence: over.length ? 0.74 : 0.86 },
      overrideReasons: over,
      createdAt: t.createdAt,
    },
  ])
}
