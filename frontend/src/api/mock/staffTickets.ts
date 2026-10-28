/**
 * 시연용 담당자 접수 저장소. 실제 API(VITE_USE_MOCK=false)에서는 쓰이지 않으며 서버가 같은 역할을 한다.
 *
 * 담당자 화면의 접수는 두 곳에서 온다.
 *  1) 이 파일의 시연 접수: 네트워크팀 김담당(EMP-1107)이 맡은 여러 상태의 접수
 *  2) 문의자가 대화에서 접수한 Ticket: 문의 저장소(chatStore)의 문의에 붙어 있고, 담당자 화면에서도 보인다.
 *     담당자가 상태를 바꾸면 문의자 화면의 진행 카드도 함께 바뀐다.
 * 저장소가 바뀌면 chatStore 의 notify 로 알려, 열려 있는 모든 화면이 다시 읽는다.
 */
import { CATEGORIES, FALLBACK_GROUP } from '../catalog'
import type { CategoryCode, Urgency, WorkStatus } from '../chatTypes'
import type { SlackPreview, StatusHistory, TicketDetail, TicketMessage, UserRef } from '../ticketTypes'
import type { DisplayStatus } from '../types'
import { nowIso } from '../../core/format'
import { MOCK_ACCOUNTS } from './accounts'
import { notify, allRecords, type StoreRecord } from './chatStore'

/** 담당 그룹 이름 → 그룹 ID (시연용) */
const GROUP_ID: Record<string, number> = { 서비스데스크: 1, 엔드포인트지원팀: 2, 네트워크팀: 3, 시스템인프라팀: 4, 업무시스템팀: 5, 정보보안팀: 6 }

const ME: UserRef = { id: 2, employeeNo: 'EMP-1107', name: '김담당' }
const OTHER: UserRef = { id: 302, employeeNo: 'EMP-1108', name: '전다랑' }

const userOf = (employeeNo: string, fallbackName = ''): UserRef => {
  const a = MOCK_ACCOUNTS.find((x) => x.employeeNo === employeeNo)
  return a ? { id: a.id, employeeNo: a.employeeNo, name: a.name } : { id: 0, employeeNo, name: fallbackName }
}

const displayOf = (w: WorkStatus | null): DisplayStatus => (w === 'WIP' ? 'progress' : w === 'FIN' ? 'awaiting_confirm' : w === 'CLS' ? 'resolved' : w === 'RDY' ? 'assigned' : 'received')

/* ------------------------------------------------------------------ 시연 접수 */
interface SeedArgs {
  n: number
  title: string
  cat: CategoryCode
  p: Urgency
  who: string
  workStatus: WorkStatus
  /** 접수한 지 며칠·몇 시간 전인지 */
  ago: { d?: number; h?: number }
  assignee?: UserRef
  note?: string
  system?: string
  symptom?: string
  impact?: string
  tried?: string
  reason?: string
  mention?: boolean
}

const WHO: Record<string, UserRef> = {
  서연: { id: 1, employeeNo: 'EMP-1001', name: '김서연' },
  민수: { id: 4, employeeNo: 'EMP-1003', name: '박민수' },
  지은: { id: 5, employeeNo: 'EMP-1004', name: '이지은' },
  신입: { id: 8, employeeNo: 'EMP-1010', name: '한신입' },
}

const at = (a: { d?: number; h?: number }) => new Date(Date.now() - ((a.d ?? 0) * 24 + (a.h ?? 0)) * 3_600_000).toISOString()

