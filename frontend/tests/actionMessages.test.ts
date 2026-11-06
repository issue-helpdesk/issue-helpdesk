/**
 * R-29: 서버가 문의자의 선택(CHOICE)과 카드(DRAFT_CARD·TICKET_CARD)를 대화 메시지로 저장한다.
 * 화면은 저장된 순서대로 말풍선·카드를 만들고(문구는 code 로 정한다), 상태로 다시 만들던 옛 방식은 kind 가 있을 때 쓰지 않는다.
 */
import { describe, expect, it } from 'vitest'
import { toInquiry } from '../src/api/inquiryServer'

const at = (n: number) => new Date(Date.UTC(2026, 10, 5, 1, n)).toISOString()
const inquiry = (over: Record<string, unknown> = {}) =>
  ({ id: 7, status: 'HANDED_OFF', title: '화상회의 프로그램 설치', categoryCode: 'SW', ticket: { id: 11, receiptNo: 'RCPT-0011', jiraKey: 'ITHD-376', workStatus: 'RDY' }, activeDraftId: null, displayStatus: 'received', action: 'ESCALATE', resolutionResult: 'UNRESOLVED', recommendedGroup: null, createdAt: at(0), updatedAt: at(9), ...over }) as never
let n = 0
const m = (sender: 'USER' | 'AI' | 'SYSTEM', kind: string, extra: Record<string, unknown> = {}) =>
  ({ id: ++n, sessionId: 1, seq: n, sender, kind, code: null, content: null, sources: [], createdAt: at(n), ...extra }) as never
const draft = (status: string) => ({ id: 5, inquiryId: 7, summary: '화상회의 설치', targetSystem: 'PC', occurredAt: '출장 전', categoryCode: 'SW', inquiryType: null, urgency: 'P4', urgencyReason: null, businessImpact: '외근 시 필요', triedActions: '없음', recommendedGroupId: 1, recommendedGroup: { id: 1, name: '엔드포인트지원팀' }, status, updatedAt: at(4) })

const flow = () => {
  n = 0
  return [
    m('USER', 'TEXT', { content: '화상회의 프로그램 설치가 필요해요' }),
    m('AI', 'TEXT', { content: '소프트웨어 센터에서 설치해 보세요.' }),
    m('USER', 'CHOICE', { code: 'UNRESOLVED' }),
    m('USER', 'CHOICE', { code: 'CONNECT' }),
    m('SYSTEM', 'DRAFT_CARD', { draft: draft('CONFIRMED') }),
    m('USER', 'CHOICE', { code: 'CONFIRM' }),
    m('SYSTEM', 'TICKET_CARD'),
  ]
}

