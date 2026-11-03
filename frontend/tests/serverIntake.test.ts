/**
 * 서버 접수 흐름 (VITE_SERVER_INTAKE=true): 담당자 연결 → 초안 생성·수정·취소·최종 접수(TK-01·03·04), 접수 이후 해결·미해결(TK-07).
 * 서버는 띄우지 않고 가짜 fetch 로 서버 계약(docs/api/03)대로 응답한다. 플래그가 꺼진 경우는 inquiryApi.test.ts 가 확인한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (status: number, code: string, details: unknown = null) => json(status, { error: { code, message: '서버 문구', details, traceId: 't' } })

const inquiry = (over: Record<string, unknown> = {}) => ({
  id: 128, title: 'VPN 접속 불가', status: 'IN_PROGRESS', displayStatus: 'unresolved', categoryCode: 'NET', urgency: 'P2', action: 'ESCALATE',
  recommendedGroup: { id: 5, name: '네트워크팀' }, resolutionResult: 'UNRESOLVED', activeDraftId: null, ticket: null,
  createdAt: '2026-10-21T10:12:03+09:00', updatedAt: '2026-10-21T10:12:09+09:00', ...over,
})
const msgs = [{ id: 901, sessionId: 1, seq: 1, sender: 'USER', content: 'VPN 이 안 돼요', sources: [], createdAt: '2026-10-21T10:12:03+09:00' }]
const draft = (over: Record<string, unknown> = {}) => ({
  id: 55, inquiryId: 128, summary: 'VPN 접속 불가', targetSystem: 'VPN', occurredAt: '어제', categoryCode: 'NET',
  inquiryType: { id: 21, code: 'NET-01', name: 'VPN 접속 불가' }, urgency: 'P2', urgencyReason: '업무 중단\n재택 중',
  businessImpact: '접속 불가', triedActions: '재설치', recommendedGroupId: 5, recommendedGroup: { id: 5, name: '네트워크팀' },
  status: 'EDITING', updatedAt: '2026-10-21T10:19:12+09:00', ...over,
})
const ticketDetail = (over: Record<string, unknown> = {}) => ({
  id: 42, receiptNo: 'RCPT-0042', jiraKey: null, inquiryId: 128, summary: 'VPN 접속 불가', category: { code: 'NET', name: 'VPN' }, urgency: 'P2',
  group: { id: 5, name: '네트워크팀' }, assignee: null, jiraSyncStatus: 'PENDING', assignStatus: 'PENDING', workStatus: null,
  createdAt: '2026-10-21T10:20:41+09:00', finishedAt: null, closedAt: null, resolutionNote: null, ...over,
})

let fetchMock: ReturnType<typeof vi.fn>
let handlers: Array<(url: string, init: RequestInit) => Response | undefined> = []
const route = (h: (url: string, init: RequestInit) => Response | undefined) => handlers.push(h)
const sent = () => fetchMock.mock.calls.map((c) => ({ url: String(c[0]), init: (c[1] ?? {}) as RequestInit }))
const body = (m: string, suffix: string) => JSON.parse(String(sent().find((c) => c.init.method === m && c.url.endsWith(suffix))!.init.body))

async function load(intake = 'true') {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
  vi.stubEnv('VITE_SERVER_INTAKE', intake)
  return import('../src/api/chat')
}
/** 문의·메시지 조회: 호출 때마다 현재 값을 읽는다 */
const serve = (get: () => { inq: unknown; draft?: unknown; ticket?: unknown }) => {
  route((u) => (u.endsWith('/inquiries/128') ? json(200, get().inq) : undefined))
  route((u) => (u.endsWith('/inquiries/128/messages') ? json(200, { items: msgs }) : undefined))
  route((u) => (u.endsWith('/ticket-drafts/55') ? json(200, get().draft) : undefined))
  route((u) => (u.endsWith('/tickets/42') ? json(200, get().ticket) : undefined))
}

