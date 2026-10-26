/**
 * 프로토타입 보완 사항 테스트: 민감정보 가리기 · 접수 초안 수정 · 진행 카드 색과 안내 · 비밀번호 초기화 · 모달 초점 · 로고 홈.
 * 가짜 응답(mock)으로만 실행하며, 시연용 지연은 tests/setup.ts 에서 없앤다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { confirmChatDraft, editDraft, getChat, replyChat, sendChat, startChat } from '../src/api/chat'
import type { Inquiry } from '../src/api/chatTypes'
import { getRecord } from '../src/api/mock/chatStore'
import type { ApiResult } from '../src/api/types'
import { hasMask, maskSensitive } from '../src/core/mask'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const USER = { employeeNo: 'EMP-1003', name: '박민수' }
const FULL_VPN = 'VPN이 자꾸 끊겨요. 어제부터 안 돼요. 저만 안 되고 메일 업무는 가능해요. 재접속해 봤어요.'

const settle = () => new Promise<void>((r) => setTimeout(r, 30))
const last = (inq: Inquiry) => inq.messages[inq.messages.length - 1]

async function data(p: Promise<ApiResult<Inquiry>>): Promise<Inquiry> {
  const r = await p
  if (!r.ok) throw new Error(JSON.stringify(r))
  return r.data
}

/** 접수 초안이 나올 때까지 진행한다 */
async function toDraft(text = FULL_VPN) {
  const a = await data(startChat(USER, text))
  await settle()
  const ans = last((await getChat(a.id, USER.employeeNo).then((r) => (r.ok ? r.data : a))) as Inquiry)
  const offer = await data(replyChat(a.id, USER.employeeNo, { messageId: ans.id, action: 'unresolved' }))
  return data(replyChat(a.id, USER.employeeNo, { messageId: last(offer).id, action: 'connect-yes' }))
}

