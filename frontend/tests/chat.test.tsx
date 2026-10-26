/**
 * 문의 대화 테스트: 대화 엔진 규칙(분류·긴급도·검색 순서) · 접수 흐름 · 대화 화면.
 * 가짜 응답(mock)으로만 실행하며, 시연용 지연은 tests/setup.ts 에서 없앤다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { listMyInquiries } from '../src/api/inquiries'
import { advanceChat, isStaleInquiry, cancelChatDraft, confirmChatDraft, editDraft, getChat, reopenChat, rejectChat, replyChat, resolveChat, sendChat, startChat, idleBackChat, idleDeleteChat, idleWarnChat, resumeChat } from '../src/api/chat'
import type { Inquiry } from '../src/api/chatTypes'
import { calcUrgency, detectCategory } from '../src/api/mock/chatEngine'
import { mockConfig } from '../src/api/mock/chatStore'
import type { ApiResult } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const USER = { employeeNo: 'EMP-1003', name: '박민수' }

/** 예약된 시연 동작(답변 준비, 접수 이후 진행)이 끝나길 기다린다 */
const settle = () => new Promise<void>((r) => setTimeout(r, 30))

/** 결과가 성공이어야 하는 호출의 문의를 꺼낸다 */
async function data(p: Promise<ApiResult<Inquiry>>): Promise<Inquiry> {
  const r = await p
  if (!r.ok) throw new Error(JSON.stringify(r))
  return r.data
}

const get = async (id: number, user = USER.employeeNo) => data(getChat(id, user))

/** 정보를 한 번에 모두 알려 바로 안내가 나오는 VPN 문의 */
const FULL_VPN = 'VPN이 자꾸 끊겨요. 어제부터 안 돼요. 저만 안 되고 메일 업무는 가능해요. 재접속해 봤어요.'

const last = (inq: Inquiry) => inq.messages[inq.messages.length - 1]

