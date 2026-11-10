/**
 * 화면 알림 API 어댑터 (NT-01~04). 담당자 배정(ASSIGNED, 담당자에게)과 처리 완료(FIN, 문의자에게)를 알린다.
 *
 *   GET  /notifications                 NT-01 내 알림 목록
 *   GET  /notifications/unread-count    NT-02 안 읽은 개수 ({count, ticketIds})
 *   POST /notifications/read            NT-04 접수 단위 읽음 (접수 상세를 열 때)
 *
 * 서버가 알림을 밀어 주는 방법(푸시)은 아직 없어서, 가벼운 개수 조회(NT-02)를 가끔 읽고 값이 바뀔 때만 화면을 갱신한다.
 * 모의 모드에서는 알림이 없다(모의는 문의의 unread·접수의 jiraMention 으로 같은 표시를 한다).
 */
import { request } from '../core/apiClient'
import { USE_MOCK_NOTIFY } from '../core/config'
import { createSharedPoll } from '../core/sharedPoll'
import { ok, type ApiResult } from './types'

interface UnreadCount {
  count: number
  ticketIds: number[]
}

export interface AppNotification {
  id: number
  kind: 'ASSIGNED' | 'FIN'
  ticketId: number
  inquiryId: number
  receiptNo: string
  summary: string | null
  readAt: string | null
  createdAt: string
}

/** 안 읽은 개수와 알림이 있는 접수 번호 (NT-02) */
export async function getUnreadCount(): Promise<ApiResult<UnreadCount>> {
  if (USE_MOCK_NOTIFY) return ok({ count: 0, ticketIds: [] })
  return request<UnreadCount>('/notifications/unread-count')
}

/** 안 읽은 알림 목록 (NT-01). 사이드바는 어느 문의에 새 소식이 있는지 알려고 쓴다 */
export async function listUnread(): Promise<ApiResult<AppNotification[]>> {
  if (USE_MOCK_NOTIFY) return ok([])
  const items: AppNotification[] = []
  // 알림이 많아도 최근 문의의 새 답변 표시가 누락되지 않게 마지막 페이지까지 읽는다.
  for (let page = 1; ; page++) {
    const r = await request<{ items: AppNotification[]; totalPages?: number }>(`/notifications?unreadOnly=true&size=100&page=${page}`)
    if (!r.ok) return r
    items.push(...r.data.items)
    if (page >= (r.data.totalPages ?? 1)) break
  }
  return ok(items)
}

/** 알림 목록 한 쪽 (NT-01, 최신순). unreadOnly 면 안 읽은 알림만. 모의 모드에서는 알림이 없다 */
export async function listNotifications(unreadOnly: boolean, page = 1, size = 20): Promise<ApiResult<{ items: AppNotification[]; hasMore: boolean }>> {
  if (USE_MOCK_NOTIFY) return ok({ items: [], hasMore: false })
  const r = await request<{ items: AppNotification[]; page?: number; totalPages?: number }>(`/notifications?${unreadOnly ? 'unreadOnly=true&' : ''}page=${page}&size=${size}`)
  return r.ok ? ok({ items: r.data.items, hasMore: page < (r.data.totalPages ?? 1) }) : r
}

/** 그 접수의 내 알림을 읽음으로 바꾼다 (NT-04). 접수 상세를 열 때 부른다 */
export async function markTicketRead(ticketId: number): Promise<ApiResult<{ updatedCount: number }>> {
  if (USE_MOCK_NOTIFY) return ok({ updatedCount: 0 })
  return request<{ updatedCount: number }>('/notifications/read', { method: 'POST', body: JSON.stringify({ ticketId }) })
}

const unread = createSharedPoll<UnreadCount>(async () => {
  const result = await getUnreadCount()
  return result.ok ? result.data : null
}, 60_000, (a, b) => a.count === b.count && [...a.ticketIds].sort().join(',') === [...b.ticketIds].sort().join(','))

/** 안 읽은 개수를 다시 읽게 한다 (읽음 처리 직후 등) */
export const refreshUnread = () => unread.refresh()

/** 안 읽은 개수가 바뀔 때마다 알려 준다. 처음 한 번 읽어서 알리고, 이후는 1분마다 읽되 값이 같으면 알리지 않는다 */
export function watchUnread(onChange: (c: UnreadCount) => void, ms = 60_000): () => void {
  if (USE_MOCK_NOTIFY) return () => {}
  return unread.watch(onChange, ms)
}