function seedTicket(a: SeedArgs): TicketDetail {
  const created = at(a.ago)
  const w = a.workStatus
  const done = w === 'FIN' || w === 'CLS'
  return {
    id: 5000 + a.n,
    receiptNo: `RCPT-${String(880 + a.n).padStart(4, '0')}`,
    jiraKey: `ITHD-${880 + a.n}`,
    inquiryId: 9000 + a.n,
    requester: WHO[a.who],
    summary: a.title,
    category: { code: a.cat, name: CATEGORIES[a.cat].name },
    urgency: a.p,
    group: { id: GROUP_ID.네트워크팀, name: '네트워크팀' },
    assignee: a.assignee ?? ME,
    jiraSyncStatus: 'SYNCED',
    assignStatus: 'ASSIGNED',
    workStatus: w,
    requestedWorkStatus: null,
    transitionStatus: 'IDLE',
    workStatusConfirmedAt: created,
    needsAdmin: false,
    displayStatus: displayOf(w),
    createdAt: created,
    jiraMention: !!a.mention,
    targetSystem: a.system ?? 'VPN·네트워크',
    symptom: a.symptom ?? a.title,
    occurredAt: '어제부터요.',
    inquiryType: null,
    urgencyReason: a.reason ?? (a.p === 'P1' ? '다수 사용자 업무 중단' : a.p === 'P2' ? '업무 지장, 대체 방법 제한적' : '개인 업무 일부 지장, 대체 방법 있음'),
    businessImpact: a.impact ?? '업무에 불편이 있어요.',
    triedActions: a.tried ?? '재접속과 재시작을 해봤어요.',
    aiSummary: 'IT-NET-001 안내 후에도 해결되지 않음',
    jiraUrl: `https://jira.example.com/browse/ITHD-${880 + a.n}`,
    resolutionNote: done ? (a.note ?? '원인을 확인하고 조치를 완료했습니다.') : null,
    finishedAt: done ? at({ d: Math.max(0, (a.ago.d ?? 0) - 1) }) : null,
    closedAt: w === 'CLS' ? at({ d: Math.max(0, (a.ago.d ?? 0) - 1), h: -2 }) : null,
  }
}

const SEED_ARGS: SeedArgs[] = [
  { n: 1, title: '악성 첨부파일 의심 메일 수신', cat: 'SEC', p: 'P1', who: '민수', workStatus: 'WIP', ago: { d: 4, h: 4 }, mention: true, system: '메일·보안', impact: '부서 전원이 같은 메일을 받았어요.', tried: '열어 보지 않고 보관해 두었어요.' },
  { n: 2, title: 'VPN 인증서 만료 알림이 계속 떠요', cat: 'NET', p: 'P2', who: '서연', workStatus: 'WIP', ago: { d: 1, h: 7 } },
  { n: 3, title: '사내 Wi-Fi 접속 불가 (3층)', cat: 'NET', p: 'P2', who: '지은', workStatus: 'WIP', ago: { d: 1, h: 7 }, mention: true, impact: '3층 전체가 접속되지 않아요.' },
  { n: 4, title: '재택 VPN 인증 오류', cat: 'NET', p: 'P3', who: '신입', workStatus: 'RDY', ago: { d: 2, h: 7 }, tried: '비밀번호를 다시 입력해 봤어요.' },
  { n: 5, title: '원격 접속 속도가 너무 느려요', cat: 'NET', p: 'P3', who: '민수', workStatus: 'WIP', ago: { d: 6, h: 5 } },
  { n: 6, title: '사내 메신저 연결이 자주 끊겨요', cat: 'SYS', p: 'P3', who: '서연', workStatus: 'WIP', ago: { d: 3 } },
  { n: 7, title: '프린터 네트워크 연결 오류', cat: 'HW', p: 'P4', who: '지은', workStatus: 'WIP', ago: { d: 5 } },
  { n: 8, title: '화상회의에서 음성이 끊겨요', cat: 'NET', p: 'P3', who: '신입', workStatus: 'FIN', ago: { d: 3, h: 2 }, note: '회의실 AP 채널을 변경했습니다. 다시 접속해 확인해 주세요.' },
  { n: 9, title: 'VPN 접속 후 사내 시스템이 열리지 않아요', cat: 'NET', p: 'P2', who: '서연', workStatus: 'FIN', ago: { d: 2, h: 5 }, note: 'VPN 라우팅 정책을 재배포했습니다. 클라이언트를 재시작하고 접속해 주세요.' },
  { n: 10, title: '사내망 DNS 응답이 느려요', cat: 'NET', p: 'P4', who: '민수', workStatus: 'FIN', ago: { d: 4 }, note: 'DNS 캐시를 정리했습니다.' },
  { n: 11, title: '신규 노트북 VPN 클라이언트 설치', cat: 'SW', p: 'P4', who: '신입', workStatus: 'CLS', ago: { d: 9 }, note: '클라이언트 설치와 인증서 등록을 완료했습니다.' },
  { n: 12, title: 'Wi-Fi 비밀번호 변경 안내 요청', cat: 'NET', p: 'P4', who: '지은', workStatus: 'CLS', ago: { d: 12 }, note: '변경된 비밀번호를 안내했습니다.' },
  { n: 13, title: '사무실 이전 후 네트워크 포트 점검', cat: 'NET', p: 'P3', who: '민수', workStatus: 'CLS', ago: { d: 15 }, note: '포트 매핑을 확인하고 정상 동작을 확인했습니다.' },
  { n: 14, title: 'VPN 이중 인증 코드가 오지 않아요', cat: 'ACC', p: 'P3', who: '서연', workStatus: 'CLS', ago: { d: 20 }, note: '인증 번호 수신 번호를 갱신했습니다.' },
  // 다른 담당자(전다랑)가 맡은 건: 내 목록에는 보이지 않고 팀 현황에만 들어간다
  { n: 15, title: '방화벽 예외 규칙 요청', cat: 'NET', p: 'P3', who: '민수', workStatus: 'WIP', ago: { d: 2 }, assignee: OTHER },
  { n: 16, title: '외부 접속 포트 확인 요청', cat: 'NET', p: 'P4', who: '지은', workStatus: 'RDY', ago: { d: 1 }, assignee: OTHER },
]

