/**
 * 문의 대화 API 어댑터.
 *
 * 모든 동작은 갱신된 문의(Inquiry) 전체를 돌려준다. 서버 전환 후에도 같은 형태를 유지하면 화면은 바뀌지 않는다.
 * 서버 경로 (docs/api/02·03, 변환은 inquiryServer.ts):
 *   POST /inquiries                       IQ-01 새 문의 시작 (첫 메시지, AI 처리 결과)
 *   GET  /inquiries/{id}, …/messages      IQ-03·07 문의와 메시지
 *   POST /inquiries/{id}/messages         IQ-08 메시지 보내기
 *   PUT  /inquiries/{id}/resolution       IQ-09 AI 답변의 해결·미해결
 *   PATCH /inquiries/{id}                 IQ-04 담당자 연결 거절(문의 종료)
 *   POST /inquiries/{id}/sessions         IQ-06 기존 문의·세션 이어가기
 * 접수 초안·최종 접수(TK-01~04)와 접수 이후의 해결·미해결(TK-07)은 아직 서버에 연결하지 않았다.
 * 실제 서버에서는 접수 이후 진행(Jira 생성·배정·처리)이 서버에서 일어나므로, 화면은 GET 을 주기적으로 다시 읽는다.
 */
import { sleep } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import type { DraftEdit, Inquiry, ReplyRequest } from './chatTypes'
import { loadInquiry, notReady, serverClose, serverResolve, serverResume, serverSend, serverStart } from './inquiryServer'
import { advanceTicket, applyReply, cancelDraft, confirmDraft, confirmResolved, denyResolved, handle, reopenInquiry, saveDraft, sendToStaff, startInquiry, idleWarnInquiry, idleDeleteInquiry, idleBackInquiry, leaveInquiry, resumeInquiry } from './mock/chatEngine'
import './mock/chatMock'
import { getRecord, mockConfig, notify, subscribe, type StoreRecord } from './mock/chatStore'
import { fail, ok, type ApiResult } from './types'

/** 실제 서버를 다시 읽는 간격(ms) */
const POLL_MS = 4000

/** 서버 모드: 마지막으로 읽은 문의 (답변을 기다리는 동안 보여 줄 화면의 바탕), 보고 있는 화면의 갱신 함수, 진행 중인 요청 수 */
const lastSeen = new Map<number, Inquiry>()
const optimistic = new Map<number, (r: ApiResult<Inquiry>) => void>()
let inflight = 0

const remember = (r: ApiResult<Inquiry>) => {
  if (r.ok) lastSeen.set(r.data.id, r.data)
  return r
}
/** 서버 요청을 하나 실행한다. 진행 중에는 주기적 조회가 화면을 되돌리지 않게 표시해 둔다. */
async function track(job: Promise<ApiResult<Inquiry>>): Promise<ApiResult<Inquiry>> {
  inflight++
  try {
    return remember(await job)
  } finally {
    inflight--
  }
}

/**
 * 화면이 보던 문의와 서버의 문의가 어긋났을 때 서버가 주는 409 오류 (API 02, docs/09 T27).
 * 지난 버튼·창 두 개·처리 중 중복 요청에서 생기며, 화면은 안내하고 최신 문의로 다시 그린다.
 */
const STALE_CODES = new Set(['INQUIRY_INVALID_STATE', 'INQUIRY_CLOSED', 'REQUEST_IN_PROGRESS'])
export const isStaleInquiry = (code: string) => STALE_CODES.has(code)

const notFound = () => fail('INQUIRY_NOT_FOUND', '문의를 찾을 수 없어요.')

/** 화면이 안전하게 쓰도록 복사본을 돌려준다 */
const snapshot = (rec: StoreRecord): Inquiry => structuredClone(rec.inquiry)

/** 사번(employeeNo)이 소유한 문의만 다룬다. 서버에서는 토큰으로 소유자를 확인한다. */
function own(id: number, employeeNo: string): StoreRecord | undefined {
  const rec = getRecord(id)
  // 보안·로그 대상이라 숨긴 문의(응답 없음 삭제 대상)는 문의자에게 보이지 않는다
  return rec && rec.internal.owner === employeeNo && !rec.internal.hidden ? rec : undefined
}

/** 모의 동작 하나를 실행하고 갱신된 문의를 돌려준다 */
async function mockAct(id: number, employeeNo: string, act: (rec: StoreRecord) => void): Promise<ApiResult<Inquiry>> {
  await sleep(120) // 응답 지연 흉내
  const rec = own(id, employeeNo)
  if (!rec) return notFound()
  act(rec)
  notify() // 사이드바와 열려 있는 대화 화면이 바뀐 내용을 다시 읽는다
  return ok(snapshot(rec))
}

/** 새 문의를 시작한다 */
export async function startChat(user: { employeeNo: string; name: string }, text: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) {
    await sleep(120)
    const inq = startInquiry(user.employeeNo, user.name, text)
    notify() // 사이드바 최근 문의에 새 문의가 나타난다
    return ok(structuredClone(inq))
  }
  return track(serverStart(text))
}

