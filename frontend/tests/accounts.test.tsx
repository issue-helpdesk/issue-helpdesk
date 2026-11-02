/**
 * 관리자 계정 관리 화면 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다.
 * 가상 계정은 30개: 정상 27, 잠김 1(EMP-1037), 이용 제한 2(EMP-1005, EMP-1067).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { MOCK_ACCOUNTS, MOCK_TEMP_PASSWORD, passwordOf } from '../src/api/mock/accounts'
import { mockCreateUser, mockListUsers, mockUpdateUser } from '../src/api/mock/users'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import type { User } from '../src/api/types'

const SLOW = { timeout: 3000 }

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

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const rowOf = async (employeeNo: string) => (await screen.findByText(employeeNo, undefined, SLOW)).closest('tr')!
/** 이름순 첫 쪽(20개)에 없는 계정은 검색해서 불러온다 */
const searchRow = async (employeeNo: string) => {
  await userEvent.type(await screen.findByRole('textbox', { name: '계정 검색' }), employeeNo)
  return rowOf(employeeNo)
}

describe('사용자 관리 API (모의)', () => {
  it('관리자만 쓸 수 있고, 목록은 조건·정렬·쪽으로 읽는다', () => {
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    expect(mockListUsers(staff, {})).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
    const r = mockListUsers(admin(), { size: 5, page: 2, sort: 'employeeNo,desc', accountStatus: ['ACTIVE'] })
    expect(r.ok && r.data.totalCount).toBe(27)
    expect(r.ok && r.data.items).toHaveLength(5)
    expect(r.ok && r.data.totalPages).toBe(6)
    const byDept = mockListUsers(admin(), { q: '네트워크팀' })
    expect(byDept.ok && byDept.data.totalCount).toBe(3)
    expect(mockListUsers(admin(), { sort: 'password,asc' })).toMatchObject({ ok: false, error: { code: 'VALIDATION_ERROR' } })
  })

  it('계정을 만들 때 사번·이메일 중복과 형식을 막고, 만들면 임시 비밀번호로 로그인하는 상태가 된다', () => {
    const base = { employeeNo: 'EMP-2001', name: '시험', email: 'test@itssue.example', serviceRole: 'EMPLOYEE' as const }
    expect(mockCreateUser(admin(), { ...base, employeeNo: 'emp-1001' })).toMatchObject({ error: { code: 'USER_EMPLOYEE_NO_DUPLICATE' } })
    expect(mockCreateUser(admin(), { ...base, email: 'emp-1001@ict.example' })).toMatchObject({ error: { code: 'USER_EMAIL_DUPLICATE' } })
    expect(mockCreateUser(admin(), { ...base, email: 'abc' })).toMatchObject({ error: { code: 'VALIDATION_ERROR', details: [{ field: 'email', reason: 'INVALID_FORMAT' }] } })
    const r = mockCreateUser(admin(), base)
    expect(r.ok && r.data.temporaryPassword).toMatch(/^Tmp#.{8}$/)
    expect(passwordOf('EMP-2001')).toBe(r.ok ? r.data.temporaryPassword : '')
  })

  it('역할·상태를 바꿀 때는 사유가 필수이고, 내 계정은 바꿀 수 없으며, 잠긴 계정을 정상으로 바꾸면 풀린다', () => {
    const me = admin()
    const locked = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1037')!
    expect(mockUpdateUser(me, locked.id, { accountStatus: 'ACTIVE' })).toMatchObject({ error: { code: 'USER_STATUS_REASON_REQUIRED' } })
    expect(mockUpdateUser(me, me.id, { accountStatus: 'INACTIVE', reason: '시험' })).toMatchObject({ error: { code: 'USER_SELF_CHANGE_NOT_ALLOWED' } })
    expect(mockUpdateUser(me, locked.id, { name: '정부장' }).ok).toBe(true) // 이름만 바꾸는 데는 사유가 필요 없다
    expect(mockUpdateUser(me, locked.id, { accountStatus: 'ACTIVE', reason: '본인 확인 완료' }).ok).toBe(true)
    expect(locked.accountStatus).toBe('ACTIVE')
  })
})

describe('계정 관리 화면', () => {
  it('상태별 건수와 20개씩 쪽 나누기가 보이고, 문의자·담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/accounts')
    const seg = await screen.findByRole('group', { name: '상태' })
    await waitFor(() => expect(within(seg).getByRole('button', { name: /^전체 30/ })).toBeInTheDocument(), SLOW)
    expect(within(seg).getByRole('button', { name: /^잠김 1/ })).toBeInTheDocument()
    expect(within(seg).getByRole('button', { name: /^이용 제한 2/ })).toBeInTheDocument()
    expect(await screen.findByText(/1–20 \/ 30건/, undefined, SLOW)).toBeInTheDocument()
    unmount()
    renderAs('EMP-1004', '/accounts')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('검색과 상태 탭으로 줄이고, 시안대로 부서 이름으로도 찾는다', async () => {
    renderAs('EMP-1178', '/accounts')
    await rowOf('EMP-1003')
    await userEvent.type(screen.getByRole('textbox', { name: '계정 검색' }), '네트워크팀')
    await waitFor(() => expect(document.querySelectorAll('.atbl tbody tr')).toHaveLength(3), SLOW)
    await userEvent.clear(screen.getByRole('textbox', { name: '계정 검색' }))
    await userEvent.click(within(screen.getByRole('group', { name: '상태' })).getByRole('button', { name: /^잠김/ }))
    await waitFor(() => expect(document.querySelectorAll('.atbl tbody tr')).toHaveLength(1), SLOW)
    expect(within(await rowOf('EMP-1037')).getByRole('button', { name: '잠금 해제' })).toBeInTheDocument()
  })

  it('이용 제한은 사유를 적어야 걸리고, 걸리면 이력에 남고 제한 해제 버튼이 나온다. 내 계정에는 버튼이 없다', async () => {
    renderAs('EMP-1178', '/accounts')
    expect(within(await searchRow('EMP-1178')).queryByRole('button', { name: '이용 제한' })).toBeNull()
    await userEvent.clear(screen.getByRole('textbox', { name: '계정 검색' }))
    await userEvent.click(within(await rowOf('EMP-1003')).getByRole('button', { name: '이용 제한' }))
    const dlg = await screen.findByRole('dialog', { name: '이용 제한' })
    await userEvent.click(within(dlg).getByRole('button', { name: '확인' }))
    expect(await within(dlg).findByText('사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('사유 (필수)'), '퇴사 예정')
    await userEvent.click(within(dlg).getByRole('button', { name: '확인' }))
    await waitFor(() => expect(within(screen.getByText('EMP-1003').closest('tr')!).getByRole('button', { name: '제한 해제' })).toBeInTheDocument(), SLOW)
    expect(await screen.findByText(/퇴사 예정 · 이건우/)).toBeInTheDocument()
  })

  it('계정을 추가할 때 칸마다 오류를 알리고, 만들면 임시 비밀번호를 한 번 보여 준다', async () => {
    renderAs('EMP-1178', '/accounts')
    await userEvent.click(await screen.findByRole('button', { name: /계정 추가/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '계정 추가' })
    await userEvent.click(within(dlg).getByRole('button', { name: '추가' }))
    expect(within(dlg).getByText('사번을 입력해 주세요.')).toBeInTheDocument()
    expect(within(dlg).getByText('이메일을 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('사번'), 'emp-3001')
    await userEvent.type(within(dlg).getByLabelText('이름'), '새내기')
    await userEvent.type(within(dlg).getByLabelText('이메일'), 'emp-1001@ict.example')
    await userEvent.click(within(dlg).getByRole('button', { name: '추가' }))
    expect(await within(dlg).findByText('이미 등록된 이메일이에요.', undefined, SLOW)).toBeInTheDocument()
    await userEvent.clear(within(dlg).getByLabelText('이메일'))
    await userEvent.type(within(dlg).getByLabelText('이메일'), 'newbie@itssue.example')
    await userEvent.selectOptions(within(dlg).getByLabelText('부서'), '개발1팀')
    await userEvent.click(within(dlg).getByRole('button', { name: '추가' }))
    const tmp = await screen.findByRole('dialog', { name: '임시 비밀번호를 발급했어요' }, SLOW)
    expect(within(tmp).getByLabelText('임시 비밀번호').textContent).toMatch(/^Tmp#/)
    await userEvent.click(within(tmp).getByRole('button', { name: '확인' }))
    expect(await screen.findByText('EMP-3001', undefined, SLOW)).toBeInTheDocument()
  })

  it('정보 수정은 역할을 바꿀 때만 사유가 필요하다', async () => {
    renderAs('EMP-1178', '/accounts')
    await userEvent.click(within(await rowOf('EMP-1003')).getByRole('button', { name: '수정' }))
    const dlg = await screen.findByRole('dialog', { name: '계정 정보 수정' })
    await userEvent.selectOptions(within(dlg).getByLabelText('역할'), 'AGENT')
    await userEvent.click(within(dlg).getByRole('button', { name: '저장' }))
    expect(await within(dlg).findByText('역할을 바꿀 때는 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText(/변경 사유/), '운영 지원')
    await userEvent.click(within(dlg).getByRole('button', { name: '저장' }))
    await waitFor(() => expect(within(screen.getByText('EMP-1003').closest('tr')!).getByText('담당자')).toBeInTheDocument(), SLOW)
  })

  it('임시 비밀번호를 발급하면 한 번만 보여 주고, 잠긴 계정의 잠금도 푼다', async () => {
    renderAs('EMP-1178', '/accounts')
    await userEvent.click(within(await searchRow('EMP-1037')).getByRole('button', { name: '임시 비밀번호 발급' }))
    const dlg = await screen.findByRole('dialog', { name: '임시 비밀번호 재발급' })
    await userEvent.click(within(dlg).getByRole('button', { name: '발급' }))
    const tmp = await screen.findByRole('dialog', { name: '임시 비밀번호를 다시 발급했어요' }, SLOW)
    expect(within(tmp).getByLabelText('임시 비밀번호').textContent).not.toBe(MOCK_TEMP_PASSWORD)
    await userEvent.click(within(tmp).getByRole('button', { name: '확인' }))
    await waitFor(() => expect(MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1037')!.accountStatus).toBe('ACTIVE'), SLOW)
  })
})