let seeds: TicketDetail[] = []
/** 담당자 화면에서 직접 요청한 상태 변경 이력 (시연 접수·문의자 접수 공통) */
const explicitHistory = new Map<number, StatusHistory[]>()
/** 담당자가 문의자에게 보낸 메시지와 Slack 알림 미리보기 (제안, 모의) */
const messages = new Map<number, TicketMessage[]>()
const slackLog: (SlackPreview & { ticketId: number })[] = []
let msgSeq = 1
let histSeq = 1

/** 시연 접수와 이력을 처음 상태로 되돌린다 (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetStaffMock() {
  seeds = SEED_ARGS.map(seedTicket)
  explicitHistory.clear()
  messages.clear()
  slackLog.length = 0
  histSeq = 1
}
resetStaffMock()

/* ------------------------------------------------------------------ 문의자가 접수한 Ticket */
const CHAT_ID_BASE = 100_000
/** 문의자가 접수한 건의 접수 ID (모의). 서버에서는 문의 응답이 접수 ID 를 함께 준다 */
export const ticketIdOfInquiry = (inquiryId: number) => CHAT_ID_BASE + inquiryId

function fromRecord(rec: StoreRecord): TicketDetail | null {
  const { inquiry, internal } = rec
  const t = inquiry.ticket
  if (!t) return null
  const groupName = t.groupName || FALLBACK_GROUP
  const d = inquiry.draft
  return {
    id: CHAT_ID_BASE + inquiry.id,
    receiptNo: t.receiptNo,
    jiraKey: t.jiraKey,
    inquiryId: inquiry.id,
    requester: userOf(internal.owner, internal.ownerName),
    summary: d?.summary || inquiry.title,
    category: t.categoryCode ? { code: t.categoryCode, name: CATEGORIES[t.categoryCode].name } : null,
    urgency: t.urgency,
    group: { id: t.groupId ?? GROUP_ID[groupName] ?? 0, name: groupName },
    assignee: t.assigneeId && t.assigneeName ? { id: t.assigneeId, employeeNo: '', name: t.assigneeName } : null,
    jiraSyncStatus: t.jiraSyncStatus,
    assignStatus: t.assignStatus,
    workStatus: t.workStatus,
    requestedWorkStatus: pending.get(CHAT_ID_BASE + inquiry.id) ?? null,
    transitionStatus: pending.has(CHAT_ID_BASE + inquiry.id) ? 'PENDING' : 'IDLE',
    workStatusConfirmedAt: t.createdAt,
    needsAdmin: t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING' || t.assignStatus === 'NEEDS_ADMIN',
    displayStatus: displayOf(t.workStatus),
    createdAt: t.createdAt,
    jiraMention: false,
    targetSystem: d?.targetSystem ?? null,
    symptom: d?.summary ?? null,
    occurredAt: d?.occurredAt ?? null,
    inquiryType: d?.inquiryTypeCode ? { code: d.inquiryTypeCode, name: d.inquiryTypeName ?? '' } : null,
    urgencyReason: d?.urgencyReasons?.join(' · ') ?? null,
    businessImpact: d?.businessImpact ?? null,
    triedActions: d?.triedActions ?? null,
    aiSummary: d?.aiSummary ?? null,
    jiraUrl: t.jiraKey ? `https://jira.example.com/browse/${t.jiraKey}` : null,
    resolutionNote: t.resolutionNote || null,
    finishedAt: t.finishedAt ?? null,
    closedAt: t.closedAt ?? null,
  }
}

