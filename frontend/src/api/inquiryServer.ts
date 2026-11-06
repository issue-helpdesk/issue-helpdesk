/**
 * 문의 대화 서버 연동 (docs/api/02 IQ-01~09). 서버 응답을 화면의 Inquiry 로 바꾸고, 서버 경로를 부른다.
 *
 * 서버는 문의(Inquiry)·메시지(Message)·다음 행동(nextActions)을 따로 주고, 화면은 단계(step)·카드·버튼이 붙은 문의 하나를 쓴다.
 * 그래서 이 파일이 둘 사이를 바꿔 준다.
 *   nextActions  REPLY → 정보 수집(collect) · CONFIRM_RESOLUTION → 해결 확인(answered, 해결·미해결 버튼)
 *                DECIDE_HANDOFF → 담당자 연결 제안(offer, 연결·종료 버튼) · START_NEW → 종료(closed)
 * 서버에 없는 것(새 답변 표시, 담당자 안내 메시지, 응답 없음 삭제·돌아옴 안내)은 값이 비어 있어 화면에서 나타나지 않는다.
 * 접수 초안·최종 접수(TK-01~04)와 접수 이후의 해결·미해결(TK-07)은 SERVER_INTAKE 가 켜졌을 때만 서버로 보낸다(config.ts).
 */
import { request } from '../core/apiClient'
import { SERVER_INTAKE } from '../core/config'
import { uuid } from '../core/uuid'
import type { ChatBlock, ChatMessage, ChatQuestion, ChatReply, ChatStep, CategoryCode, Draft, DraftEdit, DraftState, Inquiry, InquiryStatus, LegacyCase, RejudgedField, Ticket, Urgency, WorkStatus } from './chatTypes'
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
  images?: { key: string; caption: string }[]
}
interface SQuestion {
  label?: string | null
  text: string
  options?: string[]
  allowText?: boolean
}
interface SMessage {
  id: number
  sessionId: number
  seq: number
  sender: 'USER' | 'AI' | 'SYSTEM'
  /** R-29: TEXT 글, CHOICE 누른 버튼(code), NOTICE 민감정보 안내, DRAFT_CARD·TICKET_CARD 카드 자리. 이전 서버는 이 값이 없다 */
  kind?: 'TEXT' | 'CHOICE' | 'NOTICE' | 'DRAFT_CARD' | 'TICKET_CARD'
  code?: ChoiceCode | null
  /** TEXT·NOTICE 만 글이 있다. 그 밖에는 null */
  content: string | null
  /** DRAFT_CARD 의 초안 (IQ-07 에서만) */
  draft?: SDraft | null
  /** 이 AI 메시지가 물은 추가 질문 (ASK_MORE 메시지에만 값이 있다). 옛 응답에는 없다 */
  questions?: SQuestion[]
  sources: SSource[]
  createdAt: string
}
type ChoiceCode = 'RESOLVED' | 'UNRESOLVED' | 'CONNECT' | 'NO_CONNECT' | 'CONFIRM' | 'CANCEL' | 'TICKET_RESOLVED' | 'TICKET_UNRESOLVED'
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
/** 접수 초안 (TK-01·02·03) */
interface SDraft {
  id: number
  inquiryId: number
  summary: string | null
  targetSystem: string | null
  occurredAt: string | null
  categoryCode: CategoryCode | null
  inquiryType: { id: number; code: string; name: string } | null
  urgency: Urgency | null
  urgencyReason: string | null
  businessImpact: string | null
  triedActions: string | null
  recommendedGroupId: number | null
  recommendedGroup: { id: number; name: string } | null
  status: string
  updatedAt: string | null
}
interface SDraftChange {
  field: string
  before: string | number | null
  after: string | number | null
  reason: string | null
}
interface SDraftResult {
  draft: SDraft
  changes: SDraftChange[]
  maskNotice: string | null
}
interface AiTurn {
  inquiry: SInquiry
  messages: SMessage[]
  nextActions: string[]
}
interface SSummary {
  id: number
  /** 문의자 (서버 InquirySummary.user). 관리자 AI 처리 상세에서 문의자를 보여 줄 때 쓴다 */
  user?: { id: number; employeeNo: string; name: string }
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
    k = uuid() // crypto.randomUUID 는 http 서버에 없다
    keys.set(scope, k)
  }
  return k
}
const idemPost = async <T,>(path: string, body: unknown, method: 'POST' | 'PUT' = 'POST'): Promise<ApiResult<T>> => {
  const scope = `${method} ${path} ${JSON.stringify(body)}`
  let r: ApiResult<T>
  try {
    r = await request<T>(path, { method, body: JSON.stringify(body), headers: { 'Idempotency-Key': keyFor(scope) } })
  } catch {
    // 요청을 만들다가 난 예상 밖 오류도 화면이 오류 문구로 보이게 결과로 돌려준다 (던지면 대기 화면이 끝나지 않는다)
    return fail('CLIENT_ERROR', '요청을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요.')
  }
  // 서버가 처리한 결과(성공 또는 확정된 오류)를 받으면 키를 버린다. 네트워크 오류·처리 중(409)이면 같은 키로 다시 보낸다.
  if (r.ok || !['NETWORK_ERROR', 'REQUEST_IN_PROGRESS'].includes(r.error.code)) keys.delete(scope)
  return r
}

