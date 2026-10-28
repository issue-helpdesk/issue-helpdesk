/**
 * 담당자 화면이 쓰는 접수(Ticket) 타입. (docs/api/03.접수_연동.md 2.2~2.4: TicketSummary · Ticket · StatusHistory)
 * 이름과 값은 문서를 따르고, JSON 키만 camelCase 이다. 한글 표시는 catalog.ts 의 라벨표에서 붙인다.
 */
import type { AssignStatus, CategoryCode, JiraSyncStatus, Urgency, WorkStatus } from './chatTypes'
import type { DisplayStatus } from './types'

/** 상태 변경 요청의 진행 상태: 요청하면 PENDING, Jira 반영을 확인하면 IDLE, 확인하지 못하면 NEEDS_ADMIN (TK-07) */
export type TransitionStatus = 'IDLE' | 'PENDING' | 'NEEDS_ADMIN'

export interface UserRef {
  id: number
  employeeNo: string
  name: string
}

/** 목록용 접수 (TicketSummary) */
export interface TicketSummary {
  id: number
  receiptNo: string
  jiraKey: string | null
  inquiryId: number
  requester: UserRef
  summary: string
  category: { code: CategoryCode; name: string } | null
  urgency: Urgency | null
  group: { id: number; name: string } | null
  assignee: UserRef | null
  jiraSyncStatus: JiraSyncStatus
  assignStatus: AssignStatus
  workStatus: WorkStatus | null
  requestedWorkStatus: WorkStatus | null
  transitionStatus: TransitionStatus
  workStatusConfirmedAt: string | null
  needsAdmin: boolean
  displayStatus: DisplayStatus
  createdAt: string
  /**
   * Jira 댓글·멘션 알림이 도착했는데 아직 열어 보지 않은 건. (제안: TK-13 웹훅 → 화면 알림은 후속이라 문서에 응답 필드가 없다.)
   * 알림만 전달하고 댓글 내용은 Jira 에서 읽는다.
   */
  jiraMention?: boolean
}

/** 상세 접수 (Ticket) */
export interface TicketDetail extends TicketSummary {
  targetSystem: string | null
  symptom: string | null
  occurredAt: string | null
  inquiryType: { code: string; name: string } | null
  urgencyReason: string | null
  businessImpact: string | null
  triedActions: string | null
  /** AI 안내 요약 (Jira 접수 내용에만 들어가는 값) */
  aiSummary?: string | null
  jiraUrl: string | null
  resolutionNote: string | null
  finishedAt: string | null
  closedAt: string | null
}

/** 업무 상태 이력 (StatusHistory) */
export interface StatusHistory {
  id: number
  ticketId: number
  fromStatus: WorkStatus | null
  toStatus: WorkStatus
  /** JIRA: Jira 에서 바뀜, ITSSUE: 이 화면에서 요청 */
  source: 'JIRA' | 'ITSSUE'
  actor: UserRef | null
  reason: string | null
  changedAt: string
}

/** 접수 목록 조건 (TK-05) */
export interface TicketListQuery {
  view?: 'REQUESTER' | 'ASSIGNED' | 'ALL'
  page?: number
  size?: number
  /** "기준,방향". 가능: createdAt · urgency · workStatus (제목·접수번호 정렬은 프로토타입용 임시 값) */
  sort?: string
  workStatus?: WorkStatus[]
  needsAdmin?: boolean
  categoryCode?: CategoryCode[]
  urgency?: Urgency[]
  assigneeId?: number
  /** 이 날짜 00:00부터 (YYYY-MM-DD) */
  createdFrom?: string
  q?: string
  /** 제안: Jira 알림이 온 건만 */
  jiraMention?: boolean
}

/** 업무 상태 변경 요청 본문 (TK-07) */
export interface TicketTransitionRequest {
  workStatus?: 'WIP' | 'FIN'
  resolutionNote?: string
}

/** 담당자가 문의자에게 보낸 메시지 (제안: 문서상 AI 중개 양방향 소통은 Could 범위) */
export type MessageKind = '추가 정보 요청' | '일반 메시지'
export interface TicketMessage {
  id: number
  from: string
  kind: MessageKind
  text: string
  at: string
}

/** Slack 알림 미리보기 (실제 발송은 하지 않는다) */
export interface SlackPreview {
  to: string
  text: string
  at: string
}
