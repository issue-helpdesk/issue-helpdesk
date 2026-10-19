/**
 * 시연용 문의 저장소 (메모리). 새로고침하면 처음 상태로 돌아간다.
 * 실제 API(VITE_USE_MOCK=false)에서는 쓰이지 않으며, 서버가 같은 역할을 한다.
 *
 * 저장소는 문의 데이터와 함께 대화 엔진이 쓰는 내부 상태(수집한 정보, 긴급 여부 등)를 가진다.
 * 내부 상태는 API 응답에 포함하지 않는다.
 */
import type { CategoryCode, ChatMessage, Inquiry, Ticket } from '../chatTypes'

/** 문의 수집 단계에서 모으는 항목 (순서대로 묻는다) */
export type IntakeKey = 'system' | 'issue' | 'onset' | 'impact' | 'tried'

export interface Intake {
  system?: string
  issue?: string
  onset?: string
  impact?: string
  tried?: string
  /** 답변 이후 문의자가 덧붙인 내용 */
  extra?: string
  /** 외부 전송이 제한되는 문서 질의 여부 */
  restricted?: boolean
  /** 확인 질문 안내 문구를 이미 보여 주었는지 */
  asked?: boolean
}

/** 응답에 포함되지 않는 엔진 내부 상태 */
export interface Internal {
  owner: string
  ownerName: string
  intake: Intake
  /** 지금 답을 기다리는 수집 항목 */
  pending: IntakeKey | null
  urgent: boolean
  /** 안내에 쓴 Guide 요약 (초안의 "AI 안내" 항목) */
  guideLabel: string | null
}

interface Record_ {
  inquiry: Inquiry
  internal: Internal
}

/** 시연 동작 설정. 테스트에서는 지연을 0 으로 바꾸고 자동 진행을 끈다. */
export const mockConfig = {
  /** 답변 준비 중 표시 시간(ms) */
  typingMs: 1100,
  /** Jira 번호 생성·담당자 배정·처리 시작 같은 접수 이후 단계 간격의 배율 (0 이면 즉시) */
  pipelineScale: 1,
  /** 접수 후 담당자 처리 시작~결과 등록까지 시연용으로 자동 진행할지 */
  autoRun: true,
  /** 접수 저장 실패 시연 */
  saveFail: false,
}

const records = new Map<string, Record_>()
const listeners = new Set<() => void>()
let timers: ReturnType<typeof setTimeout>[] = []

const seq = { inq: 1, msg: 1000, rcpt: 1042, its: 1521 }

/** 저장소가 바뀔 때 부르는 구독 (문의 하나가 바뀌어도 목록과 상세가 모두 다시 읽는다) */
export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

export function notify() {
  listeners.forEach((fn) => fn())
}

/** 시연용 지연 실행. 저장소를 초기화하면 남은 예약도 함께 취소한다. */
export function later(ms: number, fn: () => void) {
  const t = setTimeout(() => {
    timers = timers.filter((x) => x !== t)
    fn()
  }, ms)
  timers.push(t)
}

/** 현재 시각 표시 (예: 10.19 14:05) */
export function nowLabel(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export const nextRcpt = () => `RCPT-${seq.rcpt++}`
export const nextIts = () => `ITS-${seq.its++}`

/** 메시지를 대화 끝에 붙이고 번호를 매긴다 */
export function push(inq: Inquiry, m: Omit<ChatMessage, 'id'>): ChatMessage {
  const msg: ChatMessage = { ...m, id: seq.msg++ }
  inq.messages.push(msg)
  return msg
}

export function createRecord(owner: string, ownerName: string, title: string, fixedId?: string): Record_ {
  const inquiry: Inquiry = {
    id: fixedId ?? `INQ-${seq.inq++}`,
    title,
    state: '진행 중',
    step: 'collect',
    category: null as CategoryCode | null,
    unread: 0,
    when: '방금',
    messages: [],
    draft: null,
    draftState: 'view',
    draftNote: '',
    ticket: null as Ticket | null,
  }
  const rec: Record_ = { inquiry, internal: { owner, ownerName, intake: {}, pending: null, urgent: false, guideLabel: null } }
  records.set(inquiry.id, rec)
  return rec
}

export function getRecord(id: string): Record_ | undefined {
  return records.get(id)
}

/** 사번의 문의를 최근 순으로 돌려준다 */
export function recordsOf(owner: string): Record_[] {
  return [...records.values()].filter((r) => r.internal.owner === owner).reverse()
}

export function clearRecords() {
  records.clear()
}

export function resetSeq() {
  seq.inq = 1
  seq.msg = 1000
  seq.rcpt = 1042
  seq.its = 1521
}

export function cancelTimers() {
  timers.forEach(clearTimeout)
  timers = []
}

export type { Record_ as StoreRecord }