/* ------------------------------------------------------------------ 서버 → 화면 변환 */
const GUIDE = (s: SSource) => ({ docCode: s.docCode ?? '', title: '', version: s.version ?? '', section: s.location ?? '', excerpt: s.excerpt ?? '', images: s.images?.length ? s.images : undefined })

/**
 * 줄바꿈 없이 한 줄로 온 답변 중 "1) … 2) …" 단계가 들어 있는 것은 문장 단위로 줄을 나눈다.
 * (서버 문장은 그대로 두고 화면에서만 읽기 쉽게 한다. 줄바꿈이 이미 있거나 번호 단계가 없는 답변은 건드리지 않는다)
 */
export function breakInlineSteps(content: string): string {
  if (content.includes('\n') || !/(^|\s)1\)\s[\s\S]*\s2\)\s/.test(content)) return content
  return content.replace(/([.!?])\s+(?=\S)/g, '$1\n').trim()
}

/** 평문 답변을 문단과 번호 목록 블록으로 나눈다 (서버는 HTML·블록이 아닌 글을 준다) */
export function toBlocks(content: string): ChatBlock[] {
  content = breakInlineSteps(content)
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
export function stepOf(i: SInquiry, next?: string[], lastSender?: SMessage['sender'], intake = false): ChatStep {
  if (i.ticket || i.status === 'RECEIVED' || i.status === 'HANDED_OFF') return 'submitted'
  if (i.status === 'AI_RESOLVED' || i.status === 'CLOSED_UNRESOLVED') return 'closed'
  if (next?.includes('START_NEW')) return 'closed'
  if (next?.includes('CONFIRM_RESOLUTION')) return 'answered'
  if (next?.includes('DECIDE_HANDOFF')) return 'offer'
  if (next?.includes('REPLY')) return 'collect'
  // 조회: 접수 초안이 있으면, 접수를 서버로 보내는 환경에서는 초안 단계로, 아니면 연결 제안 단계로 둔다
  if (i.activeDraftId) return intake ? 'draft' : 'offer'
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

/** 내 글을 보낸 지 이만큼은 AI 가 아직 답을 만드는 중으로 본다(ms). 서버는 AI 답변을 만들 때까지 오래 걸릴 수 있고(몇 초~1분 이상), 그동안 내 글만 저장돼 있다 */
export const AI_WAIT_MS = 120_000

/** 마지막이 내 글이고 보낸 지 얼마 안 됐으면, AI 가 못 답한 것이 아니라 아직 답하는 중이다 */
export function isAnswering(i: SInquiry, list: SMessage[]): boolean {
  const last = list[list.length - 1]
  return !i.ticket && i.status === 'IN_PROGRESS' && last?.sender === 'USER' && Date.now() - Date.parse(last.createdAt) < AI_WAIT_MS
}

/**
 * 서버가 저장하지 않는 "내가 누른 버튼"과 그 뒤 안내. 모의(시안)는 말풍선과 안내를 대화에 남기지만,
 * 서버는 해결이면 시스템 안내 한 줄만, 미해결·연결 거절이면 상태만 남긴다. 그래서 문의의 상태에서 같은 대화를 다시 만들어 보여 준다.
 */
export const RESOLVED_LABEL = '해결'
export const UNRESOLVED_LABEL = '미해결'
export const RESOLVED_REPLY: ChatMessage = { id: -6, role: 'assistant', blocks: [{ type: 'p', text: '**AI 안내로 문제가 해결되었군요!**' }, { type: 'p', text: '이 문의는 **AI 해결**로 기록했어요. 다른 도움이 필요하면 새 문의를 시작해 주세요.' }] }
export const UNRESOLVED_REPLY: ChatMessage = { id: -7, role: 'assistant', blocks: [{ type: 'p', text: '**아직 문제가 해결되지 않았군요.**' }, { type: 'p', text: '담당자 연결을 통해 추가 도움을 받을 수 있어요.' }] }
/** 서버가 해결 때 저장하는 시스템 안내 (위 "해결" 안내와 겹쳐서 화면에서는 뺀다) */
const RESOLVED_NOTICE = '해결로 종료되었습니다.'

/** 담당자 연결 제안에서 "미연결 (종료)"를 눌렀을 때 내 말풍선 글 (모의와 같다) */
export const NO_CONNECT_LABEL = '미연결 (종료)'

/** AI 가 답을 만들지 못했을 때 화면이 붙이는 안내 (서버는 저장하지 않는다) */
const NO_ANSWER_TEXT = '지금은 AI 답변을 만들지 못했어요. 입력한 내용은 저장됐어요. 담당자에게 연결해 드릴까요?'

/** 접수 없이 끝났을 때 보여 주는 종료 안내 (모의의 noTicketClosed 와 같은 글) */
export const NO_TICKET_CLOSED: ChatMessage[] = [
  { id: -4, role: 'assistant', blocks: [{ type: 'p', text: '**담당자 연결 없이 상담을 종료했어요.**' }, { type: 'p', text: '티켓은 접수되지 않았으며, 같은 문제로 다시 연결을 원하시면 새 문의로 시작해 주세요.' }] },
]

/* ------------------------------------------------------------------ 접수 초안 */
const DRAFT_INTRO = '지금까지 확인한 내용을 정리했어요. 맞는지 확인하고, 필요하면 수정해 주세요.'
/** 서버가 만든 메시지가 아니라 화면이 붙이는 카드 메시지의 id (서버 메시지 id 는 양수) */
export const DRAFT_CARD_ID = -10
export const TICKET_CARD_ID = -11

export function toDraft(d: SDraft): Draft {
  return {
    title: d.inquiryType?.name ?? `${d.targetSystem ?? 'IT'} 지원 문의`,
    categoryCode: d.categoryCode,
    targetSystem: d.targetSystem ?? '확인 필요',
    summary: d.summary ?? '',
    occurredAt: d.occurredAt ?? '확인 필요',
    businessImpact: d.businessImpact ?? '확인 필요',
    triedActions: d.triedActions ?? '확인 필요',
    aiSummary: '', // 서버에는 AI 안내 요약 칸이 없다
    urgency: d.urgency ?? 'P3',
    urgencyReasons: (d.urgencyReason ?? '').split('\n').map((x) => x.trim()).filter(Boolean),
    groupId: d.recommendedGroupId,
    groupName: d.recommendedGroup?.name ?? '',
    inquiryTypeCode: d.inquiryType?.code ?? null,
    inquiryTypeName: d.inquiryType?.name ?? null,
  }
}

/** 최종 접수(TK-04)에 보낼 값: 사용자가 본 초안의 id 와 수정 시각 */
const draftRefs = new Map<number, { id: number; updatedAt: string | null }>()
/** 초안을 고친 직후의 "다시 판단됨" 안내. 같은 수정 시각의 초안에만 붙인다(주기 조회가 지우지 않게 서버 응답이 아닌 여기에 둔다) */
const draftNotes = new Map<number, { updatedAt: string | null; note: string; rejudged: RejudgedField[] }>()

const REJUDGED: Record<string, RejudgedField> = { categoryCode: 'category', inquiryTypeId: 'inquiryType', urgency: 'urgency', recommendedGroupId: 'group' }

/** 서버 추가 질문을 화면 질문으로: 빠진 값은 옛 질문으로 보고 채운다 (선택지가 없으면 입력칸으로 답한다) */
export function toQuestions(list?: SQuestion[]): ChatQuestion[] | undefined {
  const qs = (list ?? []).filter((q) => q && typeof q.text === 'string')
  return qs.length ? qs.map((q) => ({ label: q.label ?? null, text: q.text, options: q.options ?? [], allowText: q.allowText ?? false })) : undefined
}

/** 글(말풍선)인 메시지. kind 가 없는 이전 서버의 메시지도 글로 본다 */
export const isText = (m: SMessage) => !m.kind || m.kind === 'TEXT'
/** 서버가 선택·카드를 메시지로 저장하는지 (R-29). 이전 서버는 kind 를 주지 않아서 아래 옛 방식(상태로 다시 만들기)을 쓴다 */
const hasKinds = (list: SMessage[]) => list.some((m) => !!m.kind)

/** 서버가 저장한 문의자 선택(CHOICE)의 말풍선 글 (모의와 같다) */
const CHOICE_LABEL: Record<ChoiceCode, string> = {
  RESOLVED: RESOLVED_LABEL,
  UNRESOLVED: UNRESOLVED_LABEL,
  CONNECT: '담당자 연결',
  NO_CONNECT: NO_CONNECT_LABEL,
  CONFIRM: '접수하기',
  CANCEL: '접수 안 함',
  TICKET_RESOLVED: RESOLVED_LABEL,
  TICKET_UNRESOLVED: UNRESOLVED_LABEL,
}
const DRAFT_STATE: Record<string, DraftState> = { EDITING: 'view', CONFIRMED: 'confirmed', CANCELLED: 'cancel' }
const REASK_TEXT = '다시 확인을 요청했어요. 담당자가 재확인하고 있어요. 아래 카드에서 새 진행 상황을 볼 수 있어요.'
/** 서버 메시지 하나에서 만든 화면 메시지끼리 겹치지 않는 id (고정 안내의 -3~-11 과도 겹치지 않는다) */
const extraId = (m: SMessage, n: number) => -(1000 + m.id * 10 + n)

/**
 * 서버가 선택·카드를 메시지로 저장할 때의 변환 (R-29). 저장된 순서 그대로 말풍선과 카드를 만들고, 문구는 code 로 화면이 정한다.
 * - CHOICE: 내 말풍선 + (해결·미해결·미연결·접수 안 함이면) 그 뒤 안내
 * - DRAFT_CARD: 초안 안내 + 초안 카드 (draft.status 가 EDITING 일 때만 수정·접수·취소가 되고 그 밖에는 읽기 전용)
 * - TICKET_CARD: 접수·재확인 안내. 진행 카드는 마지막 하나만 보이고(지난 시점의 상태는 저장하지 않는다) 앞의 것은 안내 글만 남는다
 */
function toMessagesFromKinds(list: SMessage[], i: SInquiry): ChatMessage[] {
  const out: ChatMessage[] = []
  const lastTicketCard = [...list].reverse().find((m) => m.kind === 'TICKET_CARD')?.id
  const resolved = i.status === 'AI_RESOLVED'
  let lastTextSender: SMessage['sender'] | null = null
  let prevCode: ChoiceCode | null = null
  list.forEach((m) => {
    const kind = m.kind ?? 'TEXT'
    const content = m.content ?? ''
    if (kind === 'TEXT') {
      lastTextSender = m.sender
      if (m.sender === 'USER') out.push({ id: m.id, role: 'user', text: content, createdAt: m.createdAt })
      else if (m.sender === 'SYSTEM') out.push({ id: m.id, role: 'sys', text: content, createdAt: m.createdAt })
      else {
        const legacy = m.sources?.find((s) => s.sourceKind === 'LEGACY')
        const legacyCase: LegacyCase | undefined = legacy ? { no: '', title: '과거 처리 사례 참고', symptom: '', solution: legacy.excerpt ?? '' } : undefined
        out.push({ id: m.id, role: 'assistant', blocks: toBlocks(content), sources: (m.sources ?? []).filter((s) => s.sourceKind === 'DOCUMENT').map(GUIDE), legacy: legacyCase, questions: toQuestions(m.questions), createdAt: m.createdAt })
      }
      return
    }
    if (kind === 'NOTICE') {
      // 이전에 저장한 "해결로 종료되었습니다" 안내는 해결 안내와 겹쳐서 뺀다
      if (resolved && content === RESOLVED_NOTICE) return
      out.push({ id: m.id, role: 'sys', text: content, createdAt: m.createdAt, tone: /민감정보|개인정보가 감지|가림|가려|가렸|마스킹/.test(content) ? 'sens' : undefined })
      return
    }
    if (kind === 'CHOICE' && m.code) {
      // 내 글에 AI 답이 없는 채로 담당자 연결·미연결을 골랐다: "답변을 만들지 못했어요" 안내는 저장되지 않아서 같은 안내를 앞에 남긴다
      if ((m.code === 'CONNECT' || m.code === 'NO_CONNECT') && lastTextSender === 'USER') out.push({ id: extraId(m, 0), role: 'assistant', blocks: [{ type: 'p', text: NO_ANSWER_TEXT }] })
      out.push({ id: m.id, role: 'user', text: CHOICE_LABEL[m.code] ?? m.code, createdAt: m.createdAt })
      if (m.code === 'RESOLVED') out.push({ ...RESOLVED_REPLY, id: extraId(m, 1) })
      else if (m.code === 'UNRESOLVED') out.push({ ...UNRESOLVED_REPLY, id: extraId(m, 1) })
      else if (m.code === 'NO_CONNECT' || m.code === 'CANCEL') NO_TICKET_CLOSED.forEach((x, n) => out.push({ ...x, id: extraId(m, 2 + n) }))
      prevCode = m.code
      return
    }
    if (kind === 'DRAFT_CARD') {
      out.push({ id: m.id, role: 'assistant', blocks: [{ type: 'p', text: DRAFT_INTRO }], card: 'draft', draft: m.draft ? toDraft(m.draft) : undefined, draftState: DRAFT_STATE[m.draft?.status ?? 'EDITING'] ?? 'view', createdAt: m.createdAt })
      return
    }
    if (kind === 'TICKET_CARD') {
      const first = prevCode === 'CONFIRM'
      const text = first && i.ticket ? `접수되었어요. 접수번호는 **${i.ticket.receiptNo}** 입니다. 담당자 연결을 진행하고 있어요. 진행 상황은 아래 카드에서 바로 볼 수 있어요.` : REASK_TEXT
      out.push({ id: m.id, role: 'assistant', blocks: [{ type: 'p', text }], card: m.id === lastTicketCard && i.ticket ? 'ticket' : undefined, createdAt: m.createdAt })
    }
  })
  return out
}

function toMessages(list: SMessage[], step: ChatStep, i: SInquiry, answering = false, intake = false): ChatMessage[] {
  const kinds = hasKinds(list)
  // 선택·카드 메시지(USER 로 저장되는 CHOICE 등)는 "마지막 말이 누구의 것인지" 판단에서 뺀다
  const texts = list.filter(isText)
  const lastTextSender = texts[texts.length - 1]?.sender
  const resolved = i.status === 'AI_RESOLVED'
  const out: ChatMessage[] = kinds ? toMessagesFromKinds(list, i) : list.filter((m) => !(resolved && m.sender === 'SYSTEM' && m.content === RESOLVED_NOTICE)).map((m): ChatMessage => {
    const content = m.content ?? ''
    if (m.sender === 'USER') return { id: m.id, role: 'user', text: content, createdAt: m.createdAt }
    if (m.sender === 'SYSTEM') return { id: m.id, role: 'sys', text: content, createdAt: m.createdAt, tone: /민감정보|개인정보가 감지|가림|가려|가렸|마스킹/.test(content) ? 'sens' : undefined }
    const legacy = m.sources.find((s) => s.sourceKind === 'LEGACY')
    const legacyCase: LegacyCase | undefined = legacy ? { no: '', title: '과거 처리 사례 참고', symptom: '', solution: legacy.excerpt ?? '' } : undefined
    return { id: m.id, role: 'assistant', blocks: toBlocks(content), sources: m.sources.filter((s) => s.sourceKind === 'DOCUMENT').map(GUIDE), legacy: legacyCase, questions: toQuestions(m.questions), createdAt: m.createdAt }
  })
  // 지금 답할 수 있는 질문: 서버가 준 마지막 메시지가 질문이 있는 AI 메시지이고, 문의가 진행 중(IN_PROGRESS)·추가 질문(ASK_MORE)일 때만이다.
  // 지난 질문(그 뒤에 내 답이 이어진 것)과 다른 상태의 문의는 읽기 전용으로 남는다 (docs/api/02 Question)
  const lastRaw = list[list.length - 1]
  if (lastRaw?.sender === 'AI' && lastRaw.questions?.length && i.status === 'IN_PROGRESS' && i.action === 'ASK_MORE' && !answering) {
    const at = out.findIndex((x) => x.id === lastRaw.id)
    if (at >= 0) out[at] = { ...out[at], questionsOpen: true }
  }
  // 아직 답하는 중이면 준비 중 표시를 붙인다 ("답하지 못함"으로 단정하지 않는다)
  if (answering) out.push({ id: -3, role: 'assistant', typing: { label: '답변을 준비하고 있어요' } })
  // 서버가 선택·카드를 저장하지 않던 때(kind 가 없는 응답)의 옛 방식: 문의 상태에서 말풍선과 카드를 다시 만들어 붙인다.
  // 서버가 R-29 를 반영한 뒤에는 쓰이지 않는다 (모든 서버가 반영되면 이 블록을 걷어낸다)
  if (!kinds) {
    // 내 글에 AI 답이 없는 채로 담당자 연결을 거절했거나 접수 초안으로 넘어간 문의: "답변을 만들지 못했어요" 안내도 서버가 저장하지 않아서
    // (연결 제안 단계에서만 화면이 만들어 붙인다) 버튼을 누르는 순간 사라진다. 누른 버튼·종료 안내 앞에 같은 안내를 버튼 없이 남겨 대화 흐름을 지킨다
    if (!answering && !resolved && lastTextSender === 'USER' && ((i.status === 'CLOSED_UNRESOLVED' && !i.ticket) || step === 'draft')) {
      out.push({ id: -3, role: 'assistant', blocks: [{ type: 'p', text: NO_ANSWER_TEXT }] })
    }
    // 내가 누른 "해결"·"미해결"과 그 뒤 안내 (서버는 저장하지 않는다)
    if (resolved) out.push({ id: -8, role: 'user', text: RESOLVED_LABEL }, RESOLVED_REPLY)
    else if (i.resolutionResult === 'UNRESOLVED') out.push({ id: -9, role: 'user', text: UNRESOLVED_LABEL }, UNRESOLVED_REPLY)
    // 접수 없이 끝난 문의(담당자 연결 거절): 서버는 종료만 저장하고 안내 글은 저장하지 않아서, 모의와 같은 종료 안내를 화면에서 붙인다
    if (i.status === 'CLOSED_UNRESOLVED' && !i.ticket) out.push({ id: -5, role: 'user', text: NO_CONNECT_LABEL }, ...NO_TICKET_CLOSED)
    // 접수 초안·접수 카드: 서버는 카드를 메시지로 저장하지 않아서 상태에서 만들어 붙인다
    if (intake && step === 'draft') out.push({ id: DRAFT_CARD_ID, role: 'assistant', blocks: [{ type: 'p', text: DRAFT_INTRO }], card: 'draft' })
    if (intake && i.ticket) {
      out.push({ id: TICKET_CARD_ID, role: 'assistant', blocks: [{ type: 'p', text: `접수되었어요. 접수번호는 **${i.ticket.receiptNo}** 입니다. 담당자 연결을 진행하고 있어요. 진행 상황은 아래 카드에서 바로 볼 수 있어요.` }], card: 'ticket' })
    }
  }
  // 버튼은 마지막 AI 메시지에만 붙는다. 내 글에 AI 답이 없으면(답하지 못함) 안내 메시지를 만들어 붙인다
  const replies = REPLIES[step]
  if (replies) {
    if (lastTextSender === 'USER' && step === 'offer') {
      out.push({ id: -3, role: 'assistant', blocks: [{ type: 'p', text: NO_ANSWER_TEXT }], replies })
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
    id: d.id,
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
    transitionPending: d.transitionStatus !== 'IDLE',
  }
}

/** 접수 상세를 읽지 못했을 때를 위한 요약 (문의 응답의 TicketRef 와 추천 그룹으로 채운다) */
const refTicket = (i: SInquiry): Ticket => ({
  id: i.ticket!.id,
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

/**
 * 서버가 제목을 아직 정하지 못한 문의(AI 가 답을 못 만든 경우 등)의 제목. 대화 화면은 첫 메시지 앞부분으로 제목을 만들어 보여 주는데,
 * 목록(사이드바·문의 내역)은 요약만 받아 첫 메시지를 몰라 "새 문의"로 보였다. 대화 화면이 만든 제목을 기억해 목록도 같은 제목을 쓴다.
 * 서버는 이제 문의를 시작할 때 기본 제목을 저장한다 (R-37). 그래서 새 문의에는 이 기억이 쓰이지 않고, 그 전에 만들어져 제목이 비어 있는 옛 문의에만 남는다.
 * (옛 문의는 서버가 제목을 채워 주지 않으므로 지우지 않는다. 새로고침하면 사라지는 한계도 그대로다.)
 */
const madeTitles = new Map<number, string>()

export function toInquiry(i: SInquiry, messages: SMessage[], next?: string[], ticket?: Ticket | null, draft?: Draft | null, draftNote = '', intake = false): Inquiry {
  // 말(TEXT)만 본다: 서버가 선택·카드를 메시지로 저장하면 마지막 메시지가 내 "선택"일 수 있다 (R-29)
  const texts = messages.filter(isText)
  const answering = isAnswering(i, texts)
  const step: ChatStep = answering ? 'answering' : stepOf(i, next, texts[texts.length - 1]?.sender, intake)
  const firstUser = texts.find((m) => m.sender === 'USER')?.content ?? undefined
  const title = i.title ?? (firstUser ? firstUser.slice(0, 30).trim() : '새 문의')
  if (!i.title && firstUser) madeTitles.set(i.id, title)
  return {
    id: i.id,
    title,
    status: i.status,
    step,
    categoryCode: i.categoryCode,
    unread: 0,
    createdAt: i.createdAt,
    updatedAt: i.updatedAt ?? i.createdAt,
    messages: toMessages(messages, step, i, answering, intake),
    draft: step === 'draft' ? (draft ?? null) : null,
    draftState: 'view',
    draftNote,
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
  // 접수를 서버로 보내는 환경에서만 작성 중인 초안을 읽는다 (TK-02)
  let draft: Draft | null = null
  let note = ''
  if (SERVER_INTAKE && !inq.data.ticket && inq.data.activeDraftId) {
    const d = await request<SDraft>(`/ticket-drafts/${inq.data.activeDraftId}`)
    if (!d.ok) return d
    draft = toDraft(d.data)
    draftRefs.set(id, { id: d.data.id, updatedAt: d.data.updatedAt })
    const kept = draftNotes.get(id)
    if (kept && kept.updatedAt === d.data.updatedAt) {
      note = kept.note
      draft.rejudged = kept.rejudged
    }
  }
  return ok(toInquiry(inq.data, msgs.data.items, next, ticket, draft, note, SERVER_INTAKE))
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
  if (r.ok) return loadInquiry(id, r.data.nextActions)
  // 서버는 미확인·미해결(연결 제안 중)·해결 확인 대기만 이어간다. 담당자 연결을 거절해 끝낸 문의는 이어갈 수 없다 (IQ-06 409)
  if (r.error.code === 'INQUIRY_INVALID_STATE') return fail('INQUIRY_INVALID_STATE', '이미 종료된 문의는 이어갈 수 없어요. 새 문의로 시작해 주세요.')
  return r
}

/** 서버 문의 요약을 화면의 요약으로 */
const SUMMARY_STATE: Record<DisplayStatus, { label: string; kind: InquiryStateKind }> = {
  in_progress: { label: '진행 중', kind: 'progress' },
  ai_resolved: { label: 'AI 해결', kind: 'ai' },
  unconfirmed: { label: '미확인', kind: 'warn' },
  unresolved: { label: '미연결 종료', kind: 'received' },
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
    title: s.title ?? madeTitles.get(s.id) ?? '새 문의',
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

/* ------------------------------------------------------------------ 접수 (TK-01·03·04)·접수 이후 해결 확인 (TK-07) */
/** 담당자 연결 동의: 접수 초안을 만든다 (TK-01). 이미 작성 중인 초안이 있으면(409) 그 초안을 연다 */
export async function serverDraftCreate(id: number): Promise<ApiResult<Inquiry>> {
  const r = await request<SDraft>(`/inquiries/${id}/ticket-drafts`, { method: 'POST' })
  if (r.ok || r.error.code === 'DRAFT_ALREADY_EXISTS') return loadInquiry(id)
  return r
}

/** 초안 수정 (TK-03). 서버가 긴급도·담당 그룹을 다시 판단한 결과(changes)와 가린 민감정보 안내(maskNotice)를 화면 안내로 바꾼다 */
export async function serverDraftSave(id: number, edit: DraftEdit): Promise<ApiResult<Inquiry>> {
  const ref = draftRefs.get(id)
  if (!ref) return fail('DRAFT_NOT_FOUND', '작성 중인 초안을 찾지 못했어요. 화면을 새로 열어 주세요.')
  // 서버는 빈 문자열을 받지 않는다(1자 이상). 비워 둔 칸은 보내지 않아 기존 값을 유지한다
  const body: Record<string, string> = {}
  for (const [k, v] of Object.entries({ summary: edit.summary, occurredAt: edit.occurredAt, businessImpact: edit.businessImpact, triedActions: edit.triedActions })) {
    if (v?.trim()) body[k] = v.trim()
  }
  const r = await request<SDraftResult>(`/ticket-drafts/${ref.id}`, { method: 'PATCH', body: JSON.stringify(body) })
  if (!r.ok) return r
  const reasons = r.data.changes.map((c) => c.reason).filter(Boolean).join(' ')
  const base = r.data.changes.length
    ? `수정한 내용을 반영해 다시 판단했어요. ${reasons} 변경된 내용으로 다시 확인해 주세요.`.replace('  ', ' ')
    : '수정 내용을 반영했어요. 최종 접수 전에 한 번 더 확인해 주세요.'
  const mask = r.data.maskNotice?.replace(/\s*\n\s*/g, ' ').trim()
  draftNotes.set(id, {
    updatedAt: r.data.draft.updatedAt,
    note: mask ? `${mask} ${base}` : base,
    rejudged: [...new Set(r.data.changes.map((c) => REJUDGED[c.field]).filter(Boolean))],
  })
  return loadInquiry(id)
}

/** 접수하지 않고 종료 (TK-03 status=CANCELLED): 초안이 취소되고 문의가 미연결 종료가 된다 */
export async function serverDraftCancel(id: number): Promise<ApiResult<Inquiry>> {
  const ref = draftRefs.get(id)
  if (!ref) return fail('DRAFT_NOT_FOUND', '작성 중인 초안을 찾지 못했어요. 화면을 새로 열어 주세요.')
  const r = await request<SDraftResult>(`/ticket-drafts/${ref.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'CANCELLED' }) })
  if (!r.ok) return r
  draftRefs.delete(id)
  draftNotes.delete(id)
  return loadInquiry(id)
}

/** 최종 접수 (TK-04). 사용자가 본 초안의 수정 시각을 보내, 다른 화면에서 바뀐 초안이면 서버가 거절한다(DRAFT_RECONFIRM_REQUIRED) */
export async function serverConfirm(id: number): Promise<ApiResult<Inquiry>> {
  const ref = draftRefs.get(id)
  if (!ref) return fail('DRAFT_NOT_FOUND', '작성 중인 초안을 찾지 못했어요. 화면을 새로 열어 주세요.')
  const r = await request<{ id: number }>('/tickets', { method: 'POST', body: JSON.stringify({ draftId: ref.id, draftUpdatedAt: ref.updatedAt }) })
  if (!r.ok) return r
  draftRefs.delete(id)
  draftNotes.delete(id)
  return loadInquiry(id)
}

/** 초안이 서버에서 바뀌었거나 이미 접수·취소돼서 화면의 초안이 낡았음을 뜻하는 오류 */
export const isStaleDraft = (code: string) => ['DRAFT_RECONFIRM_REQUIRED', 'DRAFT_NOT_EDITABLE', 'DRAFT_NOT_FOUND'].includes(code)

/** 접수 이후 문의자의 해결(CLS)·미해결(WIP+남은 증상) 선택 (TK-07). ITSM 상태 변경은 실행기가 이어서 처리하므로 화면 반영은 조금 늦을 수 있다 */
export async function serverTicketStatus(id: number, ticketId: number | undefined, body: { workStatus: 'CLS' } | { workStatus: 'WIP'; reason: string }): Promise<ApiResult<Inquiry>> {
  if (!ticketId) return fail('TICKET_NOT_FOUND', '접수 정보를 찾지 못했어요. 화면을 새로 열어 주세요.')
  const r = await request<unknown>(`/tickets/${ticketId}`, { method: 'PATCH', body: JSON.stringify(body) })
  return r.ok ? loadInquiry(id) : r
}

/**
 * 접수를 서버로 보내지 않는 환경(SERVER_INTAKE 꺼짐)에서 접수 관련 동작이 눌렸을 때의 안내.
 * 접수를 만들면 공유 DB 에 접수와 ITSM 작업이 남고, 작업 실행기가 없으면 끝나지 않고 쌓이기 때문이다. 서버는 부르지 않는다.
 */
export const notReady = (what: string) => fail('NOT_READY', `${what}은(는) ITSM 연동이 준비된 뒤에 열려요. 지금은 사용할 수 없어요.`)
