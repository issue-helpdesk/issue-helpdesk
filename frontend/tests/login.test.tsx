/**
 * 로그인 화면과 로그인 전 상담 테스트.
 * 가짜 응답(mock)으로만 실행하며, 실제 서버·키는 사용하지 않는다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { expireLockForDemo } from '../src/api/mock/accounts'
import { tokenStore } from '../src/core/tokenStore'

// 가짜 서버 지연(0.35~0.8초)을 기다리기 위한 넉넉한 대기 시간
const SLOW = { timeout: 3000 }

/** 앱 전체(라우터 + 로그인 상태)를 지정한 주소에서 그린다. */
function renderApp(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('로그인 화면', () => {
  it('시연 계정(문의자)으로 로그인하면 새 문의 화면으로 이동한다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
    expect(screen.getByText(/김서연님/)).toBeInTheDocument()
    expect(tokenStore.get()).toBe('mock.HS1001')
  })

  it('비밀번호가 틀리면 오류를 보여 주고 이동하지 않는다', async () => {
    const user = userEvent.setup()
    renderApp()
    const pw = screen.getByLabelText('비밀번호')
    await user.clear(pw)
    await user.type(pw, 'wrong')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('alert', {}, SLOW)).toHaveTextContent('사번 또는 비밀번호를 확인해 주세요.')
    expect(screen.queryByRole('heading', { name: '새 문의' })).not.toBeInTheDocument()
  })

  it('사번이나 비밀번호가 비어 있으면 서버 호출 없이 안내한다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.clear(screen.getByLabelText('사번'))
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(screen.getByRole('alert')).toHaveTextContent('사번과 비밀번호를 입력해 주세요.')
  })

  it('이용 제한 계정은 로그인할 수 없고 서비스데스크 연락처를 안내한다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: '이용 제한 계정' }))
    expect(await screen.findByRole('alert', {}, SLOW)).toHaveTextContent('내선 1000')
    expect(tokenStore.get()).toBeNull()
  })

  it('잠긴 계정은 로그인할 수 없고 남은 시간과 서비스데스크 연락처를 안내한다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: '잠김 계정' }))
    const alert = await screen.findByRole('alert', {}, SLOW)
    expect(alert).toHaveTextContent('잠긴 계정이에요')
    expect(alert).toHaveTextContent('분 후 자동으로 해제')
    expect(alert).toHaveTextContent('내선 1000')
    expect(tokenStore.get()).toBeNull()
  })

  it('비밀번호를 5회 틀리면 계정이 잠기고, 이후에는 올바른 비밀번호도 막는다', async () => {
    const user = userEvent.setup()
    renderApp()
    const pw = screen.getByLabelText('비밀번호')
    await user.clear(pw)
    await user.type(pw, 'wrong')
    for (let k = 1; k <= 5; k++) {
      await user.click(screen.getByRole('button', { name: '로그인' }))
      const alert = await screen.findByRole('alert', {}, SLOW)
      if (k < 5) expect(alert).toHaveTextContent('사번 또는 비밀번호를 확인해 주세요.')
      else expect(alert).toHaveTextContent('5회 실패로 계정이 잠겼어요')
      await screen.findByRole('button', { name: '로그인' }, SLOW) // 요청이 끝나 버튼이 다시 활성화될 때까지
    }
    // 올바른 비밀번호로 시도해도 잠긴 동안은 로그인할 수 없다
    await user.clear(pw)
    await user.type(pw, 'demo')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('alert', {}, SLOW)).toHaveTextContent('잠긴 계정이에요')
    expect(tokenStore.get()).toBeNull()
  }, 20000)

  it('4회까지 틀려도 잠기지 않고, 올바르게 입력하면 로그인된다', async () => {
    const user = userEvent.setup()
    renderApp()
    const pw = screen.getByLabelText('비밀번호')
    await user.clear(pw)
    await user.type(pw, 'wrong')
    for (let k = 1; k <= 4; k++) {
      await user.click(screen.getByRole('button', { name: '로그인' }))
      await screen.findByRole('alert', {}, SLOW)
      await screen.findByRole('button', { name: '로그인' }, SLOW)
    }
    await user.clear(pw)
    await user.type(pw, 'demo')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
  }, 20000)

  it('잠금 후 10분이 지나면 다시 로그인할 수 있다', async () => {
    const user = userEvent.setup()
    renderApp()
    expireLockForDemo('HS1530') // 10분이 지난 것처럼 만든다
    await user.click(screen.getByRole('button', { name: '잠김 계정' }))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
    expect(tokenStore.get()).toBe('mock.HS1530')
  })

  it('로그인 화면에 승인 대기 계정 버튼은 없다', () => {
    renderApp()
    expect(screen.queryByRole('button', { name: /승인 대기/ })).not.toBeInTheDocument()
  })

  it('역할에 따라 첫 화면이 다르다 (담당자=처리할 문의, 관리자=대시보드)', async () => {
    const user = userEvent.setup()
    const { unmount } = renderApp()
    await user.click(screen.getByRole('button', { name: '담당자' }))
    expect(await screen.findByRole('heading', { name: '처리할 문의' }, SLOW)).toBeInTheDocument()
    unmount()
    tokenStore.clear()
    renderApp()
    await user.click(screen.getByRole('button', { name: '관리자' }))
    expect(await screen.findByRole('heading', { name: '대시보드' }, SLOW)).toBeInTheDocument()
  })

  it('SSO 탭에서 시연 로그인을 할 수 있다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('tab', { name: 'SSO 로그인' }))
    await user.click(screen.getByRole('button', { name: 'SSO로 계속하기 (시연)' }))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
  })

  it('로그인하지 않고 보호된 화면에 들어가면 로그인 화면으로 보낸다', () => {
    renderApp('/dash')
    expect(screen.getByRole('heading', { name: 'IT 문제, 먼저 물어보세요' })).toBeInTheDocument()
  })

  it('저장된 토큰이 있으면 새로고침 후에도 로그인 상태를 유지한다', async () => {
    tokenStore.set('mock.HS0912')
    renderApp('/login')
    expect(await screen.findByRole('heading', { name: '대시보드' }, SLOW)).toBeInTheDocument()
  })

  it('로그아웃하면 로그인 화면으로 돌아가고 토큰을 지운다', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: '로그인' }))
    await screen.findByRole('heading', { name: '새 문의' }, SLOW)
    await user.click(screen.getByRole('button', { name: '로그아웃' }))
    expect(screen.getByRole('heading', { name: 'IT 문제, 먼저 물어보세요' })).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })
})

