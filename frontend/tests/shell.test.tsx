/**
 * 문의자 화면 틀 테스트: 사이드바 메뉴 · 새 문의(챗봇 시작) · FAQ.
 * 가짜 응답(mock)으로만 실행하며, 로그인 상태는 가짜 토큰을 직접 넣어 만든다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

// 가짜 서버 지연을 기다리기 위한 넉넉한 대기 시간
const SLOW = { timeout: 3000 }

/** 가짜 토큰으로 로그인한 상태에서 지정한 주소를 그린다. */
function renderAs(userId: string, path = '/new') {
  tokenStore.set(`mock.${userId}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('화면 전환과 접근성', () => {
  it('화면 제목으로 문서 제목이 바뀌고, 건너뛰기 버튼이 본문으로 초점을 옮긴다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/faq')
    await screen.findByRole('heading', { name: '먼저 확인해 보세요' }, SLOW)
    expect(document.title).toBe('FAQ · ITssue')
    const skip = screen.getByRole('button', { name: '본문으로 건너뛰기' })
    await user.click(skip)
    const main = document.querySelector('main.main') as HTMLElement
    expect(main.id).toBe('main')
    expect(main).toHaveFocus()
  })
})

describe('사이드바', () => {
  it('문의자는 새 문의 · 문의 내역 · FAQ 메뉴와 사용자 정보가 보인다', async () => {
    renderAs('EMP-1001')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(within(nav).getByRole('button', { name: /새 문의/ })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('button', { name: /문의 내역/ })).toBeInTheDocument()
    expect(within(nav).getByRole('button', { name: 'FAQ' })).toBeInTheDocument()
    // 문의자에게는 업무·운영 메뉴가 없다
    expect(within(nav).queryByRole('button', { name: '처리할 문의' })).not.toBeInTheDocument()
    expect(screen.getByText('개발1팀 · 문의자')).toBeInTheDocument()
  })

  it('담당자에게는 업무 메뉴, 관리자에게는 운영 메뉴가 더해진다', async () => {
    const { unmount } = renderAs('EMP-1107')
    expect(await screen.findByRole('button', { name: '처리할 문의' }, SLOW)).toBeInTheDocument()
    unmount()
    renderAs('EMP-0912')
    expect(await screen.findByRole('button', { name: '대시보드' }, SLOW)).toBeInTheDocument()
  })

  it('최근 문의와 확인하지 않은 답변 수를 보여 준다', async () => {
    renderAs('EMP-1001')
    expect(await screen.findByText('VPN 연결이 자주 끊겨요', {}, SLOW)).toBeInTheDocument()
    // 문의 내역 메뉴 옆의 읽지 않은 수
    const list = screen.getByRole('button', { name: /문의 내역/ })
    expect(within(list).getByText('1')).toBeInTheDocument()
  })

  it('문의가 없는 계정은 최근 문의 영역을 보여 주지 않는다', async () => {
    renderAs('EMP-1003')
    await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(screen.queryByText('최근 문의')).not.toBeInTheDocument()
  })

  it('로그아웃하면 로그인 화면으로 돌아간다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001')
    await user.click(await screen.findByRole('button', { name: '로그아웃' }, SLOW))
    expect(screen.getByRole('heading', { name: 'IT 문제, 먼저 물어보세요' })).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })

  it('좁은 화면의 메뉴 버튼으로 사이드바를 열고 닫는다', async () => {
    const user = userEvent.setup()
    const { container } = renderAs('EMP-1001', '/faq')
    await screen.findByRole('heading', { name: 'FAQ' }, SLOW)
    const app = container.querySelector('.app')
    expect(app).not.toHaveClass('nav-open')
    await user.click(screen.getByRole('button', { name: '메뉴 열기' }))
    expect(app).toHaveClass('nav-open')
    // 메뉴를 눌러 이동하면 사이드바가 닫힌다
    await user.click(within(screen.getByRole('navigation', { name: '주 메뉴' })).getByRole('button', { name: /새 문의/ }))
    expect(app).not.toHaveClass('nav-open')
  })
})

describe('새 문의 (챗봇 시작 화면)', () => {
  it('인사말과 입력창, 분류 칩, 추천 카드가 보인다', async () => {
    renderAs('EMP-1001')
    expect(await screen.findByText('김서연님, 안녕하세요', {}, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '무엇을 도와드릴까요?' })).toBeInTheDocument()
    expect(screen.getByLabelText('메시지 입력')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /계정·로그인/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /비밀번호를 잊었어요/ })).toBeInTheDocument()
  })

  it('칩을 누르면 입력창에 문장만 채워지고 바로 보내지지 않는다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001')
    await user.click(await screen.findByRole('button', { name: /계정·로그인/ }, SLOW))
    expect(screen.getByLabelText('메시지 입력')).toHaveValue('계정이 잠겼어요')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('입력이 비어 있으면 보내기 버튼이 막혀 있다', async () => {
    renderAs('EMP-1001')
    expect(await screen.findByRole('button', { name: '보내기' }, SLOW)).toBeDisabled()
  })

  it('Enter 로 보내면 문의가 만들어지고 대화 화면으로 이동한다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001')
    const box = await screen.findByLabelText('메시지 입력', {}, SLOW)
    await user.type(box, 'VPN이 안 돼요{Enter}')
    expect(await screen.findByText('VPN이 안 돼요', { selector: '.msg.u' }, SLOW)).toBeInTheDocument()
  })

  it('Shift+Enter 는 보내지 않고 줄바꿈이다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001')
    const box = await screen.findByLabelText('메시지 입력', {}, SLOW)
    await user.type(box, '첫 줄{Shift>}{Enter}{/Shift}둘째 줄')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(box).toHaveValue('첫 줄\n둘째 줄')
  })

  it('첨부 버튼은 준비 중이라 막혀 있다', async () => {
    renderAs('EMP-1001')
    expect(await screen.findByRole('button', { name: '첨부 파일 (준비 중)' }, SLOW)).toBeDisabled()
  })
})

describe('FAQ', () => {
  it('사이드바에서 FAQ 로 이동하면 목록과 분류가 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001')
    await user.click(await screen.findByRole('button', { name: 'FAQ' }, SLOW))
    expect(await screen.findByText('VPN에 연결할 수 없다고 나와요.', {}, SLOW)).toBeInTheDocument()
    expect(screen.getAllByText('계정·로그인').length).toBeGreaterThan(0)
    expect(screen.getByText('복합기 인쇄가 되지 않아요.')).toBeInTheDocument()
  })

  it('FAQ 를 열면 답변과 근거 Guide 출처가 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/faq')
    await user.click(await screen.findByText('계정이 잠겼어요. 어떻게 해야 하나요?', {}, SLOW))
    expect(screen.getByText(/10분 후 자동으로 해제돼요/)).toBeInTheDocument()
    expect(screen.getByText(/IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3\.2/)).toBeInTheDocument()
  })

  it('"상담하기"를 누르면 새 문의 입력창에 그 질문이 채워진다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/faq')
    await user.click(await screen.findByText('업무용 프로그램은 어디서 설치하나요?', {}, SLOW))
    const buttons = screen.getAllByRole('button', { name: '해결되지 않았어요 · 상담하기' })
    // 열린 항목(세 번째)의 버튼을 누른다
    await user.click(buttons[2])
    expect(await screen.findByLabelText('메시지 입력', {}, SLOW)).toHaveValue('업무용 프로그램은 어디서 설치하나요?')
  })
})
