/**
 * 캘린더(부재 일정) 화면: 담당자·관리자만 들어오고, 관리자에게만 "내 일정/전체" 전환이 있으며, 등록·삭제는 본인 일정만 한다.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App'
import { createTimeOff, listTimeOff, resetMockTimeOff, ymd } from '../src/api/timeOff'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const ME = { id: 7, employeeNo: 'EMP-1004', name: '성민경' } as User

function renderAt(path: string, employeeNo: string) {
  tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => resetMockTimeOff())

describe('캘린더 화면', () => {
  it('담당자는 달력과 목록을 보고, "내 일정/전체" 전환은 없다', async () => {
    renderAt('/calendar', 'EMP-1004')
    expect((await screen.findAllByRole('heading', { name: '캘린더' }, SLOW)).length).toBeGreaterThan(0)
    expect(screen.getByRole('grid')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '보기 범위' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '일정 등록' })).toBeInTheDocument()
  })

  it('관리자에게만 "내 일정 / 전체" 전환이 있다', async () => {
    renderAt('/calendar', 'EMP-1178')
    const g = await screen.findByRole('group', { name: '보기 범위' }, SLOW)
    expect(within(g).getByRole('button', { name: '내 일정' })).toBeInTheDocument()
    expect(within(g).getByRole('button', { name: '전체' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('문의자는 들어올 수 없고 자기 첫 화면으로 돌아간다', async () => {
    renderAt('/calendar', 'EMP-1001')
    expect(await screen.findByRole('heading', { name: '새 문의' }, SLOW)).toBeInTheDocument()
  })

  it('사이드바 메뉴 이름은 "캘린더"다', async () => {
    renderAt('/calendar', 'EMP-1004')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(within(nav).getByRole('button', { name: '캘린더' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).queryByText('부재 일정')).not.toBeInTheDocument()
  })

  it('일정을 등록하면 목록에 나타나고, 삭제하면 사라진다', async () => {
    const user = userEvent.setup()
    renderAt('/calendar', 'EMP-1004')
    await user.click(await screen.findByRole('button', { name: '일정 등록' }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '부재 일정 등록' })
    await user.type(within(dlg).getByLabelText('메모 (선택)'), '치과 진료')
    await user.click(within(dlg).getByRole('button', { name: '등록' }))
    expect(await screen.findByText('치과 진료', {}, SLOW)).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /연차 삭제$/ })[0])
    const ask = await screen.findByRole('alertdialog')
    await user.click(within(ask).getByRole('button', { name: '삭제' }))
    await screen.findByText('부재 일정을 삭제했어요.', {}, SLOW)
  })
})

describe('부재 일정 API (모의)', () => {
  const today = ymd(new Date())
  it('기간이 겹치는 일정은 등록할 수 없다 (같은 날 오전·오후 반차는 함께 가능)', async () => {
    await listTimeOff(ME, today, today)
    const a = await createTimeOff(ME, { timeOffType: 'HALF_AM', startDate: '2031-03-03', endDate: '2031-03-03' })
    expect(a.ok).toBe(true)
    const b = await createTimeOff(ME, { timeOffType: 'HALF_PM', startDate: '2031-03-03', endDate: '2031-03-03' })
    expect(b.ok).toBe(true)
    const c = await createTimeOff(ME, { timeOffType: 'ANNUAL', startDate: '2031-03-02', endDate: '2031-03-04' })
    expect(!c.ok && c.error.code).toBe('TIME_OFF_OVERLAP')
  })

  it('종료일이 시작일보다 빠르면 종료일 오류를 준다', async () => {
    const r = await createTimeOff(ME, { timeOffType: 'ANNUAL', startDate: '2031-04-05', endDate: '2031-04-01' })
    expect(!r.ok && r.error.details?.[0]?.field).toBe('endDate')
  })
})