describe('로그인 전 상담', () => {
  it('계정 잠금 질문에는 근거 Guide 출처와 함께 답한다', async () => {
    const user = userEvent.setup()
    renderApp()
    const panel = screen.getByRole('region', { name: '로그인 전 상담' })
    await user.click(within(panel).getByRole('button', { name: '계정이 잠겼어요' }))
    expect(await within(panel).findByText(/10분 후 자동으로 해제/, {}, SLOW)).toBeInTheDocument()
    expect(within(panel).getByText(/IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3\.2/)).toBeInTheDocument()
  })

  it('범위 밖 질문은 근거 없이 답하지 않고 로그인 후 문의·서비스데스크로 안내한다', async () => {
    const user = userEvent.setup()
    renderApp()
    const panel = screen.getByRole('region', { name: '로그인 전 상담' })
    await user.type(within(panel).getByLabelText('로그인 전 상담 입력'), '프린터가 안 나와요{Enter}')
    expect(await within(panel).findByText(/상담 범위\(계정·로그인\)를 벗어나요/, {}, SLOW)).toBeInTheDocument()
    expect(within(panel).getByText(/내선 1000/)).toBeInTheDocument()
  })

  it('보안 사고가 의심되면 로그인 후 담당자 연결을 안내한다', async () => {
    const user = userEvent.setup()
    renderApp()
    const panel = screen.getByRole('region', { name: '로그인 전 상담' })
    await user.type(within(panel).getByLabelText('로그인 전 상담 입력'), '피싱 메일 링크를 눌렀어요{Enter}')
    expect(await within(panel).findByText(/로그인 후 새 문의/, {}, SLOW)).toBeInTheDocument()
  })
})