function renderAt(path: string, employeeNo?: string) {
  if (employeeNo) tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('민감정보 가리기', () => {
  it('이름 뒤의 값과 6자리 이상 숫자를 가리고, 일반 문장은 그대로 둔다', () => {
    expect(maskSensitive('제 비밀번호는 abc12345 입니다').text).toBe('제 비밀번호는 ●●●●●● 입니다')
    expect(maskSensitive('인증번호: 123456').hit).toBe(true)
    expect(maskSensitive('주문번호 12345678 확인').text).toBe('주문번호 ●●●●●● 확인')
    // 비밀번호라는 말만 있는 문장은 값이 없으므로 가리지 않는다
    expect(maskSensitive('비밀번호를 잊어버렸어요')).toEqual({ text: '비밀번호를 잊어버렸어요', hit: false })
    expect(maskSensitive('비밀번호가 안 돼요').hit).toBe(false)
    expect(hasMask('●●●●●●')).toBe(true)
  })

  it('문의 제목과 대화, 안내 문구 어디에도 원문이 남지 않는다', async () => {
    const a = await data(startChat(USER, '제 비밀번호는 abc12345 이고 인증번호 123456 입니다'))
    const text = JSON.stringify(a)
    expect(text).not.toContain('abc12345')
    expect(text).not.toContain('123456')
    expect(a.title).toContain('●')
    expect(a.messages.some((m) => m.role === 'sys' && m.text?.includes('●로 바꿨어요'))).toBe(true)
  })

  it('초안을 고칠 때와 접수 후 추가 메시지에서도 가린다', async () => {
    const d = await toDraft()
    const edited = await data(editDraft(d.id, USER.employeeNo, { summary: d.draft!.summary, businessImpact: '비밀번호는 zz9988aa 입니다', triedActions: d.draft!.triedActions }))
    expect(JSON.stringify(edited.draft)).not.toContain('zz9988aa')
    const sent = await data(confirmChatDraft(d.id, USER.employeeNo))
    await settle()
    const more = await data(sendChat(sent.id, USER.employeeNo, '인증번호 654321 입니다'))
    expect(JSON.stringify(more.messages)).not.toContain('654321')
  })
})

describe('접수 초안 수정', () => {
  it('발생 시점도 고칠 수 있고, 고친 글로 세부 유형과 긴급도를 다시 판단해 바뀐 항목을 알린다', async () => {
    const d = await toDraft()
    expect(d.draft).toMatchObject({ inquiryTypeCode: 'NET-02', inquiryTypeName: 'VPN 접속 불가(개인)', urgency: 'P3' })
    const edited = await data(
      editDraft(d.id, USER.employeeNo, { summary: d.draft!.summary, onset: '어제 오후부터 전사 접속이 안 돼요', businessImpact: d.draft!.businessImpact, triedActions: d.draft!.triedActions }),
    )
    expect(edited.draft?.onset).toBe('어제 오후부터 전사 접속이 안 돼요')
    expect(edited.draft?.inquiryTypeCode).toBe('NET-03')
    expect(edited.draft?.urgency).toBe('P1')
    expect(edited.draft?.rejudged).toEqual(expect.arrayContaining(['inquiryType', 'urgency']))
  })

  it('수정 화면은 4개 항목만 입력칸이 되고 나머지는 잠금 표시로 남는다', async () => {
    const user = userEvent.setup()
    renderAt('/new', 'EMP-1003')
    await user.type(await screen.findByLabelText('메시지 입력', {}, SLOW), FULL_VPN)
    await user.click(screen.getByRole('button', { name: '보내기' }))
    await user.click(await screen.findByRole('button', { name: '아직 안 돼요' }, SLOW))
    await user.click(await screen.findByRole('button', { name: '담당자 연결하기' }, SLOW))
    // 보기 화면: 분류와 세부 유형이 한국어 이름으로 보인다
    expect(await screen.findByText('분류', {}, SLOW)).toBeInTheDocument()
    expect(screen.getByText('NET-02 · VPN 접속 불가(개인)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '수정할게요' }))
    expect(screen.getByLabelText('문의 내용')).toBeInTheDocument()
    expect(screen.getByLabelText('발생 시점')).toBeInTheDocument()
    expect(screen.getByLabelText('업무 영향')).toBeInTheDocument()
    expect(screen.getByLabelText('시도한 조치')).toBeInTheDocument()
    // 자동 판단 항목(대상 시스템, AI 안내, 분류, 세부 유형, 긴급도, 담당 그룹)은 잠금 표시
    expect(screen.getAllByText('자동으로 판단하는 항목')).toHaveLength(6)
    const onset = screen.getByLabelText('발생 시점')
    await user.clear(onset)
    await user.type(onset, '어제 오후부터 전사 접속이 안 돼요')
    await user.click(screen.getByRole('button', { name: '수정 반영하기' }))
    expect(await screen.findByText('NET-03 · VPN 전사 장애', {}, SLOW)).toBeInTheDocument()
    expect(screen.getAllByText('다시 판단됨').length).toBeGreaterThanOrEqual(2)
  })
})

describe('진행 카드', () => {
  it('처리 중에는 파랑, 생성 결과를 모를 때(VERIFYING)는 청록과 "운영자 확인 중"으로 안내한다', async () => {
    const rec = getRecord(101)!
    const t = rec.inquiry.ticket!
    t.jiraSyncStatus = 'VERIFYING'
    t.assignStatus = 'PENDING'
    t.workStatus = null
    t.assigneeName = null
    renderAt('/chat/101', 'EMP-1001')
    const stepper = await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    expect(stepper.getAttribute('style')).toContain('--s-asg-dot')
    expect(within(stepper).getByText('운영자 확인 중')).toBeInTheDocument()
    expect(screen.getByText(/운영자가 담당자 연결을 확인하고 있어요. 다시 접수하실 필요는 없어요/)).toBeInTheDocument()
  })

  it('처리 중인 접수는 파랑이다', async () => {
    renderAt('/chat/101', 'EMP-1001')
    const stepper = await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    expect(stepper.getAttribute('style')).toContain('--s-prog-dot')
  })

  it('해결 완료로 바뀌는 순간에는 초록이 되고 스파크 4개가 붙는다', async () => {
    const rec = getRecord(101)!
    const t = rec.inquiry.ticket!
    t.workStatus = 'FIN'
    t.finishedAt = '2026-10-20T14:20:00+09:00'
    const user = userEvent.setup()
    renderAt('/chat/101', 'EMP-1001')
    const stepper = await screen.findByRole('list', { name: '접수 진행 단계' }, SLOW)
    // 보라(해결 확인 대기)이고, 완료 시각이 보인다
    expect(stepper.getAttribute('style')).toContain('--s-need-dot')
    expect(within(stepper).getByText(/완료 · 10\.20 14:20/)).toBeInTheDocument()
    expect(stepper.querySelectorAll('.sp')).toHaveLength(0)
    // 이전 안내에 남은 같은 이름의 버튼은 잠겨 있으므로, 눌 수 있는 버튼만 고른다
    const resolve = screen.getAllByRole('button', { name: '해결됐어요' }).find((b) => !(b as HTMLButtonElement).disabled)!
    await user.click(resolve)
    await screen.findByText(/문의자 확인으로 종료되었어요/, {}, SLOW)
    const after = screen.getByRole('list', { name: '접수 진행 단계' })
    expect(after.getAttribute('style')).toContain('--s-ok-dot')
    expect(after.querySelectorAll('.sp')).toHaveLength(4)
    expect(after.querySelector('.st:last-child')).toHaveClass('chg')
  })
})

describe('비밀번호 초기화와 모달 초점', () => {
  it('로그인 화면의 링크로 초기화 창을 열고, 빈 사번은 입력칸 아래에 오류를 남긴다', async () => {
    const user = userEvent.setup()
    renderAt('/login')
    const link = screen.getByRole('button', { name: '비밀번호를 잊으셨나요?' })
    await user.click(link)
    const dialog = await screen.findByRole('dialog', { name: '비밀번호 초기화' })
    // 열면 창 안의 첫 입력칸으로 초점이 간다
    expect(within(dialog).getByLabelText('사번')).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: '휴대폰으로 인증하기' }))
    const id = within(dialog).getByLabelText('사번')
    expect(id).toHaveAttribute('aria-invalid', 'true')
    expect(id).toHaveAccessibleDescription('사번을 입력해 주세요.')
    // 입력하면 오류가 사라진다
    await user.type(id, 'EMP-1001')
    expect(id).not.toHaveAttribute('aria-invalid', 'true')
    await user.click(within(dialog).getByRole('button', { name: '휴대폰으로 인증하기' }))
    expect(await screen.findByRole('dialog', { name: '인증 문자를 보냈어요' })).toBeInTheDocument()
  })

  it('Esc 로 닫으면 창을 열었던 링크로 초점이 돌아가고, Tab 은 창 안에서만 돈다', async () => {
    const user = userEvent.setup()
    renderAt('/login')
    const link = screen.getByRole('button', { name: '비밀번호를 잊으셨나요?' })
    await user.click(link)
    const dialog = await screen.findByRole('dialog', { name: '비밀번호 초기화' })
    // 마지막 버튼에서 Tab 을 누르면 첫 칸으로 돌아온다
    within(dialog).getByRole('button', { name: '휴대폰으로 인증하기' }).focus()
    await user.tab()
    expect(dialog.contains(document.activeElement)).toBe(true)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(link).toHaveFocus()
  })

  it('로그인 전 상담의 비밀번호 답변에서도 같은 창을 열 수 있고, 입력한 값은 가려서 보인다', async () => {
    const user = userEvent.setup()
    renderAt('/login')
    await user.click(screen.getByRole('button', { name: '비밀번호를 재설정하고 싶어요' }))
    const open = await screen.findByRole('button', { name: '비밀번호 초기화 열기' }, SLOW)
    await user.click(open)
    expect(await screen.findByRole('dialog', { name: '비밀번호 초기화' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    const box = screen.getByLabelText('로그인 전 상담 입력')
    await user.type(box, '비밀번호는 abc12345 입니다{Enter}')
    const panel = screen.getByRole('region', { name: '로그인 전 상담' })
    expect(await within(panel).findByText(/●로 바꿨어요/, {}, SLOW)).toBeInTheDocument()
    expect(within(panel).queryByText(/abc12345/)).not.toBeInTheDocument()
  })
})

describe('로고와 용어', () => {
  it('로고를 누르면 문의자는 새 문의 화면으로 이동한다', async () => {
    const user = userEvent.setup()
    renderAt('/faq', 'EMP-1001')
    await user.click(await screen.findByRole('button', { name: 'ITssue 홈으로' }, SLOW))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
  })

  it('담당자는 처리할 문의, 관리자는 대시보드로 이동한다', async () => {
    const user = userEvent.setup()
    const { unmount } = renderAt('/faq', 'EMP-1107')
    await user.click(await screen.findByRole('button', { name: 'ITssue 홈으로' }, SLOW))
    expect(await screen.findByRole('button', { name: '처리할 문의' }, SLOW)).toHaveAttribute('aria-current', 'page')
    unmount()
    renderAt('/faq', 'EMP-0912')
    await user.click(await screen.findByRole('button', { name: 'ITssue 홈으로' }, SLOW))
    expect(await screen.findByRole('button', { name: '대시보드' }, SLOW)).toHaveAttribute('aria-current', 'page')
  })

  it('새 문의 칩 이름과 입력되는 문장이 맞는다', async () => {
    const user = userEvent.setup()
    renderAt('/new', 'EMP-1001')
    await user.click(await screen.findByRole('button', { name: '사내 시스템' }, SLOW))
    expect(screen.getByLabelText('메시지 입력')).toHaveValue('전자결재 접속이 안 돼요')
  })
})
