/**
 * 문의 대화 서버 연동 (docs/api/02 IQ-01~09). 서버 응답을 화면의 Inquiry 로 바꾸고, 서버 경로를 부른다.
 *
 * 서버는 문의(Inquiry)·메시지(Message)·다음 행동(nextActions)을 따로 주고, 화면은 단계(step)·카드·버튼이 붙은 문의 하나를 쓴다.
 * 그래서 이 파일이 둘 사이를 바꿔 준다.
 *   nextActions  REPLY → 정보 수집(collect) · CONFIRM_RESOLUTION → 해결 확인(answered, 해결·미해결 버튼)
 *                DECIDE_HANDOFF → 담당자 연결 제안(offer, 연결·종료 버튼) · START_NEW → 종료(closed)
 * 서버에 없는 것(새 답변 표시, 담당자 안내 메시지, 응답 없음 삭제·돌아옴 안내)은 값이 비어 있어 화면에서 나타나지 않는다.
 * 접수 초안·최종 접수(TK-01~04)와 접수 이후의 해결·미해결(TK-07)은 아직 연결하지 않았다.
 */
import { request } from '../core/apiClient'
import type { ChatBlock, ChatMessage, ChatReply, ChatStep, CategoryCode, Inquiry, InquiryStatus, LegacyCase, Ticket, Urgency, WorkStatus } from './chatTypes'
import type { Page } from './inquiries'
import type { TicketDetail } from './ticketTypes'
import { fail, ok, type ApiResult, type DisplayStatus, type InquirySummary, type InquiryStateKind } from './types'

/* ------------------------------------------------------------------ 서버 응답 모양 (docs/api/02) */
interface SSource {
  id: number
  sourceKind: 'DOCUMENT' | 'LEGACY'
  docCode: string | null
  version: string | null
  location: string | null
  excerpt: string | null
}
interface SMessage {
  id: number
  sessionId: number
  seq: number
  sender: 'USER' | 'AI' | 'SYSTEM'
  content: string
  sources: SSource[]
  createdAt: string
}
interface STicketRef {
  id: number
  receiptNo: string
  jiraKey: string | null
  workStatus: WorkStatus | null
}
interface SInquiry {
  id: number
  title: string | null
  status: InquiryStatus
  displayStatus: string
  categoryCode: CategoryCode | null
  urgency: Urgency | null
  action: string | null
  recommendedGroup: { id: number; name: string } | null
  resolutionResult: string | null
  activeDraftId: number | null
  ticket: STicketRef | null
  createdAt: string
  updatedAt: string | null
}
interface AiTurn {
  inquiry: SInquiry
  messages: SMessage[]
  nextActions: string[]
}
interface SSummary {
  id: number
  title: string | null
  displayStatus: DisplayStatus
  category: { code: CategoryCode; name: string } | null
  receiptNo: string | null
  createdAt: string
  updatedAt: string | null
}

/* ------------------------------------------------------------------ 요청 중복 방지 (Idempotency-Key) */
/**
 * IQ-01·08·09 는 요청마다 새로 만든 Idempotency-Key 가 필요하다. 응답을 받지 못해 다시 보낼 때는 같은 키를 써야
 * 서버가 같은 요청으로 알아본다. 그래서 같은 요청(범위+본문)은 성공할 때까지 같은 키를 쓴다.
 */
const keys = new Map<string, string>()
const keyFor = (scope: string) => {
  let k = keys.get(scope)
  if (!k) {
    k = crypto.randomUUID()
    keys.set(scope, k)
  }
  return k
}
const idemPost = async <T,>(path: string, body: unknown, method: 'POST' | 'PUT' = 'POST'): Promise<ApiResult<T>> => {
  const scope = `${method} ${path} ${JSON.stringify(body)}`
  const r = await request<T>(path, { method, body: JSON.stringify(body), headers: { 'Idempotency-Key': keyFor(scope) } })
  // 서버가 처리한 결과(성공 또는 확정된 오류)를 받으면 키를 버린다. 네트워크 오류·처리 중(409)이면 같은 키로 다시 보낸다.
  if (r.ok || !['NETWORK_ERROR', 'REQUEST_IN_PROGRESS'].includes(r.error.code)) keys.delete(scope)
  return r
}

