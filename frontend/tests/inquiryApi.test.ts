/**
 * 실제 서버 모드(VITE_USE_MOCK_INQUIRY=false) 문의 대화 API 테스트 (docs/api/02 IQ-01~09).
 * 서버는 띄우지 않고 가짜 fetch 로 서버 계약대로 응답을 만들어 준다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (status: number, code: string, details: unknown = null) => json(status, { error: { code, message: '서버 문구', details, traceId: 't' } })

const inquiry = (over: Record<string, unknown> = {}) => ({
  id: 128,
  title: '업데이트 이후 VPN 접속 불가',
  status: 'IN_PROGRESS',
  displayStatus: 'in_progress',
  categoryCode: 'NET',
  urgency: 'P2',
  action: 'ASK_MORE',
  recommendedGroup: { id: 5, name: '네트워크팀' },
  resolutionResult: null,
  activeDraftId: null,
  ticket: null,
  createdAt: '2026-10-21T10:12:03+09:00',
  updatedAt: '2026-10-21T10:12:09+09:00',
  ...over,
})
const msg = (id: number, sender: string, content: string, sources: unknown[] = []) => ({ id, sessionId: 140, seq: id, sender, content, sources, createdAt: '2026-10-21T10:12:03+09:00' })
const DOC = { id: 77, sourceKind: 'DOCUMENT', docCode: 'IT-NET-001', version: 'v1.2', location: '3.2', excerpt: '3.2 업데이트 후 접속 불가', rank: 1 }
const LEGACY = { id: 78, sourceKind: 'LEGACY', docCode: null, version: null, location: null, excerpt: '재설치 후 정상 접속 확인', rank: 2 }

let fetchMock: ReturnType<typeof vi.fn>
type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined
let handlers: Handler[] = []

/** 요청을 순서대로 핸들러에 물어 처음 응답을 주는 것으로 답한다 */
const route = (h: Handler) => handlers.push(h)
const sent = () => fetchMock.mock.calls.map((c) => ({ url: String(c[0]), init: (c[1] ?? {}) as RequestInit }))
const idem = (init: RequestInit) => new Headers(init.headers).get('Idempotency-Key')

async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
  return { chat: await import('../src/api/chat'), list: await import('../src/api/inquiries'), srv: await import('../src/api/inquiryServer') }
}