/** 가짜 토큰으로 로그인한 상태에서 지정한 주소를 그린다. */
function renderAs(employeeNo: string, path: string) {
  tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('분류와 긴급도 규칙', () => {
  it('문장에서 분류를 짐작하고, 모르면 null 이다', () => {
    expect(detectCategory('VPN이 안 돼요')).toBe('NET')
    expect(detectCategory('계정이 잠겼어요')).toBe('ACC')
    expect(detectCategory('복합기 인쇄가 안 돼요')).toBe('HW')
    expect(detectCategory('피싱 메일 링크를 눌렀어요')).toBe('SEC')
    expect(detectCategory('점심 메뉴 추천해 주세요')).toBeNull()
  })

  it('보안 사고 의심은 최소 P2, 광범위하면 P1 이다', () => {
    expect(calcUrgency('피싱 링크를 눌렀어요').urgency).toBe('P2')
    expect(calcUrgency('피싱 링크를 전 직원이 눌렀어요').urgency).toBe('P1')
  })

  it('여러 사용자의 업무 중단은 P1, 단순 문의는 P4 이다', () => {
    expect(calcUrgency('팀원 30명이 접속 불가예요').urgency).toBe('P1')
    expect(calcUrgency('폴더 권한 신청 방법을 알려 주세요').urgency).toBe('P4')
  })

  it('"급하다"는 말만으로는 긴급도를 올리지 않는다', () => {
    const r = calcUrgency('VPN이 가끔 끊겨요 빨리 해결해 주세요')
    expect(r.urgency).toBe('P3')
    expect(r.urgencyReasons.join(' ')).toContain('상향하지 않음')
  })
})

describe('대화 흐름 (API)', () => {
  it('정보가 부족하면 하나씩 되묻고, 답하면 다음 질문으로 넘어간다', async () => {
    const a = await data(startChat(USER, 'VPN이 끊겨요'))
    const q1 = last(a)
    expect(q1.blocks?.map((b) => (b.type === 'p' ? b.text : '')).join(' ')).toContain('몇 가지만 확인')
    expect(q1.replies?.every((r) => r.action === 'quick')).toBe(true)

    const b = await data(replyChat(a.id, USER.employeeNo, { messageId: q1.id, action: 'quick', arg: q1.replies![0].arg }))
    await settle()
    expect(b.messages.filter((m) => m.role === 'user')).toHaveLength(2)
  })

  it('정보가 모두 모이면 Guide 출처와 함께 안내한다 (Guide 우선)', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const inq = await get(a.id)
    const answer = last(inq)
    expect(answer.sources?.[0]).toMatchObject({ docCode: 'IT-NET-001', version: 'v2', section: '3.1' })
    expect(answer.legacy).toBeUndefined()
    expect(answer.replies?.map((r) => r.action)).toEqual(['resolved', 'unresolved'])
  })

  it('Guide에 없는 증상은 과거 처리 이력을 "참고"로 구분해 보여 준다', async () => {
    const a = await data(startChat(USER, '노트북 화면이 깜빡여요. 오늘 오전부터 그래요. 저만 그렇고 업무는 가능해요. 재부팅해 봤어요.'))
    await settle()
    const answer = last(await get(a.id))
    expect(answer.legacy?.no).toBe('LEG-0132')
    expect(answer.sources).toBeUndefined()
    expect(JSON.stringify(answer.blocks)).toContain('과거 처리 사례 참고')
  })

  it('해결을 누르면 AI 해결로 종료한다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const ans = last(await get(a.id))
    const done = await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'resolved' }))
    expect(done.status).toBe('AI_RESOLVED')
    expect(done.step).toBe('closed')
  })

  it('이미 응답한 버튼은 다시 눌러도 반영되지 않는다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const ans = last(await get(a.id))
    await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'resolved' }))
    const again = await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'unresolved' }))
    expect(again.status).toBe('AI_RESOLVED')
    expect(again.messages.filter((m) => m.role === 'user' && m.text === '미해결')).toHaveLength(0)
  })

  it('보안 사고 의심은 일반 검색 없이 담당자 연결부터 제안한다', async () => {
    const a = await data(startChat(USER, '피싱 메일의 링크를 눌렀어요'))
    const m = last(a)
    expect(m.blocks?.some((b) => b.type === 'urgent' && b.urgency === 'P2' && b.groupName === '정보보안팀')).toBe(true)
    expect(m.replies?.map((r) => r.action)).toEqual(['connect-yes', 'connect-no'])
    expect(m.sources).toBeUndefined()
  })

  it('외부 전송이 제한된 문서 질의는 AI가 답하지 않고 담당자 연결을 제안한다', async () => {
    const a = await data(startChat(USER, '업무용 PC에서 USB 반출 예외 신청을 하고 싶어요. 오늘부터 필요해요. 저만 필요해요. 아직 안 해봤어요.'))
    await settle()
    const ans = last(await get(a.id))
    expect(JSON.stringify(ans.blocks)).toContain('외부 모델로 전송할 수 없는 문서')
    expect(ans.sources).toBeUndefined()
  })

  it('접근권한은 신청 절차만 안내하고 AI가 부여하지 않는다고 알린다', async () => {
    const a = await data(startChat(USER, '공유 폴더 접근권한이 필요해요. 오늘부터 필요해요. 저만 필요해요. 아직 안 해봤어요.'))
    await settle()
    const ans = last(await get(a.id))
    expect(ans.sources?.[0].docCode).toBe('IT-ACS-001')
    expect(JSON.stringify(ans.blocks)).toContain('AI가 대신할 수 없어요')
  })

  it('비밀번호·인증번호로 보이는 값은 가려서 저장한다', async () => {
    const a = await data(startChat(USER, '인증번호는 123456 입니다'))
    const user = a.messages.find((m) => m.role === 'user')!
    expect(user.text).not.toContain('123456')
    expect(a.messages.some((m) => m.role === 'sys' && m.text?.includes('입력하지 마세요'))).toBe(true)
  })

  it('다른 사용자의 문의는 열 수 없다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    const r = await getChat(a.id, 'EMP-1004')
    expect(r.ok).toBe(false)
  })

  it('종료된 상담은 이어가기로 다시 연다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const ans = last(await get(a.id))
    const offer = await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'unresolved' }))
    const closed = await data(replyChat(a.id, USER.employeeNo, { messageId: last(offer).id, action: 'connect-no' }))
    expect(closed.status).toBe('CLOSED_UNRESOLVED')
    expect(closed.step).toBe('closed')
    const reopened = await data(reopenChat(a.id, USER.employeeNo))
    expect(reopened.status).toBe('IN_PROGRESS')
    expect(last(reopened).replies?.map((r) => r.action)).toContain('connect-yes')
  })

  it('답변 뒤 응답이 없으면 5시간 안내를 한 번 보내고, 안내 뒤 대화를 삭제한다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const warned = await data(idleWarnChat(a.id, USER.employeeNo))
    expect(warned.idleWarned).toBe('h5')
    expect(last(warned).text).toBe('5시간 뒤까지 미확인 시 대화 내용은 삭제됩니다.')
    // 같은 안내를 다시 보내지 않는다
    const again = await data(idleWarnChat(a.id, USER.employeeNo))
    expect(again.messages).toHaveLength(warned.messages.length)
    await data(idleDeleteChat(a.id, USER.employeeNo))
    expect((await getChat(a.id, USER.employeeNo)).ok).toBe(false)
  })

  it('질문 단계에서 응답이 없으면 2시간 안내이고, 긴급·민감정보 문의는 지우지 않고 숨긴다', async () => {
    const a = await data(startChat(USER, 'VPN이 끊겨요'))
    await settle()
    const warned = await data(idleWarnChat(a.id, USER.employeeNo))
    expect(warned.idleWarned).toBe('h2')
    expect(last(warned).text).toBe('이어서 하지 않으면 대화내역이 사라집니다.')
    // 긴급 징후가 있었던 문의는 삭제하지 않고 문의자 화면에서만 숨긴다
    const u = await data(startChat(USER, '피싱 메일의 링크를 눌렀어요'))
    await settle()
    await data(idleDeleteChat(u.id, USER.employeeNo))
    expect((await getChat(u.id, USER.employeeNo)).ok).toBe(false) // 문의자에게는 보이지 않는다
    const list = await listMyInquiries(USER.employeeNo)
    expect(list.ok && list.data.some((x) => x.id === u.id)).toBe(false)
  })

  it('삭제 전에 돌아오면 입력창을 잠그고, 이어서 하면 같은 대화로 계속한다', async () => {
    const a = await data(startChat(USER, FULL_VPN))
    await settle()
    const back = await data(idleBackChat(a.id, USER.employeeNo))
    expect(back.paused).toBe(true)
    const resumed = await data(resumeChat(a.id, USER.employeeNo))
    expect(resumed.paused).toBe(false)
    expect(resumed.step).toBe(a.step === 'collect' ? 'collect' : resumed.step)
    expect(last(resumed).text).toBe('같은 대화에서 이어서 진행해요.')
  })
})