describe('선택·카드를 서버가 메시지로 저장할 때 (R-29)', () => {
  it('저장된 순서대로 말풍선과 카드가 보이고, 접수 뒤에도 초안 카드·내 선택이 남는다', () => {
    const i = toInquiry(inquiry(), flow(), undefined, null, null, '', true)
    const kinds = i.messages.map((x) => (x.card ? `card:${x.card}` : `${x.role}:${x.text ?? ''}`.slice(0, 24)))
    expect(kinds).toContain('user:미해결')
    expect(kinds).toContain('user:담당자 연결')
    expect(kinds).toContain('card:draft')
    expect(kinds).toContain('user:접수하기')
    expect(kinds).toContain('card:ticket')
    // 순서: 접수하기 → 진행 카드, 담당자 연결 → 초안 카드
    expect(kinds.indexOf('user:담당자 연결')).toBeLessThan(kinds.indexOf('card:draft'))
    expect(kinds.indexOf('user:접수하기')).toBeLessThan(kinds.indexOf('card:ticket'))
    expect(i.step).toBe('submitted')
  })

  it('두 번 보이지 않는다: 같은 말풍선·카드가 상태에서 한 번 더 만들어지지 않는다', () => {
    const i = toInquiry(inquiry(), flow(), undefined, null, null, '', true)
    expect(i.messages.filter((x) => x.role === 'user' && x.text === '미해결')).toHaveLength(1)
    expect(i.messages.filter((x) => x.card === 'draft')).toHaveLength(1)
    expect(i.messages.filter((x) => x.card === 'ticket')).toHaveLength(1)
    expect(new Set(i.messages.map((x) => x.id)).size).toBe(i.messages.length) // 화면에서 key 가 겹치지 않는다
  })

  it('접수된 초안 카드는 서버가 준 초안으로 읽기 전용(confirmed)이다', () => {
    const i = toInquiry(inquiry(), flow(), undefined, null, null, '', true)
    const card = i.messages.find((x) => x.card === 'draft')!
    expect(card.draft?.summary).toBe('화상회의 설치')
    expect(card.draftState).toBe('confirmed')
  })

  it('접수번호는 문의의 ticket.receiptNo 로 채운다', () => {
    const i = toInquiry(inquiry(), flow(), undefined, null, null, '', true)
    expect(JSON.stringify(i.messages.find((x) => x.card === 'ticket'))).toContain('RCPT-0011')
  })

  it('재확인 요청으로 진행 카드가 여러 개면 마지막만 카드이고 앞의 것은 안내 글만 남는다', () => {
    n = 0
    const list = [...flow(), m('USER', 'CHOICE', { code: 'TICKET_UNRESOLVED' }), m('USER', 'TEXT', { content: '같은 오류가 계속 나요' }), m('SYSTEM', 'TICKET_CARD')]
    const i = toInquiry(inquiry({ ticket: { id: 11, receiptNo: 'RCPT-0011', jiraKey: null, workStatus: 'WIP' } }), list, undefined, null, null, '', true)
    const cards = i.messages.filter((x) => x.card === 'ticket')
    expect(cards).toHaveLength(1)
    expect(i.messages[i.messages.length - 1].card).toBe('ticket')
    expect(JSON.stringify(i.messages[i.messages.length - 1])).toContain('다시 확인을 요청했어요')
  })

  it('내 선택이 마지막이어도 "AI 답을 기다리는 중"이나 "답하지 못함"으로 잘못 보지 않는다 (글만 본다)', () => {
    n = 0
    const list = [m('USER', 'TEXT', { content: '질문' }), m('AI', 'TEXT', { content: '답' }), m('USER', 'CHOICE', { code: 'UNRESOLVED' })]
    const i = toInquiry(inquiry({ status: 'IN_PROGRESS', ticket: null, resolutionResult: 'UNRESOLVED', displayStatus: 'in_progress' }), list, ['DECIDE_HANDOFF'])
    expect(i.step).toBe('offer')
    expect(i.messages.some((x) => x.typing)).toBe(false)
    expect(JSON.stringify(i.messages)).not.toContain('지금은 AI 답변을 만들지 못했어요')
    // 담당자 연결 제안 버튼은 마지막 안내에 붙는다
    expect(i.messages[i.messages.length - 1].replies?.map((r) => r.action)).toEqual(['connect-yes', 'connect-no'])
  })

  it('content 가 null 인 선택 메시지에서도 오류 없이 만들어진다 (제목도 글에서만 만든다)', () => {
    n = 0
    const list = [m('USER', 'CHOICE', { code: 'CONNECT' }), m('USER', 'TEXT', { content: '첫 글' })]
    const i = toInquiry(inquiry({ title: null, ticket: null, status: 'IN_PROGRESS' }), list)
    expect(i.title).toBe('첫 글')
  })

  it('민감정보 안내(NOTICE)는 안내 말풍선(sens)으로 보인다', () => {
    n = 0
    const list = [m('USER', 'TEXT', { content: '비번은 ●●●' }), m('SYSTEM', 'NOTICE', { content: '민감정보가 감지되어 가렸어요.' })]
    const i = toInquiry(inquiry({ ticket: null, status: 'IN_PROGRESS' }), list)
    expect(i.messages.find((x) => x.role === 'sys')).toMatchObject({ tone: 'sens' })
  })

  it('접수 없이 끝내면(접수 안 함·미연결) 내 선택 뒤에 종료 안내가 한 번 붙는다', () => {
    n = 0
    const list = [m('USER', 'TEXT', { content: '질문' }), m('AI', 'TEXT', { content: '답' }), m('USER', 'CHOICE', { code: 'NO_CONNECT' })]
    const i = toInquiry(inquiry({ status: 'CLOSED_UNRESOLVED', ticket: null, resolutionResult: 'UNRESOLVED' }), list)
    expect(i.messages.filter((x) => x.role === 'user' && x.text === '미연결 (종료)')).toHaveLength(1)
    expect(JSON.stringify(i.messages)).toContain('담당자 연결 없이 상담을 종료했어요')
    expect(JSON.stringify(i.messages).match(/담당자 연결 없이 상담을 종료했어요/g)).toHaveLength(1)
  })
})

describe('kind 가 없는 이전 서버 응답', () => {
  it('옛 방식(상태로 다시 만들기)대로 동작한다', () => {
    n = 0
    const old = (id: number, sender: 'USER' | 'AI', content: string) => ({ id, sender, content, sources: [], createdAt: at(id) }) as never
    const i = toInquiry(inquiry({ status: 'AI_RESOLVED', ticket: null, resolutionResult: 'RESOLVED' }), [old(1, 'USER', '질문'), old(2, 'AI', '답')])
    expect(i.messages.some((x) => x.role === 'user' && x.text === '해결')).toBe(true)
  })
})