beforeEach(() => {
  handlers = []
  fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    for (const h of handlers) {
      const r = h(String(url), init)
      if (r) return r
    }
    return err(404, 'NOT_MOCKED', [{ reason: String(url) }])
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('초안 만들기·고치기·취소', () => {
  it('담당자 연결을 누르면 초안을 만들고, 초안 단계와 초안 카드로 보여 준다', async () => {
    const chat = await load()
    let created = false
    route((u, i) => (u.endsWith('/inquiries/128/ticket-drafts') && i.method === 'POST' ? ((created = true), json(201, draft())) : undefined))
    serve(() => ({ inq: inquiry({ activeDraftId: created ? 55 : null }), draft: draft() }))

    const r = await chat.replyChat(128, 'EMP', { messageId: 1, action: 'connect-yes' })
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data.step).toBe('draft')
    expect(r.data.draft).toMatchObject({ summary: 'VPN 접속 불가', urgency: 'P2', groupName: '네트워크팀', inquiryTypeCode: 'NET-01', urgencyReasons: ['업무 중단', '재택 중'] })
    expect(r.data.messages.at(-1)).toMatchObject({ card: 'draft' })
  })

  it('이미 작성 중인 초안이 있으면(409) 그 초안을 연다', async () => {
    const chat = await load()
    route((u, i) => (u.endsWith('/ticket-drafts') && i.method === 'POST' ? err(409, 'DRAFT_ALREADY_EXISTS', [{ reason: 'DRAFT_ID', value: 55 }]) : undefined))
    serve(() => ({ inq: inquiry({ activeDraftId: 55 }), draft: draft() }))
    const r = await chat.replyChat(128, 'EMP', { messageId: 1, action: 'connect-yes' })
    expect(r).toMatchObject({ ok: true, data: { step: 'draft' } })
  })

  it('초안을 고치면 보낸 칸만 서버로 보내고, 다시 판단된 항목과 가린 안내를 화면에 남긴다', async () => {
    const chat = await load()
    let updatedAt = '2026-10-21T10:19:12+09:00'
    route((u, i) => (u.endsWith('/ticket-drafts/55') && i.method === 'PATCH'
      ? ((updatedAt = '2026-10-21T10:25:00+09:00'), json(200, { draft: draft({ urgency: 'P1', updatedAt }), changes: [{ field: 'urgency', before: 'P2', after: 'P1', reason: '오늘 마감' }], maskNotice: '민감정보를 가렸어요\n비밀번호는 저장하지 않아요' }))
      : undefined))
    serve(() => ({ inq: inquiry({ activeDraftId: 55 }), draft: draft({ urgency: 'P1', updatedAt }) }))
    await chat.getChat(128, 'EMP')

    const r = await chat.editDraft(128, 'EMP', { summary: ' 새 요약 ', occurredAt: '', businessImpact: '오늘 마감', triedActions: '   ' })
    expect(body('PATCH', '/ticket-drafts/55')).toEqual({ summary: '새 요약', businessImpact: '오늘 마감' }) // 빈 칸은 보내지 않는다
    expect(r).toMatchObject({ ok: true, data: { draft: { urgency: 'P1', rejudged: ['urgency'] } } })
    if (r.ok) {
      expect(r.data.draftNote).toContain('오늘 마감')
      expect(r.data.draftNote).toContain('민감정보를 가렸어요 비밀번호는 저장하지 않아요')
    }
  })

  it('접수 안 함은 초안을 취소(CANCELLED)하고 종료된 문의를 돌려준다', async () => {
    const chat = await load()
    let cancelled = false
    route((u, i) => (u.endsWith('/ticket-drafts/55') && i.method === 'PATCH' ? ((cancelled = true), json(200, { draft: draft({ status: 'CANCELLED' }), changes: [], maskNotice: null })) : undefined))
    serve(() => ({ inq: cancelled ? inquiry({ status: 'CLOSED_UNRESOLVED', activeDraftId: null }) : inquiry({ activeDraftId: 55 }), draft: draft() }))
    await chat.getChat(128, 'EMP')
    const r = await chat.cancelChatDraft(128, 'EMP')
    expect(body('PATCH', '/ticket-drafts/55')).toEqual({ status: 'CANCELLED' })
    expect(r).toMatchObject({ ok: true, data: { step: 'closed', status: 'CLOSED_UNRESOLVED' } })
  })
})

describe('최종 접수', () => {
  it('사용자가 본 초안의 id 와 수정 시각을 보내고, 접수되면 접수 카드와 접수 id 를 담는다', async () => {
    const chat = await load()
    let confirmed = false
    route((u, i) => (u.endsWith('/tickets') && i.method === 'POST' ? ((confirmed = true), json(201, { id: 42, receiptNo: 'RCPT-0042' })) : undefined))
    serve(() => ({ inq: confirmed ? inquiry({ status: 'RECEIVED', activeDraftId: null, ticket: { id: 42, receiptNo: 'RCPT-0042', jiraKey: null, workStatus: null } }) : inquiry({ activeDraftId: 55 }), draft: draft(), ticket: ticketDetail() }))
    await chat.getChat(128, 'EMP')

    const r = await chat.confirmChatDraft(128, 'EMP')
    expect(body('POST', '/tickets')).toEqual({ draftId: 55, draftUpdatedAt: '2026-10-21T10:19:12+09:00' })
    expect(r).toMatchObject({ ok: true, data: { step: 'submitted', ticket: { id: 42, receiptNo: 'RCPT-0042' } } })
    if (r.ok) expect(r.data.messages.at(-1)).toMatchObject({ card: 'ticket' })
  })

  it('다른 화면에서 초안이 바뀌어 거절되면(409) 오류를 돌려주고 최신 초안으로 화면을 다시 맞춘다', async () => {
    const chat = await load()
    route((u, i) => (u.endsWith('/tickets') && i.method === 'POST' ? err(409, 'DRAFT_RECONFIRM_REQUIRED') : undefined))
    serve(() => ({ inq: inquiry({ activeDraftId: 55 }), draft: draft({ updatedAt: '2026-10-21T10:21:00+09:00' }) }))
    const seen: unknown[] = []
    const off = chat.watchChat(128, 'EMP', (x) => seen.push(x))
    await chat.getChat(128, 'EMP')
    seen.length = 0 // 접수 요청 이후에 화면으로 간 갱신만 센다

    expect(await chat.confirmChatDraft(128, 'EMP')).toMatchObject({ ok: false, error: { code: 'DRAFT_RECONFIRM_REQUIRED' } })
    await vi.waitFor(() => expect(seen).toHaveLength(1))
    expect(seen[0]).toMatchObject({ ok: true, data: { step: 'draft' } })
    off()
  })
})

describe('접수 이후 해결·미해결', () => {
  const received = () => inquiry({ status: 'RECEIVED', ticket: { id: 42, receiptNo: 'RCPT-0042', jiraKey: 'ITHD-7', workStatus: 'FIN' } })

  it('해결은 workStatus=CLS, 미해결은 WIP 와 남은 증상을 접수 id 로 보낸다', async () => {
    const chat = await load()
    route((u, i) => (u.endsWith('/tickets/42') && i.method === 'PATCH' ? json(202, ticketDetail()) : undefined))
    serve(() => ({ inq: received(), ticket: ticketDetail({ workStatus: 'FIN' }) }))
    await chat.getChat(128, 'EMP') // 접수 id 를 알아 둔다

    await chat.resolveChat(128, 'EMP')
    expect(body('PATCH', '/tickets/42')).toEqual({ workStatus: 'CLS' })
    await chat.rejectChat(128, 'EMP', '아직 접속이 안 돼요')
    const bodies = sent().filter((c) => c.init.method === 'PATCH').map((c) => JSON.parse(String(c.init.body)))
    expect(bodies[1]).toEqual({ workStatus: 'WIP', reason: '아직 접속이 안 돼요' })
  })

  it('문의를 읽은 적이 없어 접수 id 를 모르면 서버로 보내지 않는다', async () => {
    const chat = await load()
    expect(await chat.resolveChat(128, 'EMP')).toMatchObject({ ok: false, error: { code: 'TICKET_NOT_FOUND' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('플래그가 꺼져 있으면', () => {
  it('초안을 읽지도 않고 연결 제안 단계를 그대로 둔다', async () => {
    const chat = await load('')
    serve(() => ({ inq: inquiry({ activeDraftId: 55 }), draft: draft() }))
    const r = await chat.getChat(128, 'EMP')
    expect(r).toMatchObject({ ok: true, data: { step: 'offer', draft: null } })
    expect(sent().some((c) => c.url.includes('/ticket-drafts/'))).toBe(false)
  })
})
