/**
 * 내 글만 저장되고 AI 답이 아직 없을 때: 방금 보냈으면 "답하는 중", 오래됐으면 "답하지 못함".
 */
import { describe, expect, it } from 'vitest'
import { AI_WAIT_MS, isAnswering, toInquiry } from '../src/api/inquiryServer'

const at = (msAgo: number) => new Date(Date.now() - msAgo).toISOString()
const inquiry = (over: Record<string, unknown> = {}) =>
  ({ id: 7, status: 'IN_PROGRESS', title: null, categoryCode: null, ticket: null, activeDraftId: null, displayStatus: 'in_progress', action: 'ASK_MORE', resolutionResult: null, createdAt: at(600_000), updatedAt: at(1000), ...over }) as never
const msg = (id: number, sender: 'USER' | 'AI', msAgo: number) => ({ id, sender, content: `글 ${id}`, createdAt: at(msAgo), sources: [] }) as never

describe('AI 답변을 기다리는 중 판단', () => {
  it('방금 보낸 글에 답이 없으면 답하는 중이다 (준비 중 표시, 입력 잠금)', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000), msg(3, 'USER', 20_000)]
    expect(isAnswering(inquiry(), list)).toBe(true)
    const i = toInquiry(inquiry(), list)
    expect(i.step).toBe('answering')
    expect(i.messages[i.messages.length - 1]).toMatchObject({ role: 'assistant', typing: { label: '답변을 준비하고 있어요' } })
    expect(i.messages.some((m) => m.replies)).toBe(false)
  })

  it('오래 지났는데도 답이 없으면 답하지 못한 것으로 보고 담당자 연결을 제안한다', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000), msg(3, 'USER', AI_WAIT_MS + 10_000)]
    expect(isAnswering(inquiry(), list)).toBe(false)
    const i = toInquiry(inquiry(), list)
    expect(i.step).toBe('offer')
    expect(JSON.stringify(i.messages[i.messages.length - 1])).toContain('지금은 답변을 만들지 못했어요')
  })

  it('AI 답이 마지막이거나 접수된 문의는 답하는 중이 아니다', () => {
    expect(isAnswering(inquiry(), [msg(1, 'USER', 5000), msg(2, 'AI', 1000)])).toBe(false)
    expect(isAnswering(inquiry({ ticket: { id: 1 } }), [msg(1, 'USER', 5000)])).toBe(false)
    expect(isAnswering(inquiry({ status: 'CLOSED_UNRESOLVED' }), [msg(1, 'USER', 5000)])).toBe(false)
  })
})

describe('접수 없이 끝낸 문의 (담당자 연결 거절)', () => {
  it('서버는 종료 안내 글을 저장하지 않으므로 화면이 종료 안내를 붙인다', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000)]
    const i = toInquiry(inquiry({ status: 'CLOSED_UNRESOLVED', action: 'ESCALATE' }), list)
    expect(i.step).toBe('closed')
    expect(JSON.stringify(i.messages[i.messages.length - 1])).toContain('담당자 연결 없이 상담을 종료했어요')
    // 내가 누른 "미연결 (종료)"가 말풍선으로 먼저 보이고 그 다음에 종료 안내가 이어진다
    const n = i.messages.length
    expect(i.messages[n - 2]).toMatchObject({ role: 'user', text: '미연결 (종료)' })
  })

  it('접수된 문의나 진행 중인 문의에는 붙이지 않는다', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000)]
    expect(JSON.stringify(toInquiry(inquiry(), list).messages)).not.toContain('상담을 종료했어요')
    expect(JSON.stringify(toInquiry(inquiry({ status: 'CLOSED_UNRESOLVED', ticket: { id: 1, receiptNo: 'R', jiraKey: null, workStatus: 'RDY', createdAt: at(1000) } }), list).messages)).not.toContain('상담을 종료했어요')
  })
})

describe('내가 누른 해결·미해결 (서버는 말풍선과 안내를 저장하지 않는다)', () => {
  const sys = (id: number, text: string, msAgo: number) => ({ id, sender: 'SYSTEM', content: text, createdAt: at(msAgo), sources: [] }) as never

  it('해결: 내 "해결" 말풍선과 AI 해결 안내가 보이고, 서버의 시스템 안내 한 줄은 겹쳐서 뺀다', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000), sys(3, '해결로 종료되었습니다.', 5000)]
    const i = toInquiry(inquiry({ status: 'AI_RESOLVED', resolutionResult: 'RESOLVED', displayStatus: 'ai_resolved' }), list)
    const text = JSON.stringify(i.messages)
    expect(text).not.toContain('해결로 종료되었습니다.')
    expect(i.messages[i.messages.length - 2]).toMatchObject({ role: 'user', text: '해결' })
    expect(JSON.stringify(i.messages[i.messages.length - 1])).toContain('AI 안내로 문제가 해결되었군요')
    expect(i.step).toBe('closed')
  })

  it('미해결: 내 "미해결" 말풍선과 안내가 보이고, 안내 아래에 담당자 연결 버튼이 붙는다', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000)]
    const i = toInquiry(inquiry({ resolutionResult: 'UNRESOLVED' }), list, ['DECIDE_HANDOFF'])
    expect(i.step).toBe('offer')
    expect(i.messages[i.messages.length - 2]).toMatchObject({ role: 'user', text: '미해결' })
    const last = i.messages[i.messages.length - 1]
    expect(JSON.stringify(last)).toContain('아직 문제가 해결되지 않았군요')
    expect(last.replies?.map((r) => r.action)).toEqual(['connect-yes', 'connect-no'])
  })

  it('미해결 뒤 연결을 거절하면 대화가 차례대로 이어진다 (미해결 → 안내 → 미연결 → 종료 안내)', () => {
    const list = [msg(1, 'USER', 90_000), msg(2, 'AI', 80_000)]
    const i = toInquiry(inquiry({ status: 'CLOSED_UNRESOLVED', resolutionResult: 'UNRESOLVED' }), list)
    expect(i.messages.slice(2).map((m) => (m.role === 'user' ? `나:${m.text}` : '안내'))).toEqual(['나:미해결', '안내', '나:미연결 (종료)', '안내'])
    expect(i.messages.some((m) => m.replies)).toBe(false)
  })
})
