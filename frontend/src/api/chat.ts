/**
 * 문의 대화 API 어댑터.
 *
 * 모든 동작은 갱신된 문의(Inquiry) 전체를 돌려준다. 서버 전환 후에도 같은 형태를 유지하면 화면은 바뀌지 않는다.
 * 제안 엔드포인트 (시스템 설계서 9.2 를 바탕으로, 백엔드(A)와 맞춘 뒤 확정):
 *   POST /inquiries                       새 문의 시작 (첫 메시지)
 *   GET  /inquiries/{id}                  문의 상세 (열면 새 답변 표시가 지워진다)
 *   POST /inquiries/{id}/messages         메시지 보내기
 *   POST /inquiries/{id}/replies          빠른 응답 버튼
 *   POST /inquiries/{id}/draft/edit       접수 초안 수정 (분류·긴급도 재판단)
 *   POST /inquiries/{id}/draft/confirm    초안 확인 후 접수
 *   POST /inquiries/{id}/draft/cancel     접수하지 않고 종료
 *   POST /inquiries/{id}/resolve          접수 후 "해결"
 *   POST /inquiries/{id}/reject           접수 후 "미해결" (사유 필수)
 *   POST /inquiries/{id}/reopen           종료된 상담 다시 열기
 * 실제 서버에서는 접수 이후 진행(Jira 생성·배정·처리)이 서버에서 일어나므로, 화면은 GET 을 주기적으로 다시 읽는다.
 */
import { request, sleep } from '../core/apiClient'
import { USE_MOCK } from '../core/config'
import type { DraftEdit, Inquiry, ReplyRequest } from './chatTypes'
import { advanceTicket, applyReply, cancelDraft, confirmDraft, confirmResolved, denyResolved, handle, reopenInquiry, saveDraft, sendToStaff, startInquiry, timeoutInquiry, idleWarnInquiry } from './mock/chatEngine'
import './mock/chatMock'
import { getRecord, notify, subscribe, type StoreRecord } from './mock/chatStore'
import { fail, ok, type ApiResult } from './types'

/** 실제 서버를 다시 읽는 간격(ms) */
const POLL_MS = 4000

/** POST 요청 (본문은 JSON 으로 보낸다) */
const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

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
  return rec && rec.internal.owner === employeeNo ? rec : undefined
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
  if (USE_MOCK) {
    await sleep(120)
    const inq = startInquiry(user.employeeNo, user.name, text)
    notify() // 사이드바 최근 문의에 새 문의가 나타난다
    return ok(structuredClone(inq))
  }
  return post<Inquiry>('/inquiries', { text })
}

/** 문의 상세를 읽는다. 열면 새 답변 표시가 지워진다. */
export async function getChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) {
    await sleep(60)
    const rec = own(id, employeeNo)
    if (!rec) return notFound()
    if (rec.inquiry.unread > 0) {
      rec.inquiry.unread = 0
      notify() // 사이드바의 새 답변 표시를 바로 지운다
    }
    return ok(snapshot(rec))
  }
  return request<Inquiry>(`/inquiries/${encodeURIComponent(id)}`)
}

/**
 * 문의가 바뀔 때마다 알려 준다. 모의 모드에서는 저장소 변경을, 서버 모드에서는 주기적 조회를 쓴다.
 * 돌려주는 함수를 부르면 구독이 끝난다.
 */
export function watchChat(id: number, employeeNo: string, onChange: (r: ApiResult<Inquiry>) => void): () => void {
  if (USE_MOCK) {
    const off = subscribe(() => {
      const rec = own(id, employeeNo)
      // 이 화면을 보고 있으니 새 답변 표시는 바로 지운다
      if (rec) {
        rec.inquiry.unread = 0
        onChange(ok(snapshot(rec)))
      }
    })
    return off
  }
  const timer = setInterval(() => {
    request<Inquiry>(`/inquiries/${encodeURIComponent(id)}`).then(onChange)
  }, POLL_MS)
  return () => clearInterval(timer)
}

export function sendChat(id: number, employeeNo: string, text: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) {
    return mockAct(id, employeeNo, (rec) => {
      // 접수 이후에는 담당자에게 가는 메시지이고, 답변을 준비하는 중에는 새 메시지를 받지 않는다
      if (rec.inquiry.ticket) sendToStaff(rec, text)
      else if (rec.inquiry.step !== 'answering' && rec.inquiry.step !== 'closed') handle(rec, text, false)
    })
  }
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/messages`, { text })
}

export function replyChat(id: number, employeeNo: string, req: ReplyRequest): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => applyReply(rec, req))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/replies`, req)
}

export function editDraft(id: number, employeeNo: string, edit: DraftEdit): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => saveDraft(rec, edit))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/draft/edit`, edit)
}

export function confirmChatDraft(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => confirmDraft(rec))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/draft/confirm`)
}

export function cancelChatDraft(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => cancelDraft(rec))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/draft/cancel`)
}

export function resolveChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => confirmResolved(rec))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/resolve`)
}

export function rejectChat(id: number, employeeNo: string, reason: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => denyResolved(rec, reason))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/reject`, { reason })
}

export function reopenChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => reopenInquiry(rec))
  return post<Inquiry>(`/inquiries/${encodeURIComponent(id)}/reopen`)
}

/** 시연 전용: 응답 없이 시간이 지난 상황 (실제 서버에서는 서버가 정해진 시간 후 처리한다) */
/** 시연: 종료 10분 전 안내를 보낸다 (실제로는 서버가 보내는 시스템 메시지) */
export function idleWarnChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  return mockAct(id, employeeNo, (rec) => idleWarnInquiry(rec))
}

export function timeoutChat(id: number, employeeNo: string, messageId: number): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => timeoutInquiry(rec, messageId))
  return Promise.resolve(fail('NOT_SUPPORTED', '시연 전용 기능이에요.'))
}

/** 시연 전용: 담당자 처리를 한 단계 앞으로 보낸다 */
export function advanceChat(id: number, employeeNo: string): Promise<ApiResult<Inquiry>> {
  if (USE_MOCK) return mockAct(id, employeeNo, (rec) => advanceTicket(rec))
  return Promise.resolve(fail('NOT_SUPPORTED', '시연 전용 기능이에요.'))
}