describe('어긋난 요청 오류 (API)', () => {
  it('지난 버튼·중복 요청 같은 409 오류는 최신 화면으로 다시 그리는 대상이다', () => {
    expect(isStaleInquiry('INQUIRY_INVALID_STATE')).toBe(true)
    expect(isStaleInquiry('INQUIRY_CLOSED')).toBe(true)
    expect(isStaleInquiry('REQUEST_IN_PROGRESS')).toBe(true)
    expect(isStaleInquiry('INQUIRY_NOT_FOUND')).toBe(false)
  })
})

describe('긴급 건 접수 없이 종료 (API)', () => {
  it('연결을 거절하면 행동 안내와 내선 1000이 함께 보인다', async () => {
    const a = await data(startChat(USER, '피싱 메일의 링크를 눌렀어요'))
    await settle()
    const offer = last(await get(a.id))
    const closed = await data(replyChat(a.id, USER.employeeNo, { messageId: offer.id, action: 'connect-no' }))
    expect(closed.status).toBe('CLOSED_UNRESOLVED')
    expect(JSON.stringify(last(closed).blocks)).toContain('내선 1000')
  })
})

describe('접수 흐름 (API)', () => {
  /** 해결되지 않아 담당자 연결을 선택해 접수 초안까지 만든다 */
  async function toDraft(text = FULL_VPN) {
    const a = await data(startChat(USER, text))
    await settle()
    const ans = last(await get(a.id))
    const offer = await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'unresolved' }))
    const draft = await data(replyChat(a.id, USER.employeeNo, { messageId: last(offer).id, action: 'connect-yes' }))
    return draft
  }

  it('연결하면 접수 초안을 보여 주고, 확인하기 전에는 접수되지 않는다', async () => {
    const d = await toDraft()
    expect(d.step).toBe('draft')
    expect(d.ticket).toBeNull()
    expect(d.draft).toMatchObject({ categoryCode: 'NET', groupName: '네트워크팀', urgency: 'P3' })
    expect(last(d).card).toBe('draft')
  })

  it('초안을 확인하면 접수번호가 생기고, Jira 번호 생성 → 담당자 배정이 이어진다', async () => {
    const d = await toDraft()
    const done = await data(confirmChatDraft(d.id, USER.employeeNo))
    expect(done.ticket?.receiptNo).toMatch(/^RCPT-\d+$/)
    expect(done.status).toBe('RECEIVED')
    expect(done.draftState).toBe('confirmed')
    await settle()
    const after = await get(d.id)
    expect(after.ticket?.jiraKey).toMatch(/^ITHD-\d+$/)
    expect(after.ticket).toMatchObject({ workStatus: 'RDY', assignStatus: 'ASSIGNED', jiraSyncStatus: 'SYNCED', assigneeName: '김담당', groupName: '네트워크팀' })
    expect(after.status).toBe('HANDED_OFF')
  })

  it('접수 저장에 실패하면 접수 완료로 안내하지 않고 초안을 보존한다', async () => {
    const d = await toDraft()
    mockConfig.saveFail = true
    const r = await data(confirmChatDraft(d.id, USER.employeeNo))
    expect(r.ticket).toBeNull()
    expect(last(r).card).toBe('savefail')
    expect(r.draftState).toBe('view')
    // 다시 시도하면 접수된다
    mockConfig.saveFail = false
    const retry = await data(confirmChatDraft(d.id, USER.employeeNo))
    expect(retry.ticket?.receiptNo).toBeTruthy()
  })

  it('초안을 고치면 긴급도를 다시 판단하고 변경을 알린다', async () => {
    const d = await toDraft()
    const edited = await data(editDraft(d.id, USER.employeeNo, { summary: d.draft!.summary, businessImpact: '전 직원 50명이 접속 불가예요', triedActions: d.draft!.triedActions }))
    expect(edited.draft?.urgency).toBe('P1')
    expect(edited.draftNote).toContain('P3에서 P1')
  })

  it('접수하지 않고 종료하면 미해결 종료로 남고 Ticket 은 만들지 않는다', async () => {
    const d = await toDraft()
    const r = await data(cancelChatDraft(d.id, USER.employeeNo))
    expect(r.status).toBe('CLOSED_UNRESOLVED')
    expect(r.ticket).toBeNull()
  })

  it('처리 결과가 등록되면 문의자가 해결을 확인해 종료한다', async () => {
    const d = await toDraft()
    await data(confirmChatDraft(d.id, USER.employeeNo))
    await settle()
    // 담당자 처리 시연: 처리 대기 → 처리 중 → 해결 확인 대기
    await data(advanceChat(d.id, USER.employeeNo))
    const fin = await data(advanceChat(d.id, USER.employeeNo))
    expect(fin.ticket?.workStatus).toBe('FIN')
    expect(fin.ticket?.resolutionNote).toBeTruthy()
    const cls = await data(resolveChat(d.id, USER.employeeNo))
    expect(cls.ticket?.workStatus).toBe('CLS')
  })

  it('미해결이라고 알리면 사유와 함께 다시 처리 중으로 돌아간다', async () => {
    const d = await toDraft()
    await data(confirmChatDraft(d.id, USER.employeeNo))
    await settle()
    await data(advanceChat(d.id, USER.employeeNo))
    await data(advanceChat(d.id, USER.employeeNo))
    const re = await data(rejectChat(d.id, USER.employeeNo, '같은 오류가 계속 나요'))
    expect(re.ticket?.workStatus).toBe('WIP')
    expect(re.messages.some((m) => m.role === 'user' && m.text === '같은 오류가 계속 나요')).toBe(true)
    // 지난 진행 카드는 기록으로 남고, 새 진행 카드가 붙는다
    expect(re.messages.filter((m) => m.card === 'ticket' && m.ticketSnapshot)).toHaveLength(1)
    expect(re.messages.filter((m) => m.card === 'ticket')).toHaveLength(2)
  })

  it('사유 없이는 다시 확인을 요청할 수 없다', async () => {
    const d = await toDraft()
    await data(confirmChatDraft(d.id, USER.employeeNo))
    await settle()
    await data(advanceChat(d.id, USER.employeeNo))
    await data(advanceChat(d.id, USER.employeeNo))
    const same = await data(rejectChat(d.id, USER.employeeNo, '   '))
    expect(same.ticket?.workStatus).toBe('FIN')
  })

  it('접수 이후 보낸 메시지는 담당자에게 전달되는 추가 메시지다', async () => {
    const d = await toDraft()
    await data(confirmChatDraft(d.id, USER.employeeNo))
    const r = await data(sendChat(d.id, USER.employeeNo, '오후에는 외근이에요'))
    expect(last(r)).toMatchObject({ role: 'user', text: '오후에는 외근이에요', kind: '추가 메시지' })
  })
})

