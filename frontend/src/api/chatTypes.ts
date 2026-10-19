/**
 * 문의 대화(챗봇) API 계약 타입 (제안).
 * 백엔드(A)가 확정한 값에 맞춰 이 파일과 어댑터(chat.ts)만 고친다.
 *
 * 답변 본문은 HTML 이 아니라 구조화된 블록으로 주고받는다. 화면이 React 요소로만 그리므로
 * 서버가 준 문구에 스크립트가 섞여 있어도 실행되지 않는다. (**굵게** 표시만 지원)
 */

/** 문의 분류 7종 (PRD 4.3) */
export type CategoryCode = 'ACC' | 'ACS' | 'NET' | 'SW' | 'HW' | 'SYS' | 'SEC'

/** 긴급도 P1(긴급) ~ P4(낮음) */
export type Priority = 'P1' | 'P2' | 'P3' | 'P4'

/**
 * 문의(대화) 자체의 상태.
 * 접수 이후의 진행 단계는 Ticket 상태(RDY → WIP → FIN → CLS)가 따로 나타낸다.
 */
export type InquiryState = '진행 중' | 'AI 해결' | '미확인' | '미해결 종료' | '접수 완료' | '담당자 이관'

/** 대화 진행 단계 (화면이 입력창·버튼을 정할 때 쓴다) */
export type ChatStep = 'collect' | 'answering' | 'answered' | 'offer' | 'draft' | 'submitted' | 'closed'

/** Ticket 상태: 처리 대기 → 처리 중 → 해결 확인 대기 → 해결 완료 (06 설계서의 RDY/WIP/FIN/CLS) */
export type TicketStatus = 'RDY' | 'WIP' | 'FIN' | 'CLS'

/** 답변에 붙는 근거 Guide 출처 */
export interface GuideSource {
  guide: string
  version: number
  section: string
  /** 출처 미리보기에 보여 줄 요약 */
  excerpt: string
}

/** 도입 이전 처리 이력(읽기 전용) 참고 표시 */
export interface LegacyCase {
  no: string
  title: string
  symptom: string
  solution: string
}

/** 답변 본문 블록 */
export type ChatBlock =
  | { type: 'p'; text: string; muted?: boolean }
  | { type: 'ol'; items: string[] }
  /** 긴급 징후 요약 카드 */
  | { type: 'urgent'; group: string; priority: Priority; why: string[] }

/** 답변 아래 빠른 응답 버튼이 보내는 동작 */
export type ReplyAction = 'quick' | 'resolved' | 'unresolved' | 'connect-yes' | 'connect-no' | 'noop'

export interface ChatReply {
  label: string
  action: ReplyAction
  /** quick 일 때 대화에 보낼 문장 */
  arg?: string
  primary?: boolean
}

/** 메시지에 붙는 카드 종류 */
export type ChatCard = 'draft' | 'ticket' | 'savefail'

export interface ChatMessage {
  id: number
  /** user=문의자, assistant=AI, staff=담당자, sys=시스템 안내 */
  role: 'user' | 'assistant' | 'staff' | 'sys'
  /** user·staff·sys 메시지 본문 */
  text?: string
  /** assistant 메시지 본문 */
  blocks?: ChatBlock[]
  sources?: GuideSource[]
  legacy?: LegacyCase
  replies?: ChatReply[]
  /** 이미 응답했거나 지나간 단계여서 버튼을 누를 수 없는 상태 */
  locked?: boolean
  /** 시연용 "응답 없이 시간 경과" 버튼 표시 */
  demoTimeout?: boolean
  /** 답변을 준비 중임을 나타내는 점 세 개 표시 */
  typing?: { label: string }
  card?: ChatCard
  /** 다시 확인 요청 때 옛 진행 카드를 그대로 남기는 스냅샷 */
  ticketSnapshot?: Ticket
  /** staff 메시지 */
  from?: string
  group?: string
  kind?: string
  time?: string
}

/** 접수 초안 (문의자가 확인·수정한 뒤에만 접수된다) */
export interface Draft {
  title: string
  category: CategoryCode | null
  system: string
  issue: string
  onset: string
  impact: string
  tried: string
  /** AI 안내 요약 */
  ai: string
  priority: Priority
  priorityWhy: string[]
  /** 추천 담당 그룹 */
  group: string
}

/** 초안에서 문의자가 고칠 수 있는 항목 */
export interface DraftEdit {
  issue: string
  impact: string
  tried: string
}

export type DraftState = 'view' | 'confirmed' | 'cancel'

/** 접수된 Ticket 중 문의자에게 보이는 정보 */
export interface Ticket {
  /** 접수번호 RCPT-#### */
  receipt: string
  /** Jira Ticket 번호 ITS-####. 생성 전에는 null */
  jiraId: string | null
  title: string
  category: CategoryCode | null
  priority: Priority
  group: string
  assignee: string | null
  /** 담당자 배정 전에는 null */
  status: TicketStatus | null
  created: string
  /** 담당자가 등록한 처리 결과 */
  result: string
  /** 담당자가 추가 정보를 요청해 문의자의 답변을 기다리는 중 */
  needReply: boolean
}

export interface Inquiry {
  /** 문의 번호 */
  id: string
  title: string
  state: InquiryState
  step: ChatStep
  category: CategoryCode | null
  /** 확인하지 않은 담당자 답변 수 */
  unread: number
  /** 최근 활동 표시 (예: 방금, 어제) */
  when: string
  messages: ChatMessage[]
  draft: Draft | null
  draftState: DraftState
  /** 초안 수정 후 다시 판단한 결과 안내 */
  draftNote: string
  ticket: Ticket | null
}

/** 로그인한 사용자의 문의 한 건 요청: 첫 메시지 */
export interface StartInquiryRequest {
  text: string
}

/** 빠른 응답 버튼 전송 */
export interface ReplyRequest {
  messageId: number
  action: ReplyAction
  arg?: string
}