/* ------------------------------------------------------------------ 서버 → 화면 변환 */
const GUIDE = (s: SSource) => ({ docCode: s.docCode ?? '', title: '', version: s.version ?? '', section: s.location ?? '', excerpt: s.excerpt ?? '' })

/** 평문 답변을 문단과 번호 목록 블록으로 나눈다 (서버는 HTML·블록이 아닌 글을 준다) */
export function toBlocks(content: string): ChatBlock[] {
  const out: ChatBlock[] = []
  let list: string[] = []
  const flush = () => {
    if (list.length) out.push({ type: 'ol', items: list })
    list = []
  }
  for (const paragraph of content.split(/\n{2,}/)) {
    for (const line of paragraph.split('\n')) {
      const m = /^\s*\d+[.)]\s+(.*\S)\s*$/.exec(line)
      if (m) list.push(m[1])
      else if (line.trim()) {
        flush()
        out.push({ type: 'p', text: line.trim() })
      }
    }
    flush()
  }
  return out.length ? out : [{ type: 'p', text: content }]
}

/** 단계: 서버가 준 nextActions 가 있으면 그것으로, 없으면(조회) 문의 상태로 정한다 */
export function stepOf(i: SInquiry, next?: string[], lastSender?: SMessage['sender']): ChatStep {
  if (i.ticket || i.status === 'RECEIVED' || i.status === 'HANDED_OFF') return 'submitted'
  if (i.status === 'AI_RESOLVED' || i.status === 'CLOSED_UNRESOLVED') return 'closed'
  if (next?.includes('START_NEW')) return 'closed'
  if (next?.includes('CONFIRM_RESOLUTION')) return 'answered'
  if (next?.includes('DECIDE_HANDOFF')) return 'offer'
  if (next?.includes('REPLY')) return 'collect'
  // 조회: 접수 초안이 있으면 연결 제안 단계로 둔다 (초안 화면은 아직 연결하지 않았다)
  if (i.activeDraftId) return 'offer'
  // 내 글에 AI 답이 없다: AI 가 답하지 못했다(503). 서버에는 "AI 응답 불가" 표시가 없어서 마지막 메시지로 알아낸다 (docs/api/02 IQ-01)
  if (lastSender === 'USER') return 'offer'
  if (i.displayStatus === 'unconfirmed') return 'answered'
  if (i.action === 'ESCALATE' || i.action === 'OUT_OF_SCOPE' || i.resolutionResult === 'UNRESOLVED') return 'offer'
  return 'collect'
}

const REPLIES: Partial<Record<ChatStep, ChatReply[]>> = {
  answered: [
    { label: '해결', action: 'resolved', primary: true },
    { label: '미해결', action: 'unresolved' },
  ],
  offer: [
    { label: '담당자 연결', action: 'connect-yes', primary: true },
    { label: '미연결 (종료)', action: 'connect-no' },
  ],
}

function toMessages(list: SMessage[], step: ChatStep): ChatMessage[] {
  const out: ChatMessage[] = list.map((m): ChatMessage => {
    if (m.sender === 'USER') return { id: m.id, role: 'user', text: m.content, createdAt: m.createdAt }
    if (m.sender === 'SYSTEM') return { id: m.id, role: 'sys', text: m.content, createdAt: m.createdAt, tone: /가려|가렸|마스킹/.test(m.content) ? 'sens' : undefined }
    const legacy = m.sources.find((s) => s.sourceKind === 'LEGACY')
    const legacyCase: LegacyCase | undefined = legacy ? { no: '', title: '과거 처리 사례 참고', symptom: '', solution: legacy.excerpt ?? '' } : undefined
    return { id: m.id, role: 'assistant', blocks: toBlocks(m.content), sources: m.sources.filter((s) => s.sourceKind === 'DOCUMENT').map(GUIDE), legacy: legacyCase, createdAt: m.createdAt }
  })
  // 버튼은 마지막 AI 메시지에만 붙는다. 내 글에 AI 답이 없으면(답하지 못함) 안내 메시지를 만들어 붙인다
  const replies = REPLIES[step]
  if (replies) {
    if (list[list.length - 1]?.sender === 'USER' && step === 'offer') {
      out.push({ id: -3, role: 'assistant', blocks: [{ type: 'p', text: '지금은 답변을 만들지 못했어요. 담당자에게 연결해 드릴까요?' }], replies })
    } else {
      for (let k = out.length - 1; k >= 0; k--) {
        if (out[k].role === 'assistant') {
          out[k] = { ...out[k], replies }
          break
        }
      }
    }
  }
  return out
}