/** 상태 변경을 요청했지만 Jira 반영을 아직 확인하지 못한 접수 (ID → 목표 상태) */
export const pending = new Map<number, WorkStatus>()

/** 문의자 접수 Ticket 의 문의 저장소 기록 */
export function recordOfTicket(id: number): StoreRecord | undefined {
  return allRecords().find((r) => CHAT_ID_BASE + r.inquiry.id === id && r.inquiry.ticket)
}

/** 시연 접수와 문의자 접수를 합친 전체 목록 (최근 접수가 먼저) */
export function allStaffTickets(): TicketDetail[] {
  const chat = allRecords().map(fromRecord).filter((x): x is TicketDetail => !!x)
  const seeded = seeds.map((s) => ({ ...s, requestedWorkStatus: pending.get(s.id) ?? null, transitionStatus: pending.has(s.id) ? ('PENDING' as const) : s.transitionStatus }))
  return [...chat, ...seeded].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
}

export const findStaffTicket = (id: number): TicketDetail | undefined => allStaffTickets().find((t) => t.id === id)

/** 시연 접수 하나를 바꾼다 (문의자 접수는 chatEngine 이 바꾼다) */
export function mutateSeed(id: number, fn: (t: TicketDetail) => void): boolean {
  const s = seeds.find((x) => x.id === id)
  if (!s) return false
  fn(s)
  notify()
  return true
}

/** Jira 알림을 열어 본 것으로 표시한다 */
export function clearMention(id: number) {
  const s = seeds.find((x) => x.id === id)
  if (s?.jiraMention) s.jiraMention = false
}

/* ------------------------------------------------------------------ 이력 */
export function addHistory(ticketId: number, h: Omit<StatusHistory, 'id' | 'ticketId'>) {
  const list = explicitHistory.get(ticketId) ?? []
  list.push({ ...h, id: 9000 + histSeq++, ticketId })
  explicitHistory.set(ticketId, list)
}

/** 접수·처리 시작·처리 결과 이력 (changedAt 오름차순). 이 화면에서 요청한 변경은 그대로, 나머지는 시각에서 만든다. */
export function historyOf(t: TicketDetail): StatusHistory[] {
  const explicit = explicitHistory.get(t.id) ?? []
  const has = (w: WorkStatus) => explicit.some((h) => h.toStatus === w)
  const base: StatusHistory[] = []
  const mk = (toStatus: WorkStatus, fromStatus: WorkStatus | null, changedAt: string): StatusHistory => ({ id: 0, ticketId: t.id, fromStatus, toStatus, source: 'JIRA', actor: null, reason: null, changedAt })
  if (t.workStatus) base.push(mk('RDY', null, t.createdAt))
  const order: WorkStatus[] = ['RDY', 'WIP', 'FIN', 'CLS']
  const idx = t.workStatus ? order.indexOf(t.workStatus) : -1
  if (idx >= 1 && !has('WIP')) base.push(mk('WIP', 'RDY', new Date(Date.parse(t.createdAt) + 10 * 60_000).toISOString()))
  if (idx >= 2 && !has('FIN')) base.push(mk('FIN', 'WIP', t.finishedAt ?? nowIso()))
  if (idx >= 3 && !has('CLS')) base.push(mk('CLS', 'FIN', t.closedAt ?? nowIso()))
  return [...base, ...explicit].sort((a, b) => Date.parse(a.changedAt) - Date.parse(b.changedAt)).map((h, i) => ({ ...h, id: h.id || i + 1 }))
}

/** 같은 그룹 팀원 (모의): 이름과 근무 여부. 서버에는 아직 이 정보를 주는 API 가 없어 제안으로 다룬다 */
export const TEAM_MEMBERS: Record<string, { name: string; avail: boolean }[]> = {
  네트워크팀: [
    { name: '김담당', avail: true },
    { name: '전다랑', avail: true },
    { name: '정네트', avail: false },
  ],
}

export const messagesOf = (ticketId: number) => messages.get(ticketId) ?? []
export const slackOf = (ticketId: number) => slackLog.filter((s) => s.ticketId === ticketId).map(({ ticketId: _t, ...s }) => s)
export function addMessage(ticketId: number, m: Omit<TicketMessage, 'id'>) {
  const list = messages.get(ticketId) ?? []
  list.push({ ...m, id: msgSeq++ })
  messages.set(ticketId, list)
  slackLog.unshift({ ticketId, to: '문의자', text: '담당자 메시지가 도착했습니다.', at: m.at })
}