describe('대화 화면', () => {
  it('새 문의를 보내면 대화 화면으로 이동해 확인 질문을 보여 준다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), 'VPN이 끊겨요')
    await user.click(screen.getByRole('button', { name: '보내기' }))
    expect(await screen.findByText(/몇 가지만 확인할게요/, {}, SLOW)).toBeInTheDocument()
    expect(screen.getByText('VPN이 끊겨요', { selector: '.msg.u' })).toBeInTheDocument()
    // 사이드바 최근 문의에도 새 문의가 생긴다
    expect(await screen.findByRole('button', { name: /VPN이 끊겨요.*진행 중/ }, SLOW)).toBeInTheDocument()
  })

  it('안내를 받고 해결을 누르면 종료 안내와 "대화 이어가기"가 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    expect(await screen.findByText(/IT-NET-001 3\.1/, {}, SLOW)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '해결' }))
    expect(await screen.findByText(/AI 안내로 해결된 문의입니다/, {}, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '대화 이어가기' })).toBeInTheDocument()
  })

  it('답변 뒤에는 입력창이 꺼지고, 5시간 안내 띠가 보이며, 돌아오면 이어서 할지 고른다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findByText(/IT-NET-001 3\.1/, {}, SLOW)
    // 해결 · 미해결을 고르는 단계: 글을 쓸 수 없다
    const box = screen.getByLabelText('메시지 입력')
    expect(box).toBeDisabled()
    expect(box).toHaveAttribute('placeholder', '위 버튼으로 골라 주세요')
    // 시연: 5시간 안내 → 입력창 위 띠
    await user.click(screen.getByRole('button', { name: '응답 없음 안내' }))
    const bar = await screen.findByRole('status', {}, SLOW)
    expect(bar).toHaveTextContent('5시간 뒤까지 미확인 시 대화 내용은 삭제됩니다.')
    // 시연: 삭제 전에 돌아옴 → 이어서 채팅하기 / 새로운 문의하기
    await user.click(screen.getByRole('button', { name: '돌아옴 팝업' }))
    expect(await screen.findByRole('group', { name: '이어서 하기' }, SLOW)).toBeInTheDocument()
    expect(screen.getByLabelText('메시지 입력')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '이어서 채팅하기' }))
    expect(await screen.findByText('같은 대화에서 이어서 진행해요.', {}, SLOW)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '이어서 하기' })).not.toBeInTheDocument()
  })

  it('안내 뒤 삭제되면 새 문의 화면으로 돌아간다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findByText(/IT-NET-001 3\.1/, {}, SLOW)
    await user.click(screen.getByRole('button', { name: '안내 뒤 삭제' }))
    expect(await screen.findByRole('heading', { name: '무엇을 도와드릴까요?' }, SLOW)).toBeInTheDocument()
  })

  it('출처 버튼을 누르면 출처 미리보기 창이 열리고 Esc 로 닫힌다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await user.click(await screen.findByRole('button', { name: /IT-NET-001/ }, SLOW))
    const dlg = screen.getByRole('dialog')
    expect(within(dlg).getByText(/VPN 클라이언트를 최신 버전/)).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('담당자 연결 → 초안 확인 → 접수하면 접수번호와 진행 카드가 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await user.click(await screen.findByRole('button', { name: '미해결' }, SLOW))
    await user.click(await screen.findByRole('button', { name: '담당자 연결' }, SLOW))
    expect(await screen.findByText('확인 대기 · 아직 접수되지 않았어요', {}, SLOW)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '접수' }))
    expect(await screen.findByText(/접수번호는/, {}, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '접수 진행 단계' })).toBeInTheDocument()
    expect(screen.getByText('접수 확인 완료')).toBeInTheDocument()
  })

  it('초안에서 "수정"으로 고치고 반영하면 안내 문구가 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1003', '/new')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await user.click(await screen.findByRole('button', { name: '미해결' }, SLOW))
    await user.click(await screen.findByRole('button', { name: '담당자 연결' }, SLOW))
    await user.click(await screen.findByRole('button', { name: '수정' }, SLOW))
    const impact = screen.getByLabelText('업무 영향')
    await user.clear(impact)
    await user.type(impact, '전 직원 50명이 접속 불가예요')
    await user.click(screen.getByRole('button', { name: '수정 반영하기' }))
    expect(await screen.findByText(/긴급도를 P3에서 P1\(으\)로/, {}, SLOW)).toBeInTheDocument()
  })

  it('접수된 문의(시연 데이터)를 열면 진행 카드·담당자 메시지가 보이고 새 답변 표시가 지워진다', async () => {
    renderAs('EMP-1001', '/chat/101')
    expect(await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)).toBeInTheDocument()
    expect(screen.getByText(/김담당 담당자가 처리하고 있어요/)).toBeInTheDocument()
    expect(screen.getByText(/VPN 서버 쪽 인증 정보를 확인하고 있어요/)).toBeInTheDocument()
    expect(screen.getByLabelText('메시지 입력')).toHaveAttribute('placeholder', '담당자에게 추가 내용 남기기')
    const list = await screen.findByRole('button', { name: /문의 내역/ }, SLOW)
    expect(within(list).queryByText('1')).not.toBeInTheDocument()
  })

  it('해결 확인 대기 카드에서 미해결을 누르면 사유 입력 창이 열린다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/chat/101')
    await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    // 담당자 처리 시연: 처리 중 → 해결 확인 대기
    await advanceChat(101, 'EMP-1001')
    // 이전 안내에 남은 같은 이름의 버튼은 잠겨 있으므로, 눌 수 있는 버튼이 나타날 때까지 기다린다
    const reject = await waitFor(() => {
      const b = screen.getAllByRole('button', { name: '미해결' }).find((x) => !(x as HTMLButtonElement).disabled)
      if (!b) throw new Error('미해결 버튼 없음')
      return b
    }, SLOW)
    await user.click(reject)
    const send = screen.getByRole('button', { name: '다시 확인 요청' })
    expect(send).toBeDisabled() // 사유를 쓰기 전에는 보낼 수 없다
    await user.type(screen.getByLabelText('남은 증상'), '같은 오류가 나요')
    await user.click(send)
    expect(await screen.findByText(/다시 확인을 요청했어요/, {}, SLOW)).toBeInTheDocument()
  })

  it('종료된 문의(미확인)는 입력창 대신 안내와 "대화 이어가기"를 보여 준다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/chat/103')
    expect((await screen.findAllByText(/미확인 처리합니다/, {}, SLOW)).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('메시지 입력')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '대화 이어가기' }))
    expect(await screen.findByText(/상담을 다시 열었어요/, {}, SLOW)).toBeInTheDocument()
    expect(screen.getByLabelText('메시지 입력')).toBeInTheDocument()
  })

  it('없는 문의 주소는 안내 문구를 보여 준다', async () => {
    renderAs('EMP-1001', '/chat/9999')
    expect(await screen.findByText(/문의를 찾을 수 없어요/, {}, SLOW)).toBeInTheDocument()
  })
})
