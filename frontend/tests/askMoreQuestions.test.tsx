/**
 * AI 추가 질문(ASK_MORE): 선택칩·입력으로 답하고 "이름: 값" 줄로 묶어 한 번에 보낸다.
 * 순수 규칙(questionAnswers), 서버 응답 변환(questions·열림 조건·label=null), 대화 화면(모의)을 함께 확인한다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { startChat } from '../src/api/chat'
import type { ChatQuestion } from '../src/api/chatTypes'
import { toInquiry, toQuestions } from '../src/api/inquiryServer'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { nextKnown } from '../src/views/inquiry/messageKeys'
import { allAnswered, answersFromText, buildAnswerText, canType, directLabel, isAnswered, labelOf, showsInput, unansweredCount } from '../src/views/inquiry/questionAnswers'

const NL = String.fromCharCode(10)
const SLOW = { timeout: 3000 }
const situation: ChatQuestion = { label: '상황', text: '어떤 상황인가요?', options: ['집에서 자주 끊겨요', '사무실에서 안 돼요'], allowText: true }
const impact: ChatQuestion = { label: '영향 범위', text: '누가 영향을 받나요?', options: ['저만 그래요', '팀 전체가 그래요'], allowText: false }
const screen_: ChatQuestion = { label: '화면 메시지', text: '화면에 뜨는 메시지가 있나요?', options: ['메시지가 없어요'], allowText: true }
const typed: ChatQuestion = { label: '발생 시점', text: '언제부터인가요?', options: [], allowText: false }
const old: ChatQuestion = { label: null, text: '증상을 알려 주세요', options: [], allowText: false }

describe('질문 답 규칙', () => {
  it('선택형은 하나를 고르면 답이 되고, 직접 입력 버튼은 선택지가 있고 직접 입력도 받는 질문에만 있다', () => {
    expect(canType(situation)).toBe(true)
    expect(canType(impact)).toBe(false) // allowText=false 라 선택지만
    expect(canType(typed)).toBe(false)
    expect(isAnswered(situation, { mode: 'option', option: '집에서 자주 끊겨요', text: '' })).toBe(true)
    expect(isAnswered(situation, undefined)).toBe(false)
  })

  it('상황 질문의 직접 입력 버튼은 "그 밖의 상황"으로 고정이고, 다른 질문은 "직접 입력"이다', () => {
    expect(directLabel(situation)).toBe('그 밖의 상황')
    expect(directLabel(screen_)).toBe('직접 입력')
  })

  it('선택지가 없으면 allowText=false 여도 입력칸을 막지 않는다', () => {
    expect(showsInput(typed, undefined)).toBe(true)
    expect(showsInput(old, undefined)).toBe(true)
    expect(showsInput(situation, undefined)).toBe(false)
    expect(showsInput(situation, { mode: 'text', option: '', text: '' })).toBe(true)
  })

  it('입력형·혼합형: 직접 입력은 비어 있으면 답이 아니다 ("잘 모르겠어요"는 답이다), 빈칸을 자동으로 채우지 않는다', () => {
    expect(isAnswered(situation, { mode: 'text', option: '집에서 자주 끊겨요', text: '' })).toBe(false) // 고른 선택지가 있어도 직접 입력으로 바꿨으면 입력이 답
    expect(isAnswered(situation, { mode: 'text', option: '', text: '   ' })).toBe(false)
    expect(isAnswered(situation, { mode: 'text', option: '', text: '잘 모르겠어요' })).toBe(true)
    expect(allAnswered([situation, typed], [{ mode: 'option', option: '집에서 자주 끊겨요', text: '' }, undefined])).toBe(false)
    expect(unansweredCount([situation, impact, typed], [undefined, undefined, undefined])).toBe(3)
  })

  it('"이름: 값" 줄로 묶고, 입력창의 글은 맨 끝 "추가 내용"으로 붙이며 없으면 그 줄은 없다', () => {
    const qs = [situation, impact, screen_]
    const a = [
      { mode: 'text' as const, option: '', text: '재택에서만 그래요' },
      { mode: 'option' as const, option: '저만 그래요', text: '' },
      { mode: 'option' as const, option: '메시지가 없어요', text: '' },
    ]
    expect(buildAnswerText(qs, a, '')).toBe(['상황: 재택에서만 그래요', '영향 범위: 저만 그래요', '화면 메시지: 메시지가 없어요'].join(NL))
    expect(buildAnswerText(qs, a, '  어제부터요 ')).toBe(['상황: 재택에서만 그래요', '영향 범위: 저만 그래요', '화면 메시지: 메시지가 없어요', '추가 내용: 어제부터요'].join(NL))
  })

  it('label 이 없는 옛 질문은 질문 글을 이름으로 쓴다', () => {
    expect(labelOf(old)).toBe('증상을 알려 주세요')
    expect(buildAnswerText([old], [{ mode: 'text', option: '', text: '접속이 안 돼요' }], '')).toBe('증상을 알려 주세요: 접속이 안 돼요')
  })

  it('직접 입력의 줄바꿈은 공백으로 바꿔 줄 구조가 깨지지 않게 한다', () => {
    const t = buildAnswerText([typed], [{ mode: 'text', option: '', text: ['오늘', '오전'].join(NL) }], '')
    expect(t).toBe('발생 시점: 오늘 오전')
  })
})

const at = (n: number) => new Date(Date.UTC(2026, 10, 6, 0, n)).toISOString()
const inq = (over: Record<string, unknown> = {}) =>
  ({ id: 9, status: 'IN_PROGRESS', title: '질문 시험', categoryCode: 'NET', ticket: null, activeDraftId: null, displayStatus: 'in_progress', action: 'ASK_MORE', resolutionResult: null, recommendedGroup: null, createdAt: at(0), updatedAt: at(3), ...over }) as never
const sq = [
  { label: '상황', text: '어떤 상황인가요?', options: ['집에서 자주 끊겨요'], allowText: true },
  { label: null, text: '화면 메시지가 있나요?', options: ['메시지가 없어요'] },
]
const text = (id: number, sender: 'USER' | 'AI', content: string, extra: Record<string, unknown> = {}) => ({ id, sessionId: 1, seq: id, sender, kind: 'TEXT', code: null, content, sources: [], createdAt: at(id), ...extra }) as never

describe('서버 응답의 추가 질문', () => {
  it('questions 를 화면 질문으로 바꾼다: 빠진 값은 옛 질문으로 채운다 (label=null, allowText=false)', () => {
    expect(toQuestions(sq)).toEqual([
      { label: '상황', text: '어떤 상황인가요?', options: ['집에서 자주 끊겨요'], allowText: true },
      { label: null, text: '화면 메시지가 있나요?', options: ['메시지가 없어요'], allowText: false },
    ])
    expect(toQuestions([])).toBeUndefined()
    expect(toQuestions(undefined)).toBeUndefined()
  })

  it('마지막 메시지가 질문 있는 AI 메시지이고 IN_PROGRESS·ASK_MORE 이면 답할 수 있다 (nextActions 없이도: 다시 열 때)', () => {
    const list = [text(1, 'USER', '인터넷이 안 돼요'), text(2, 'AI', '몇 가지 여쭤볼게요.', { questions: sq })]
    const i = toInquiry(inq(), list) // nextActions 없음
    const m = i.messages.find((x) => x.id === 2)!
    expect(m.questions).toHaveLength(2)
    expect(m.questionsOpen).toBe(true)
    expect(i.step).toBe('collect')
  })

  it('질문 뒤에 내 답이 이어졌거나 다른 상태·행동이면 읽기 전용이다 (과거 질문도 남는다)', () => {
    const answered = [text(1, 'USER', '인터넷이 안 돼요'), text(2, 'AI', '여쭤볼게요.', { questions: sq }), text(3, 'USER', '상황: 집에서 자주 끊겨요')]
    const a = toInquiry(inq(), answered, ['REPLY'])
    expect(a.messages.find((x) => x.id === 2)?.questions).toHaveLength(2)
    expect(a.messages.find((x) => x.id === 2)?.questionsOpen).toBeUndefined()
    const asked = [text(1, 'USER', '인터넷이 안 돼요'), text(2, 'AI', '여쭤볼게요.', { questions: sq })]
    expect(toInquiry(inq({ action: 'ANSWER' }), asked).messages.find((x) => x.id === 2)?.questionsOpen).toBeUndefined()
    expect(toInquiry(inq({ status: 'CLOSED_UNRESOLVED' }), asked).messages.find((x) => x.id === 2)?.questionsOpen).toBeUndefined()
  })

  it('질문이 없는 기존 답변·연결 안내는 그대로이고, R-29 선택·카드 메시지가 섞여 있어도 질문은 사라지지 않는다', () => {
    const plain = toInquiry(inq({ action: 'ANSWER' }), [text(1, 'USER', '질문'), text(2, 'AI', '답입니다.', { questions: [] })])
    expect(plain.messages.find((x) => x.id === 2)?.questions).toBeUndefined()
    const mixed = [text(1, 'USER', '질문'), text(2, 'AI', '여쭤볼게요.', { questions: sq }), { id: 3, sessionId: 1, seq: 3, sender: 'USER', kind: 'CHOICE', code: 'UNRESOLVED', content: null, sources: [], createdAt: at(3) } as never]
    const i = toInquiry(inq(), mixed)
    expect(i.messages.find((x) => x.id === 2)?.questions).toHaveLength(2)
  })
})

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

describe('대화 화면의 추가 질문 (모의)', () => {
  async function open() {
    const r = await startChat({ employeeNo: 'EMP-1003', name: '김민지' }, 'VPN이 끊겨요')
    if (!r.ok) throw new Error('시작')
    renderAs('EMP-1003', `/chat/${r.data.id}`)
    return r.data
  }

  it('질문이 선택칩으로 보이고, 모든 질문에 답해야 보내기가 켜지며, 누르는 즉시 보내지 않는다', async () => {
    const user = userEvent.setup()
    await open()
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    const radios = within(grp).getAllByRole('radio')
    expect(radios.length).toBeGreaterThan(1)
    const send = within(grp).getByRole('button', { name: '답변 보내기' })
    expect(send).toBeDisabled()
    const groups = within(grp).getAllByRole('radiogroup')
    // 첫 질문만 고르면 아직 보낼 수 없다 (빈칸을 자동으로 채우지 않는다)
    await user.click(within(groups[0]).getAllByRole('radio')[0])
    expect(within(groups[0]).getAllByRole('radio')[0]).toHaveAttribute('aria-checked', 'true')
    if (groups.length > 1) expect(send).toBeDisabled()
    expect(screen.queryByText(/상황: /)).toBeNull() // 보내지 않았다
  })

  it('직접 입력 버튼으로 입력칸이 열리고, 입력창의 글은 추가 내용으로 함께 한 번만 가며, 보낸 질문은 잠긴다', async () => {
    const user = userEvent.setup()
    await open()
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    const groups = within(grp).getAllByRole('radiogroup')
    for (const g of groups) {
      const other = within(g).queryByRole('radio', { name: /그 밖의 상황|직접 입력/ })
      if (other && groups.indexOf(g) === 0) {
        await user.click(other)
        await user.type(within(grp).getByLabelText(/직접 입력$/), '잘 모르겠어요')
      } else await user.click(within(g).getAllByRole('radio')[0])
    }
    await user.type(screen.getByLabelText('메시지 입력'), '어제부터 심해요')
    await user.click(within(grp).getByRole('button', { name: '답변 보내기' }))
    // 한 번에 묶여 내 말풍선 하나로 보인다
    const bubble = await screen.findByText(/추가 내용: 어제부터 심해요/, undefined, SLOW)
    expect(bubble.textContent).toMatch(/: 잘 모르겠어요/) // 첫 질문은 직접 입력으로 답했다
    expect(screen.getAllByText(/추가 내용: 어제부터 심해요/)).toHaveLength(1)
    // 보낸 질문은 읽기 전용으로 남는다
    await waitFor(() => expect(screen.getAllByRole('group', { name: '지난 추가 질문' }).length).toBeGreaterThan(0), SLOW)
  })

  it('질문에 다 답하지 않고 입력창에서 Enter 로 보내려 하면 막고 안내한다', async () => {
    const user = userEvent.setup()
    await open()
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    await user.type(screen.getByLabelText('메시지 입력'), '그냥 보낼래요{Enter}')
    // 안내는 채팅 글이 아니라 입력창에 붙는다: 입력창이 빨갛게(aria-invalid) 바뀌고 빨간 문구가 보인다
    const warn = await screen.findByText(/아직 답하지 않은 질문이/)
    expect(warn.closest('.cmpw')).not.toBeNull()
    expect(screen.getByLabelText('메시지 입력')).toHaveAttribute('aria-invalid', 'true')
    expect(document.querySelector('.composer.err')).not.toBeNull()
    expect(within(grp).queryByText(/아직 답하지 않은 질문이/)).toBeNull() // 질문 안에는 오류 문구가 없다
    expect(document.querySelectorAll('.msg.u')).toHaveLength(1) // 처음 질문 하나뿐: 아무것도 보내지 않았다
    expect(screen.getByLabelText('메시지 입력')).toHaveValue('그냥 보낼래요') // 쓴 글은 그대로
    // 잠깐 뒤 저절로 사라진다
    await waitFor(() => expect(screen.queryByText(/아직 답하지 않은 질문이/)).toBeNull(), { timeout: 6000 })
    expect(document.querySelector('.composer.err')).toBeNull()
  }, 12000)

  it('질문에 답을 고르면 입력창 경고는 바로 사라진다', async () => {
    const user = userEvent.setup()
    await open()
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    await user.type(screen.getByLabelText('메시지 입력'), '보낼래요{Enter}')
    await screen.findByText(/아직 답하지 않은 질문이/)
    await user.click(within(within(grp).getAllByRole('radiogroup')[0]).getAllByRole('radio')[0])
    expect(screen.queryByText(/아직 답하지 않은 질문이/)).toBeNull()
  })

  it('보낸 뒤 지난 질문에는 내가 고른 칸이 색 있는 선(picked)으로 보이고, 직접 입력한 답은 글로 보인다', async () => {
    const user = userEvent.setup()
    await open()
    const grp = await screen.findByRole('group', { name: '추가 질문' }, SLOW)
    const groups = within(grp).getAllByRole('radiogroup')
    const first = within(groups[0]).getAllByRole('radio')[0].textContent
    await user.click(within(groups[0]).getAllByRole('radio')[0])
    await user.click(within(groups[1]).getByRole('radio', { name: /직접 입력/ }))
    await user.type(within(grp).getByLabelText(/직접 입력$/), '내가 쓴 답')
    for (const g of groups.slice(2)) await user.click(within(g).getAllByRole('radio')[0])
    await user.click(within(grp).getByRole('button', { name: '답변 보내기' }))
    const past = await screen.findAllByRole('group', { name: '지난 추가 질문' }, SLOW)
    const picked = past[0].querySelectorAll('.chip.picked')
    expect(picked.length).toBeGreaterThanOrEqual(2) // 고른 칸들(선택 + 직접 입력 칸)
    expect([...picked].some((e) => e.textContent === first)).toBe(true)
    expect(within(past[0]).getByText('내가 쓴 답')).toBeInTheDocument()
  })
})

describe('지난 질문의 답 읽기', () => {
  it('내 말풍선의 "이름: 답" 줄에서 질문별 답을 읽는다: 선택지와 같으면 선택, 아니면 직접 입력, 없으면 undefined', () => {
    const text = ['상황: 집에서 자주 끊겨요', '영향 범위: 우리 부서 전체예요', '추가 내용: 어제부터요'].join(NL)
    const r = answersFromText([situation, impact, screen_], text)
    expect(r[0]).toEqual({ mode: 'option', option: '집에서 자주 끊겨요', text: '' })
    expect(r[1]).toEqual({ mode: 'text', option: '', text: '우리 부서 전체예요' })
    expect(r[2]).toBeUndefined()
  })
  it('label=null 인 옛 질문은 질문 글 이름으로 찾는다', () => {
    expect(answersFromText([old], '증상을 알려 주세요: 접속이 안 돼요')[0]).toEqual({ mode: 'text', option: '', text: '접속이 안 돼요' })
  })
})

describe('보낸 글이 임시 글에서 진짜 글로 바뀔 때', () => {
  const u = (id: number, text: string) => ({ id, role: 'user', text })
  const a = (id: number) => ({ id, role: 'assistant' })
  it('같은 내 글은 같은 키를 이어 쓰고 새 메시지로 치지 않는다 (화면이 다시 불러온 것처럼 보이지 않게)', () => {
    let k = nextKnown(null, 7, [u(1, '처음'), a(2)])
    k = nextKnown(k, 7, [u(1, '처음'), a(2), u(-1, '다음 글'), a(-2)]) // 임시 글과 준비 중 표시
    expect(k.opt).toBe('다음 글')
    k = nextKnown(k, 7, [u(1, '처음'), a(2), u(30, '다음 글'), a(31)]) // 서버가 진짜 글·답으로 바꿔 줌
    expect(k.alias.get(30)).toBe(-1) // 임시 글의 키를 이어 쓴다
    expect(k.fresh.has(30)).toBe(false) // 내 글은 다시 움직이지 않는다
    expect(k.fresh.has(31)).toBe(true) // 새 AI 답만 움직인다
  })
  it('다른 글이면 이어 쓰지 않고, 바뀐 게 없으면 같은 기록을 돌려준다', () => {
    let k = nextKnown(null, 7, [u(1, '처음')])
    k = nextKnown(k, 7, [u(1, '처음'), u(-1, '임시')])
    const same = nextKnown(k, 7, [u(1, '처음'), u(-1, '임시')])
    expect(same).toBe(k)
    const other = nextKnown(k, 7, [u(1, '처음'), u(40, '마스킹된 다른 글')])
    expect(other.alias.size).toBe(0)
    expect(other.fresh.has(40)).toBe(true)
  })
  it('문의를 바꾸면 처음부터 다시 시작하고 아무것도 움직이지 않는다', () => {
    const k = nextKnown(null, 7, [u(1, '처음')])
    const other = nextKnown(k, 8, [u(5, '다른 문의'), a(6)])
    expect(other.id).toBe(8)
    expect(other.fresh.size).toBe(0)
  })
})