/** 접수 상세(TK-06)를 문의 화면의 접수 카드로 */
export function toTicket(d: TicketDetail): Ticket {
  return {
    receiptNo: d.receiptNo,
    jiraKey: d.jiraKey,
    title: d.summary,
    categoryCode: d.category?.code ?? null,
    urgency: d.urgency ?? 'P3',
    groupId: d.group?.id ?? null,
    groupName: d.group?.name ?? '',
    assigneeId: d.assignee?.id ?? null,
    assigneeName: d.assignee?.name ?? null,
    workStatus: d.workStatus,
    assignStatus: d.assignStatus,
    jiraSyncStatus: d.jiraSyncStatus,
    createdAt: d.createdAt,
    finishedAt: d.finishedAt,
    closedAt: d.closedAt,
    resolutionNote: d.resolutionNote ?? '',
    needReply: false,
  }
}

/** 접수 상세를 읽지 못했을 때를 위한 요약 (문의 응답의 TicketRef 와 추천 그룹으로 채운다) */
const refTicket = (i: SInquiry): Ticket => ({
  receiptNo: i.ticket!.receiptNo,
  jiraKey: i.ticket!.jiraKey,
  title: i.title ?? '',
  categoryCode: i.categoryCode,
  urgency: i.urgency ?? 'P3',
  groupId: i.recommendedGroup?.id ?? null,
  groupName: i.recommendedGroup?.name ?? '',
  assigneeId: null,
  assigneeName: null,
  workStatus: i.ticket!.workStatus,
  assignStatus: 'PENDING',
  jiraSyncStatus: 'PENDING',
  createdAt: i.createdAt,
  resolutionNote: '',
  needReply: false,
})

export function toInquiry(i: SInquiry, messages: SMessage[], next?: string[], ticket?: Ticket | null): Inquiry {
  const step = stepOf(i, next, messages[messages.length - 1]?.sender)
  const firstUser = messages.find((m) => m.sender === 'USER')?.content
  return {
    id: i.id,
    title: i.title ?? (firstUser ? firstUser.slice(0, 30) : '새 문의'),
    status: i.status,
    step,
    categoryCode: i.categoryCode,
    unread: 0,
    createdAt: i.createdAt,
    updatedAt: i.updatedAt ?? i.createdAt,
    messages: toMessages(messages, step),
    draft: null,
    draftState: 'view',
    draftNote: '',
    ticket: i.ticket ? (ticket ?? refTicket(i)) : null,
  }
}

/* ------------------------------------------------------------------ 호출 */
/** 문의 한 건을 읽는다: 문의 + 모든 메시지 (+ 접수 상세) */
export async function loadInquiry(id: number, next?: string[]): Promise<ApiResult<Inquiry>> {
  const [inq, msgs] = await Promise.all([request<SInquiry>(`/inquiries/${id}`), request<{ items: SMessage[] }>(`/inquiries/${id}/messages`)])
  if (!inq.ok) return inq
  if (!msgs.ok) return msgs
  let ticket: Ticket | null = null
  if (inq.data.ticket) {
    const t = await request<TicketDetail>(`/tickets/${inq.data.ticket.id}`)
    if (t.ok) ticket = toTicket(t.data)
  }
  return ok(toInquiry(inq.data, msgs.data.items, next, ticket))
}

