/**
 * 문의 대화(챗봇) API 계약 타입.
 * 이름과 값은 06 테이블 설계서의 DB 컬럼·코드 값을 따르고, JSON 키만 camelCase 로 쓴다. (docs/07.API_계약서.md)
 *
 * 답변 본문은 HTML 이 아니라 구조화된 블록으로 주고받는다. 화면이 React 요소로만 그리므로
 * 서버가 준 문구에 스크립트가 섞여 있어도 실행되지 않는다. (**굵게** 표시만 지원)
 */

/** 문의 분류 7종 (PRD 4.3) */
export type CategoryCode = 'ACC' | 'ACS' | 'NET' | 'SW' | 'HW' | 'SYS' | 'SEC'

/** 긴급도 P1(긴급) ~ P4(낮음) (urgency) */
export type Urgency = 'P1' | 'P2' | 'P3' | 'P4'

/**
 * 문의(대화) 자체의 상태 (inquiries.status). 한글 표시는 catalog.ts 의 INQUIRY_STATUS_LABEL.
 * 접수 이후의 진행 단계는 Ticket 업무 상태(RDY → WIP → FIN → CLS)가 따로 나타낸다.
 */
export type InquiryStatus = 'IN_PROGRESS' | 'AI_RESOLVED' | 'UNCONFIRMED' | 'CLOSED_UNRESOLVED' | 'RECEIVED' | 'HANDED_OFF'

/** 대화 진행 단계 (화면이 입력창·버튼을 정할 때 쓴다) */
/** 종료 10분 전 안내 문구 (docs/09 T28). 서버가 시스템 메시지로 보내고, 화면은 입력창 위 띠로도 보여 준다. */
export const IDLE_WARN_TEXT = '추가 문의사항이 없으면 채팅을 종료하겠습니다.'

export type ChatStep = 'collect' | 'answering' | 'answered' | 'offer' | 'draft' | 'submitted' | 'closed'

/** Ticket 업무 상태 (tickets.work_status): 처리 대기 → 처리 중 → 해결 확인 대기 → 해결 완료 */
export type WorkStatus = 'RDY' | 'WIP' | 'FIN' | 'CLS'

/** 배정 상태 (tickets.assign_status) */
export type AssignStatus = 'PENDING' | 'ASSIGNED' | 'NEEDS_ADMIN'

/** Jira 연동 상태 (tickets.jira_sync_status) */
export type JiraSyncStatus = 'PENDING' | 'VERIFYING' | 'SYNCED' | 'NEEDS_ADMIN'

/** 답변에 붙는 근거 Guide 출처. 문의 화면·로그인 전 상담·FAQ 가 같은 형태를 쓴다. */
export interface GuideSource {
  /** 문서 코드 (knowledge_documents.doc_code, 예: IT-NET-001) */
  docCode: string
  /** 문서 제목 */
  title: string
  /** 문서 버전 (document_versions.version, 예: v2) */
  version: string
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
  | { type: 'urgent'; groupName: string; urgency: Urgency; urgencyReasons: string[] }

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
  groupName?: string
  kind?: string
  /** 메시지 시각 (ISO 8601) */
  createdAt?: string
}

/** 접수 초안 (문의자가 확인·수정한 뒤에만 접수된다) */
export interface Draft {
  title: string
  categoryCode: CategoryCode | null
  targetSystem: string
  /** 문의 요약 (ticket_drafts.summary) */
  summary: string
  /** 발생 시점. DB 컬럼 없이 Jira 접수 내용에만 넣는다. */
  onset: string
  /** 업무 영향 (business_impact) */
  businessImpact: string
  triedActions: string
  /** AI 안내 요약. DB 컬럼 없이 Jira 접수 내용에만 넣는다. */
  aiSummary: string
  urgency: Urgency
  /** 긴급도 근거. DB urgency_reason 에는 줄바꿈으로 합쳐 저장한다. */
  urgencyReasons: string[]
  /** 추천 담당 그룹 */
  groupId: number | null
  groupName: string
  /** 세부 유형 코드와 이름 (예: NET-02 · VPN 접속 불가(개인)). 판단하지 못하면 없음 (inquiry_types.code) */
  inquiryTypeCode?: string | null
  inquiryTypeName?: string | null
  /** 초안을 고친 뒤 다시 판단해서 값이 바뀐 항목. 화면이 "다시 판단됨" 표시를 붙인다. */
  rejudged?: RejudgedField[]
}

/** 초안에서 다시 판단되는 항목 */
export type RejudgedField = 'category' | 'inquiryType' | 'urgency' | 'group'

/** 초안에서 문의자가 고칠 수 있는 항목 (분류·세부 유형·긴급도·담당 그룹은 이 글로 다시 판단한다) */
export interface DraftEdit {
  summary: string
  /** 발생 시점. 문의자가 쓴 말이라 고칠 수 있다. 보내지 않으면 기존 값을 유지한다. */
  onset?: string
  businessImpact: string
  triedActions: string
}

export type DraftState = 'view' | 'confirmed' | 'cancel'

/** 접수된 Ticket 중 문의자에게 보이는 정보 */
export interface Ticket {
  /** 접수번호 RCPT-#### */
  receiptNo: string
  /** Jira 이슈 키 ITSD-####. 생성 전에는 null */
  jiraKey: string | null
  title: string
  categoryCode: CategoryCode | null
  urgency: Urgency
  groupId: number | null
  groupName: string
  assigneeId: number | null
  assigneeName: string | null
  /** 업무 상태. Jira 생성 직후 RDY, Jira 생성 전에는 null */
  workStatus: WorkStatus | null
  /** 배정 여부는 업무 상태와 따로 나타낸다 */
  assignStatus: AssignStatus
  jiraSyncStatus: JiraSyncStatus
  /** 접수 시각 (ISO 8601) */
  createdAt: string
  /** 담당자가 처리 결과를 등록한 시각 (해결 확인 대기가 된 때). 아직이면 없음 */
  finishedAt?: string | null
  /** 문의자가 해결을 확인해 종료된 시각. 아직이면 없음 */
  closedAt?: string | null
  /** 담당자가 등록한 처리 결과 (tickets.resolution_note) */
  resolutionNote: string
  /** 담당자가 추가 정보를 요청해 문의자의 답변을 기다리는 중 */
  needReply: boolean
}

export interface Inquiry {
  /** 문의 ID (inquiries.id). 화면에는 보이지 않고, 문의자에게는 접수번호만 보인다. */
  id: number
  title: string
  status: InquiryStatus
  step: ChatStep
  categoryCode: CategoryCode | null
  /** 확인하지 않은 담당자 답변 수 */
  unread: number
  /** 최근 활동 시각 (ISO 8601). '어제' 같은 표시는 화면에서 계산한다. */
  updatedAt: string
  messages: ChatMessage[]
  draft: Draft | null
  draftState: DraftState
  /** 초안 수정 후 다시 판단한 결과 안내 */
  draftNote: string
  ticket: Ticket | null
  /** 종료 10분 전 안내를 보낸 상태. 화면이 입력창 위에 안내 띠를 보여 준다. 문의자가 답하면 해제된다. */
  idleWarned?: boolean
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
