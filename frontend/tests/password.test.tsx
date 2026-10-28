/**
 * 비밀번호 창 테스트: 임시 비밀번호 직후 팝업 · 내 프로필 · 비밀번호 변경 · 로그인 만료 안내.
 * 가짜 응답(mock)으로만 실행한다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { MOCK_TEMP_PASSWORD } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

function renderApp(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** 임시 비밀번호 계정으로 로그인해 "새 비밀번호를 정해 주세요" 창이 뜬 상태 */
async function loginTemp() {
  const user = userEvent.setup()
  renderApp()
  const id = screen.getByLabelText('사번')
  await user.clear(id)
  await user.type(id, 'EMP-1010')
  const pw = screen.getByLabelText('비밀번호')
  await user.clear(pw)
  await user.type(pw, MOCK_TEMP_PASSWORD)
  await user.click(screen.getByRole('button', { name: '로그인' }))
  const dialog = await screen.findByRole('dialog', { name: '새 비밀번호를 정해 주세요' }, SLOW)
  return { user, dialog }
}

describe('임시 비밀번호 직후', () => {
  it('로그인하면 닫을 수 없는 새 비밀번호 창이 뜨고, 로그아웃만 할 수 있다', async () => {
    const { user, dialog } = await loginTemp()
    expect(within(dialog).queryByRole('button', { name: '닫기' })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '로그아웃' })).toBeInTheDocument()
    // Esc 로도 닫히지 않는다
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '새 비밀번호를 정해 주세요' })).toBeInTheDocument()
    // 로그아웃하면 안내 없이 로그인 화면으로 돌아간다
    await user.click(within(dialog).getByRole('button', { name: '로그아웃' }))
    expect(await screen.findByRole('button', { name: '로그인' })).toBeInTheDocument()
    expect(screen.queryByText('비밀번호를 바꿨어요.')).not.toBeInTheDocument()
  })

  it('현재 → 규칙 → 확인 순서로 오류를 입력칸 아래에 보여 준다', async () => {
    const { user, dialog } = await loginTemp()
    const cur = within(dialog).getByLabelText('현재 비밀번호')
    const nw = within(dialog).getByLabelText('새 비밀번호')
    const cf = within(dialog).getByLabelText('새 비밀번호 확인')
    const submit = () => user.click(within(dialog).getByRole('button', { name: '비밀번호 변경' }))

    // 현재 비밀번호가 비어 있으면 그것만 알린다
    await submit()
    expect(cur).toHaveAccessibleDescription('현재 비밀번호를 입력해 주세요.')

    // 규칙 위반은 여러 개면 모두 보인다
    await user.type(cur, MOCK_TEMP_PASSWORD)
    await user.type(nw, 'abc')
    await submit()
    expect(nw).toHaveAccessibleDescription(/8자 이상 입력해 주세요\..*3종류 이상을 섞어 주세요\./)

    // 사번과 같은 값
    await user.clear(nw)
    await user.type(nw, 'EMP-1010')
    await submit()
    expect(nw).toHaveAccessibleDescription(/현재 비밀번호나 사번과 다른 값을 입력해 주세요\./)

    // 규칙을 지켰지만 확인이 다르면 확인 칸 아래에 알린다
    await user.clear(nw)
    await user.type(nw, 'NewPass!234')
    await user.type(cf, 'NewPass!235')
    await submit()
    expect(cf).toHaveAccessibleDescription('새 비밀번호가 서로 달라요.')

    // 현재 비밀번호가 틀리면 서버가 알려 준다
    await user.clear(cur)
    await user.type(cur, 'wrong-pass')
    await user.clear(cf)
    await user.type(cf, 'NewPass!234')
    await submit()
    expect(await within(dialog).findByText('현재 비밀번호가 맞지 않아요.', {}, SLOW)).toBeInTheDocument()
  })

  it('비밀번호를 바꾸면 로그인 화면에서 안내가 보이고, 새 비밀번호로 로그인하면 창이 뜨지 않는다', async () => {
    const { user, dialog } = await loginTemp()
    await user.type(within(dialog).getByLabelText('현재 비밀번호'), MOCK_TEMP_PASSWORD)
    await user.type(within(dialog).getByLabelText('새 비밀번호'), 'NewPass!234')
    await user.type(within(dialog).getByLabelText('새 비밀번호 확인'), 'NewPass!234')
    await user.click(within(dialog).getByRole('button', { name: '비밀번호 변경' }))
    const done = await screen.findByRole('dialog', { name: '비밀번호 변경' }, SLOW)
    expect(done).toHaveTextContent('모든 기기에서 로그아웃돼요')
    expect(within(done).queryByRole('button', { name: '닫기' })).not.toBeInTheDocument()
    await user.click(within(done).getByRole('button', { name: '로그인 화면으로' }))

    expect(await screen.findByText('비밀번호를 바꿨어요.')).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
    const pw = screen.getByLabelText('비밀번호')
    await user.clear(pw)
    await user.type(pw, 'NewPass!234')
    const id = screen.getByLabelText('사번')
    await user.clear(id)
    await user.type(id, 'EMP-1010')
    await user.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('내 프로필', () => {
  it('사이드바의 이름 영역으로 열고 ✕ 로 닫으며, 닫으면 그 버튼으로 초점이 돌아간다', async () => {
    const user = userEvent.setup()
    tokenStore.set('mock.EMP-1001')
    renderApp('/new')
    const open = await screen.findByRole('button', { name: '내 프로필 열기' }, SLOW)
    await user.click(open)
    const dialog = await screen.findByRole('dialog', { name: '내 프로필' })
    expect(dialog).toHaveTextContent('김서연')
    expect(dialog).toHaveTextContent('EMP-1001')
    expect(dialog).toHaveTextContent('개발1팀')
    expect(dialog).toHaveTextContent('마지막 변경 후 38일')
    // 입력칸은 [변경]을 눌러야 펼쳐진다
    expect(within(dialog).queryByLabelText('현재 비밀번호')).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '변경' }))
    expect(within(dialog).getByLabelText('현재 비밀번호')).toHaveFocus()
    expect(within(dialog).getByText(/8~64자, 영문 대·소문자·숫자·특수문자 중 3종류 이상/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '닫기' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(open).toHaveFocus()
  })

  it('임시 비밀번호 상태가 아니면 로그인해도 창이 자동으로 뜨지 않는다', async () => {
    tokenStore.set('mock.EMP-1001')
    renderApp('/new')
    await screen.findByRole('heading', { name: '새 문의' }, SLOW)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('로그인 만료 안내', () => {
  it('저장된 로그인이 더는 유효하지 않으면 로그인 화면 맨 위에 한 줄로 알린다', async () => {
    tokenStore.set('mock.NOBODY')
    renderApp('/new')
    expect(await screen.findByText('로그인이 만료됐어요.', {}, SLOW)).toBeInTheDocument()
    expect(screen.getByText(/일정 시간이 지나면 다시 로그인해야 해요/)).toBeInTheDocument()
    // 별도 창은 뜨지 않는다
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