/**
 * AI 가 답하지 못해도(503 AI_UNAVAILABLE) 문의·메시지는 저장돼 있다. 그때는 저장된 문의를 열고 담당자 연결을 안내한다 (IQ-01·08).
 */
async function afterTurn(r: ApiResult<AiTurn>, savedId?: number): Promise<ApiResult<Inquiry>> {
  if (r.ok) return loadInquiry(r.data.inquiry.id, r.data.nextActions)
  if (r.error.code === 'AI_UNAVAILABLE') {
    const id = savedId ?? Number(r.error.details?.find((d) => d.reason === 'INQUIRY_ID')?.value)
    if (id) return loadInquiry(id, ['DECIDE_HANDOFF'])
  }
  return r
}

export const serverStart = async (text: string) => afterTurn(await idemPost<AiTurn>('/inquiries', { content: text }))
export const serverSend = async (id: number, text: string) => afterTurn(await idemPost<AiTurn>(`/inquiries/${id}/messages`, { content: text }), id)
/** AI 답변의 해결 확인 (IQ-09) */
export const serverResolve = async (id: number, result: 'RESOLVED' | 'UNRESOLVED') => afterTurn(await idemPost<AiTurn>(`/inquiries/${id}/resolution`, { resolutionResult: result }, 'PUT'), id)
/** 담당자 연결을 거절하고 문의를 끝낸다 (IQ-04) */
export async function serverClose(id: number): Promise<ApiResult<Inquiry>> {
  const r = await request<SInquiry>(`/inquiries/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'CLOSED_UNRESOLVED' }) })
  return r.ok ? loadInquiry(id) : r
}
/** 기존 문의·세션 이어가기 (IQ-06) */
export async function serverResume(id: number): Promise<ApiResult<Inquiry>> {
  const r = await request<{ inquiry: SInquiry; nextActions: string[] }>(`/inquiries/${id}/sessions`, { method: 'POST' })
  return r.ok ? loadInquiry(id, r.data.nextActions) : r
}

/** 서버 문의 요약을 화면의 요약으로 */
const SUMMARY_STATE: Record<DisplayStatus, { label: string; kind: InquiryStateKind }> = {
  in_progress: { label: '진행 중', kind: 'progress' },
  ai_resolved: { label: 'AI 해결', kind: 'ai' },
  unconfirmed: { label: '미확인', kind: 'warn' },
  unresolved: { label: '미해결 종료', kind: 'received' },
  received: { label: '접수', kind: 'received' },
  assigned: { label: '담당자 배정', kind: 'assigned' },
  progress: { label: '처리 중', kind: 'progress' },
  awaiting_confirm: { label: '해결 확인 대기', kind: 'awaiting_confirm' },
  resolved: { label: '해결 완료', kind: 'resolved' },
}
export function toServerSummary(s: SSummary): InquirySummary {
  const st = SUMMARY_STATE[s.displayStatus] ?? SUMMARY_STATE.in_progress
  return {
    id: s.id,
    title: s.title ?? '새 문의',
    displayStatus: s.displayStatus,
    categoryCode: s.category?.code ?? null,
    receiptNo: s.receiptNo,
    jiraKey: null,
    createdAt: s.createdAt,
    stateLabel: st.label,
    stateKind: st.kind,
    unread: 0,
    updatedAt: s.updatedAt ?? s.createdAt,
  }
}
export const mapSummaries = (p: Page<SSummary>): Page<InquirySummary> => ({ ...p, items: p.items.map(toServerSummary) })
export type { SSummary }

/**
 * 접수 초안·최종 접수·접수 이후의 해결 확인은 Jira 연동(실행기)이 준비되기 전에는 서버로 보내지 않는다.
 * 접수를 만들면 공유 DB 에 접수와 Jira 작업이 남고 Jira 단계가 끝나지 않기 때문이다. 이 안내만 돌려주고 서버는 부르지 않는다.
 */
export const notReady = (what: string) => fail('NOT_READY', `${what}은(는) Jira 연동이 준비된 뒤에 열려요. 지금은 사용할 수 없어요.`)