/** 문의 상세를 읽는다. 열면 새 답변 표시가 지워진다. */
export async function getChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) {
    await sleep(60)
    if (mockConfig.loadFail) return fail('NETWORK_ERROR', '서버에 연결하지 못했어요.')
    const rec = own(id, employeeNo)
    if (!rec) return notFound()
    if (rec.inquiry.unread > 0) {
      rec.inquiry.unread = 0
      notify() // 사이드바의 새 답변 표시를 바로 지운다
    }
    return ok(snapshot(rec))
  }
  return remember(await loadInquiry(id))
}

/**
 * 문의가 바뀔 때마다 알려 준다. 모의 모드에서는 저장소 변경을, 서버 모드에서는 주기적 조회를 쓴다.
 * 돌려주는 함수를 부르면 구독이 끝난다.
 */
export function watchChat(id: number, employeeNo: string, onChange: (r: ApiResult<Inquiry>) => void): () => void {
  if (USE_MOCK_INQUIRY) {
    const off = subscribe(() => {
      const rec = own(id, employeeNo)
      // 이 화면을 보고 있으니 새 답변 표시는 바로 지운다
      if (rec) {
        rec.inquiry.unread = 0
        onChange(ok(snapshot(rec)))
      } else onChange(notFound()) // 삭제되었거나 숨겨진 문의
    })
    return off
  }
  optimistic.set(id, onChange)
  const timer = setInterval(() => {
    if (inflight) return // 답변을 기다리는 중에는 화면을 되돌리지 않는다
    loadInquiry(id).then((r) => {
      if (!inflight) onChange(remember(r))
    })
  }, POLL_MS)
  return () => {
    clearInterval(timer)
    optimistic.delete(id)
  }
}

export function sendChat(id: number, employeeNo: string, text: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) {
    return mockAct(id, employeeNo, (rec) => {
      // 접수 이후에는 담당자에게 가는 메시지이고, 답변을 준비하는 중에는 새 메시지를 받지 않는다
      if (rec.inquiry.ticket) sendToStaff(rec, text)
      else if (rec.inquiry.step !== 'answering' && rec.inquiry.step !== 'closed') handle(rec, text, false)
    })
  }
  // 서버가 답할 때까지(AI 처리는 몇 초 걸린다) 내 글과 "준비 중" 표시를 먼저 보여 준다
  const base = lastSeen.get(id)
  if (base) {
    const wait: Inquiry = {
      ...base,
      step: 'answering',
      messages: [...base.messages.map((m) => ({ ...m, replies: undefined })), { id: -1, role: 'user', text }, { id: -2, role: 'assistant', typing: { label: '답변을 준비하고 있어요' } }],
    }
    optimistic.get(id)?.(ok(wait))
  }
  return track(serverSend(id, text))
}

export function replyChat(id: number, employeeNo: string, req: ReplyRequest): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => applyReply(rec, req))
  switch (req.action) {
    case 'resolved':
      return track(serverResolve(id, 'RESOLVED'))
    case 'unresolved':
      return track(serverResolve(id, 'UNRESOLVED'))
    case 'connect-no':
      return track(serverClose(id))
    case 'connect-yes':
      return Promise.resolve(notReady('담당자 연결(접수 초안)'))
    case 'quick':
      return req.arg ? sendChat(id, employeeNo, req.arg) : track(loadInquiry(id))
    default:
      return track(loadInquiry(id))
  }
}

export function editDraft(id: number, employeeNo: string, edit: DraftEdit): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => saveDraft(rec, edit))
  return Promise.resolve(notReady('접수 초안 수정'))
}

export function confirmChatDraft(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => confirmDraft(rec))
  return Promise.resolve(notReady('최종 접수'))
}

export function cancelChatDraft(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => cancelDraft(rec))
  return Promise.resolve(notReady('접수 취소'))
}

export function resolveChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => confirmResolved(rec))
  return Promise.resolve(notReady('접수 이후 해결 확인'))
}

export function rejectChat(id: number, employeeNo: string, reason: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => denyResolved(rec, reason))
  return Promise.resolve(notReady('접수 이후 미해결 알림'))
}

export function reopenChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => reopenInquiry(rec))
  return track(serverResume(id))
}

/** 시연 전용: 응답 없이 시간이 지난 상황 (실제 서버에서는 서버가 정해진 시간 후 처리한다) */
/** 시연: 응답 없음 삭제 안내를 보낸다 (실제로는 서버가 보내는 시스템 메시지) */
export function idleWarnChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => idleWarnInquiry(rec))
}

/** 시연: 안내 뒤 대화를 삭제한다 (보안·로그 대상은 숨김) */
export function idleDeleteChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => idleDeleteInquiry(rec))
}

/** 시연: 삭제 전에 돌아온 상태 (이어서 대화하기 / 새 문의 시작하기 선택) */
export function idleBackChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => idleBackInquiry(rec))
}

/** "새 문의 시작하기": 이전 문의는 그대로 두고 돌아옴 상태만 푼다 (서버에서는 새 문의를 만드는 요청만 보내도 된다) */
export function leaveChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => leaveInquiry(rec))
}

/** "이어서 대화하기": 같은 대화·같은 단계로 계속한다 */
export function resumeChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => resumeInquiry(rec))
}

/** 시연 전용: 담당자 처리를 한 단계 앞으로 보낸다 */
export function advanceChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK_INQUIRY) return mockAct(id, employeeNo, (rec) => advanceTicket(rec))
  return Promise.resolve(fail('NOT_SUPPORTED', '시연 전용 기능이에요.'))
}