beforeEach(() => {
  handlers = []
  fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    for (const h of handlers) {
      const r = await h(String(url), init)
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

/** 문의 한 건을 읽는 두 요청(문의·메시지)에 답한다 */
const serve = (inq: unknown, messages: unknown[]) => {
  route((u) => (u.endsWith('/inquiries/128') ? json(200, inq) : undefined))
  route((u) => (u.endsWith('/inquiries/128/messages') && !u.includes('?') ? json(200, { items: messages }) : undefined))
}

describe('서버 모드 문의 시작·읽기', () => {
  it('새 문의는 Idempotency-Key 와 함께 보내고, 답변은 문단·번호 목록과 출처로 바꾼다', async () => {
    const { chat } = await load()
    const text = '어제 업데이트 이후 VPN 이 안 돼요.'
    const ai = msg(902, 'AI', '다음을 확인해 주세요.\n\n1. 클라이언트를 다시 설치해요.\n2. PC 를 재부팅해요.\n\n그래도 안 되면 알려 주세요.', [DOC, LEGACY])
    route((u, i) => (u.endsWith('/inquiries') && i.method === 'POST' ? json(201, { inquiry: inquiry({ displayStatus: 'unconfirmed', action: 'ANSWER' }), messages: [msg(901, 'USER', text), ai], assessment: null, nextActions: ['CONFIRM_RESOLUTION'] }) : undefined))
    serve(inquiry({ displayStatus: 'unconfirmed', action: 'ANSWER' }), [msg(901, 'USER', text), ai])

    const r = await chat.startChat({ employeeNo: 'EMP-1300', name: '최지혜' }, text)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(JSON.parse(String(sent()[0].init.body))).toEqual({ content: text })
    expect(idem(sent()[0].init)).toMatch(/^[0-9a-f-]{36}$/)
    expect(r.data).toMatchObject({ id: 128, title: '업데이트 이후 VPN 접속 불가', status: 'IN_PROGRESS', step: 'answered', unread: 0, ticket: null, draft: null })
    expect(r.data.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
    const a = r.data.messages[1]
    expect(a.blocks).toEqual([{ type: 'p', text: '다음을 확인해 주세요.' }, { type: 'ol', items: ['클라이언트를 다시 설치해요.', 'PC 를 재부팅해요.'] }, { type: 'p', text: '그래도 안 되면 알려 주세요.' }])
    expect(a.sources).toEqual([{ docCode: 'IT-NET-001', title: '', version: 'v1.2', section: '3.2', excerpt: '3.2 업데이트 후 접속 불가' }])
    expect(a.legacy).toMatchObject({ title: '과거 처리 사례 참고', solution: '재설치 후 정상 접속 확인' })
    expect(a.replies?.map((x) => x.action)).toEqual(['resolved', 'unresolved']) // 해결·미해결 버튼은 마지막 AI 답변에만
  })

  it('AI 가 답하지 못한 문의(내 글만 있음)는 다시 읽어도 담당자 연결 안내와 버튼을 보여 준다', async () => {
    const { chat } = await load()
    // IQ-01: 문의는 저장됐지만 AI 가 답하지 못함 (모델 파일이 없는 환경 등)
    route((u, i) => (u.endsWith('/inquiries') && i.method === 'POST' ? err(503, 'AI_UNAVAILABLE', [{ reason: 'INQUIRY_ID', message: '저장된 문의', value: 128 }]) : undefined))
    serve(inquiry({ title: null, action: null }), [msg(901, 'USER', '비밀번호를 잊었어요')])
    const first = await chat.startChat({ employeeNo: 'EMP-1300', name: '최지혜' }, '비밀번호를 잊었어요')
    expect(first.ok && first.data.id).toBe(128)
    // 주기적으로 다시 읽을 때(다음 행동 정보 없음)에도 같은 안내가 유지된다
    const again = await chat.getChat(128, 'EMP-1300')
    expect(again.ok && again.data.step).toBe('offer')
    const last = again.ok ? again.data.messages[again.data.messages.length - 1] : undefined
    expect(last).toMatchObject({ role: 'assistant' })
    expect(last?.replies?.map((r) => r.action)).toEqual(['connect-yes', 'connect-no'])
    expect(again.ok && again.data.title).toBe('비밀번호를 잊었어요')
  })

  it('조회에서는 문의 상태로 단계를 정하고, 접수가 있으면 접수 상세로 카드를 채운다', async () => {
    const { chat } = await load()
    const t = { id: 42, receiptNo: 'RCPT-0042', jiraKey: null, workStatus: null }
    serve(inquiry({ status: 'RECEIVED', displayStatus: 'received', ticket: t }), [msg(901, 'USER', '안녕')])
    route((u) => (u.endsWith('/tickets/42') ? json(200, { id: 42, receiptNo: 'RCPT-0042', jiraKey: null, summary: '접수 요약', category: { code: 'NET', name: 'VPN' }, urgency: 'P2', group: { id: 5, name: '네트워크팀' }, assignee: null, jiraSyncStatus: 'PENDING', assignStatus: 'PENDING', workStatus: null, createdAt: '2026-10-21T10:20:00+09:00', resolutionNote: null, finishedAt: null, closedAt: null }) : undefined))
    const r = await chat.getChat(128, 'EMP-1300')
    expect(r.ok && r.data.step).toBe('submitted')
    expect(r.ok && r.data.ticket).toMatchObject({ receiptNo: 'RCPT-0042', jiraSyncStatus: 'PENDING', groupName: '네트워크팀', workStatus: null })
  })

  it('없는 문의는 서버 오류 코드를 그대로 돌려준다', async () => {
    const { chat } = await load()
    route((u) => (u.endsWith('/inquiries/9') ? err(404, 'INQUIRY_NOT_FOUND') : undefined))
    route((u) => (u.includes('/inquiries/9/messages') ? err(404, 'INQUIRY_NOT_FOUND') : undefined))
    expect(await chat.getChat(9, 'EMP-1300')).toMatchObject({ ok: false, error: { code: 'INQUIRY_NOT_FOUND' } })
  })
})

describe('서버 모드 메시지·해결 확인·종료', () => {
  it('AI 가 답하지 못하면(503) 저장된 문의를 열고 담당자 연결 단계로 안내한다', async () => {
    const { chat } = await load()
    route((u, i) => (u.endsWith('/inquiries/128/messages') && i.method === 'POST' ? err(503, 'AI_UNAVAILABLE', [{ reason: 'MESSAGE_ID', message: '저장된 메시지', value: 905 }]) : undefined))
    serve(inquiry({ action: 'ESCALATE' }), [msg(901, 'USER', '도와 주세요'), msg(905, 'USER', '오류가 나요')])
    const r = await chat.sendChat(128, 'EMP-1300', '오류가 나요')
    expect(r.ok && r.data.step).toBe('offer')
  })

  it('해결·미해결은 IQ-09, 연결 거절은 IQ-04 로 보내고, 접수 초안은 아직 연결하지 않았다고 알린다', async () => {
    const { chat } = await load()
    route((u, i) => (u.endsWith('/resolution') && i.method === 'PUT' ? json(200, { inquiry: inquiry({ status: 'AI_RESOLVED', displayStatus: 'ai_resolved' }), messages: [], assessment: null, nextActions: ['START_NEW'] }) : undefined))
    route((u, i) => (u.endsWith('/inquiries/128') && i.method === 'PATCH' ? json(200, inquiry({ status: 'CLOSED_UNRESOLVED', displayStatus: 'unresolved' })) : undefined))
    serve(inquiry({ status: 'AI_RESOLVED', displayStatus: 'ai_resolved' }), [msg(901, 'USER', '안녕')])

    const a = await chat.replyChat(128, 'EMP-1300', { messageId: 1, action: 'resolved' })
    expect(a.ok && a.data.step).toBe('closed')
    const put = sent().find((c) => c.init.method === 'PUT')!
    expect(JSON.parse(String(put.init.body))).toEqual({ resolutionResult: 'RESOLVED' })
    expect(idem(put.init)).toBeTruthy()

    await chat.replyChat(128, 'EMP-1300', { messageId: 1, action: 'connect-no' })
    expect(JSON.parse(String(sent().find((c) => c.init.method === 'PATCH')!.init.body))).toEqual({ status: 'CLOSED_UNRESOLVED' })

    expect(await chat.replyChat(128, 'EMP-1300', { messageId: 1, action: 'connect-yes' })).toMatchObject({ ok: false, error: { code: 'NOT_READY' } })
  })

  it('Jira 연동 전에는 접수 초안·최종 접수·접수 이후 해결 확인을 서버로 보내지 않는다', async () => {
    const { chat } = await load()
    const results = await Promise.all([
      chat.replyChat(128, 'EMP-1300', { messageId: 1, action: 'connect-yes' }),
      chat.editDraft(128, 'EMP-1300', { summary: 'a', businessImpact: 'b', triedActions: 'c' }),
      chat.confirmChatDraft(128, 'EMP-1300'),
      chat.cancelChatDraft(128, 'EMP-1300'),
      chat.resolveChat(128, 'EMP-1300'),
      chat.rejectChat(128, 'EMP-1300', '아직 안 돼요'),
    ])
    for (const r of results) expect(r).toMatchObject({ ok: false, error: { code: 'NOT_READY', message: expect.stringContaining('Jira 연동이 준비된 뒤에') } })
    expect(fetchMock).not.toHaveBeenCalled() // 서버에 아무 요청도 가지 않았다
  })

  it('답을 받지 못해 다시 보내면 같은 Idempotency-Key 를 쓰고, 성공하면 새 글에는 새 키를 쓴다', async () => {
    const { chat } = await load()
    let n = 0
    route((u, i) => {
      if (!(u.endsWith('/inquiries/128/messages') && i.method === 'POST')) return undefined
      if (++n === 1) throw new TypeError('network') // 서버에 닿지 못함
      return json(201, { inquiry: inquiry(), messages: [], assessment: null, nextActions: ['REPLY'] })
    })
    serve(inquiry(), [msg(901, 'USER', '첫 글')])
    expect(await chat.sendChat(128, 'EMP-1300', '같은 글')).toMatchObject({ ok: false, error: { code: 'NETWORK_ERROR' } })
    await chat.sendChat(128, 'EMP-1300', '같은 글')
    await chat.sendChat(128, 'EMP-1300', '다른 글')
    const keys = sent().filter((c) => c.init.method === 'POST').map((c) => idem(c.init))
    expect(keys[0]).toBe(keys[1])
    expect(keys[2]).not.toBe(keys[1])
  })

  it('이어가기는 세션 이어가기(IQ-06)를 부르고 서버가 준 다음 행동으로 단계를 정한다', async () => {
    const { chat } = await load()
    route((u, i) => (u.endsWith('/inquiries/128/sessions') && i.method === 'POST' ? json(200, { session: { id: 140 }, inquiry: inquiry(), nextActions: ['DECIDE_HANDOFF'] }) : undefined))
    serve(inquiry({ status: 'CLOSED_UNRESOLVED', displayStatus: 'unresolved' }), [msg(901, 'USER', '안녕'), msg(902, 'AI', '연결할까요?')])
    const r = await chat.reopenChat(128, 'EMP-1300')
    expect(r.ok && r.data.step).toBe('closed') // 서버가 닫힌 상태로 주면 닫힘이 우선
    expect(sent()[0].url).toBe('/api/v1/inquiries/128/sessions')
  })
})

describe('서버 모드 문의 목록', () => {
  it('최근 문의와 문의 내역은 Page 를 화면의 요약으로 바꾼다', async () => {
    const { list } = await load()
    const item = { id: 128, user: { id: 1 }, title: null, status: 'RECEIVED', displayStatus: 'awaiting_confirm', category: { code: 'NET', name: 'VPN' }, urgency: 'P2', receiptNo: 'RCPT-0042', createdAt: '2026-10-21T10:12:03+09:00', updatedAt: null }
    route((u) => (u.includes('/inquiries?') ? json(200, { items: [item], page: 1, size: 5, totalCount: 1, totalPages: 1 }) : undefined))
    const r = await list.listMyInquiries('EMP-1300')
    expect(sent()[0].url).toBe('/api/v1/inquiries?size=5&sort=updatedAt,desc')
    expect(r.ok && r.data[0]).toMatchObject({ id: 128, title: '새 문의', displayStatus: 'awaiting_confirm', stateLabel: '해결 확인 대기', categoryCode: 'NET', receiptNo: 'RCPT-0042', unread: 0, updatedAt: '2026-10-21T10:12:03+09:00' })
    const p = await list.listInquiries('EMP-1300', { displayStatus: ['received'], q: 'VPN', page: 2 })
    expect(sent()[1].url).toContain('displayStatus=received')
    expect(p.ok && p.data.items).toHaveLength(1)
  })
})
