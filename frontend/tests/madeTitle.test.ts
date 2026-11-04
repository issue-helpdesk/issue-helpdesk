/**
 * 서버가 제목을 정하지 못한 문의(title null): 대화 화면이 첫 메시지로 만든 제목을 목록도 같이 쓴다.
 */
import { describe, expect, it } from 'vitest'
import { toInquiry, toServerSummary } from '../src/api/inquiryServer'

const inq = (over: Record<string, unknown> = {}) =>
  ({ id: 77, userId: 1, title: null, status: 'IN_PROGRESS', displayStatus: 'in_progress', categoryCode: null, urgency: null, action: null, resolutionResult: null, ticket: null, activeDraftId: null, createdAt: '2026-11-04T10:00:00+09:00', updatedAt: null, ...over }) as never
const msg = (content: string) => ({ id: 1, sessionId: 1, seq: 1, sender: 'USER', content, sources: [], createdAt: '2026-11-04T10:00:00+09:00' }) as never
const summary = (over: Record<string, unknown> = {}) => ({ id: 77, title: null, displayStatus: 'unresolved', category: null, receiptNo: null, createdAt: '2026-11-04T10:00:00+09:00', updatedAt: null, ...over }) as never

describe('제목이 없는 문의의 목록 제목', () => {
  it('대화 화면이 만든 제목을 목록에서도 쓰고, 본 적 없는 문의는 새 문의로 둔다', () => {
    expect(toServerSummary(summary({ id: 78 })).title).toBe('새 문의')
    const t = toInquiry(inq(), [msg('전자결재 접속이 안 돼요. 나만 안되는 것 같아 방금 전부터 안되기 시작했어요.')])
    expect(t.title).toBe('전자결재 접속이 안 돼요. 나만 안되는 것 같아 방금')
    expect(toServerSummary(summary()).title).toBe(t.title)
  })

  it('서버가 제목을 주면 그대로 쓴다', () => {
    toInquiry(inq({ id: 79 }), [msg('첫 메시지')])
    expect(toServerSummary(summary({ id: 79, title: '서버 제목' })).title).toBe('서버 제목')
  })
})
