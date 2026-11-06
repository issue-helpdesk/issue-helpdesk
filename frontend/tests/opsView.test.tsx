/**
 * 관리자 운영 현황 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다.
 * 모의 접수에는 긴급 P1(처리 중), 당일 미종결 P2, ITSM 생성 확인 2건, 상태 동기화 확인 1건, 담당자 배정 확인 2건이 들어 있다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { getOpsSnapshot, recheckTransition, retryJiraCreate } from '../src/api/ops'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import type { User } from '../src/api/types'

const WHY = 'ITSM 장애 복구 후 재처리'
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
const staff = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
const section = (name: RegExp) => screen.getByRole('heading', { name }).closest('section') as HTMLElement

describe('운영 현황 API (모의)', () => {
  it('긴급·예외·연동 확인·배정 확인 목록을 나눠 준다', async () => {
    const r = await getOpsSnapshot(admin())
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data.urgent.length).toBeGreaterThan(0)
    expect(r.data.urgent.every((t) => t.urgency === 'P1' && (t.workStatus === 'RDY' || t.workStatus === 'WIP'))).toBe(true)
    // 당일 미종결 예외: P1·P2, 접수일이 오늘 이전, 긴급 목록(P1 진행 중)과 겹치지 않는다
    expect(r.data.exception.length).toBeGreaterThan(0)
    expect(r.data.exception.every((t) => t.urgency === 'P1' || t.urgency === 'P2')).toBe(true)
    const urgentIds = new Set(r.data.urgent.map((t) => t.id))
    expect(r.data.exception.some((t) => urgentIds.has(t.id))).toBe(false)
    expect(r.data.link.every((t) => t.jiraSyncStatus !== 'SYNCED' || t.transitionStatus === 'NEEDS_ADMIN')).toBe(true)
    expect(r.data.assign.every((t) => t.jiraSyncStatus === 'SYNCED' && t.assignStatus === 'NEEDS_ADMIN')).toBe(true)
    expect(r.data.link.length).toBe(3)
    expect(r.data.assign.length).toBe(2)
  })

  it('담당 그룹으로 좁힌다', async () => {
    const all = await getOpsSnapshot(admin())
    const infra = await getOpsSnapshot(admin(), 4)
    expect(all.ok && infra.ok).toBe(true)
    if (!all.ok || !infra.ok) return
    const groups = [...infra.data.urgent, ...infra.data.exception, ...infra.data.link, ...infra.data.assign].map((t) => t.group?.id)
    expect(groups.every((g) => g === 4)).toBe(true)
    expect(infra.data.link.length).toBeLessThan(all.data.link.length)
  })

  it('ITSM 생성 확인·재시도는 이슈를 만들고 가장 한가한 근무자에게 자동 배정한다', async () => {
    const before = await getOpsSnapshot(admin())
    if (!before.ok) throw new Error('목록 실패')
    const target = before.data.link.find((t) => t.jiraSyncStatus === 'NEEDS_ADMIN')!
    const r = await retryJiraCreate(admin(), target.id, WHY)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data.jiraKey).toMatch(/^ITHD-\d+$/)
    expect(r.data.workStatus).toBe('RDY')
    expect(r.data.jiraSyncStatus).toBe('SYNCED')
    // 같은 그룹에서 근무 중이고 ITSM 계정이 있는 사람(김수아는 ITSM 미연결)
    expect(r.data.assignee?.name).toBeTruthy()
    expect(r.data.assignee?.name).not.toBe('김수아')
    const again = await retryJiraCreate(admin(), target.id, WHY)
    expect(again.ok).toBe(false)
    const after = await getOpsSnapshot(admin())
    expect(after.ok && after.data.link.some((t) => t.id === target.id)).toBe(false)
  })

  it('상태 동기화 확인은 요청한 상태로 반영하고, 대상이 아니면 막는다', async () => {
    const before = await getOpsSnapshot(admin())
    if (!before.ok) throw new Error('목록 실패')
    const target = before.data.link.find((t) => t.transitionStatus === 'NEEDS_ADMIN')!
    expect(target.requestedWorkStatus).toBe('FIN')
    const r = await recheckTransition(admin(), target.id, WHY)
    expect(r.ok && r.data.workStatus).toBe('FIN')
    expect(r.ok && r.data.transitionStatus).toBe('IDLE')
    expect((await recheckTransition(admin(), target.id, WHY)).ok).toBe(false)
  })

  it('관리자만 확인할 수 있다', async () => {
    const r = await retryJiraCreate(staff(), 5037, WHY)
    expect(r.ok).toBe(false)
  })
})

describe('운영 현황 화면', () => {
  it('구역별 건수와 팀별 개인 현황이 보이고, 문의자·담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/ops')
    expect(await screen.findByRole('heading', { name: '운영 현황', level: 1 }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(section(/긴급 조치 필요/).querySelectorAll('.orow').length).toBeGreaterThan(0), SLOW)
    expect(within(section(/티켓 연동 확인/)).getByText(/^\d+건$/)).toBeInTheDocument()
    expect(within(section(/담당자 배정 확인/)).getByText(/^\d+건$/)).toBeInTheDocument()
    expect(section(/티켓 연동 확인/)).toHaveClass('need')
    // 팀별 개인 현황은 캘린더 화면 맨 아래로 옮겼다
    expect(screen.queryByRole('group', { name: '담당 그룹' })).toBeNull()
    unmount()
    renderAs('EMP-1004', '/ops')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('나머지 건 보기·접기가 되고, 담당 그룹을 고르면 목록이 줄어든다', async () => {
    renderAs('EMP-1178', '/ops')
    await waitFor(() => expect(section(/긴급 조치 필요/).querySelectorAll('.orow').length).toBeGreaterThan(0), SLOW)
    const exc = () => section(/당일 미종결 예외/).querySelectorAll('.orow').length
    expect(exc()).toBe(3)
    await userEvent.click(within(section(/당일 미종결 예외/)).getByRole('button', { name: /^나머지 \d+건 보기/ }))
    expect(exc()).toBeGreaterThan(3)
    await userEvent.click(within(section(/당일 미종결 예외/)).getByRole('button', { name: '접기' }))
    expect(exc()).toBe(3)
    await userEvent.click(screen.getByRole('button', { name: /^담당 그룹\s*전체/ }))
    await userEvent.click(await screen.findByRole('option', { name: '정보보안팀' }))
    await waitFor(() => expect(within(section(/티켓 연동 확인/)).getByText('0건')).toBeInTheDocument(), SLOW)
    expect(within(section(/티켓 연동 확인/)).getByText('연동 확인이 필요한 건이 없어요.')).toBeInTheDocument()
  })

  it('ITSM 생성 확인·재시도를 누르면 최근 처리 결과에 남는다', async () => {
    renderAs('EMP-1178', '/ops')
    await waitFor(() => expect(section(/티켓 연동 확인/).querySelectorAll('.orow').length).toBeGreaterThan(0), SLOW)
    const row = section(/티켓 연동 확인/).querySelector('.orow.l') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: '확인' }))
    const dlg = await screen.findByRole('dialog')
    // 어떤 문제인지 카드로 보이고, 사유가 없으면 막는다
    expect(within(dlg).getByLabelText('확인이 필요한 내용')).toBeInTheDocument()
    const go = within(dlg).getByRole('button', { name: /^ITSM (생성 확인·재시도|상태 확인·다시 반영)$/ })
    await userEvent.click(go)
    expect(await within(dlg).findByText('재처리 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText(/재처리 사유/), WHY)
    await userEvent.click(go)
    const done = await screen.findByRole('region', { name: '최근 처리 결과' }, SLOW)
    expect(within(done).getByRole('button', { name: '처리 이력 보기' })).toBeInTheDocument()
    // 요청 직후 그 줄의 버튼은 "처리 중"이었다가 반영되면 "완료"가 된다
    expect(await within(done).findByText('완료', {}, SLOW)).toBeInTheDocument()
  })

  it('담당자 지정은 후보를 고르고 사유를 적어야 한다', async () => {
    renderAs('EMP-1178', '/ops')
    await waitFor(() => expect(section(/담당자 배정 확인/).querySelectorAll('.orow').length).toBeGreaterThan(0), SLOW)
    await userEvent.click(within(section(/담당자 배정 확인/)).getAllByRole('button', { name: '지정' })[0])
    const dlg = await screen.findByRole('dialog', {}, SLOW)
    expect(within(dlg).getByText('지정 사유 (필수)')).toBeInTheDocument()
    expect(await within(dlg).findByText('자동배정 추천 (가용 + 업무량 최소)', {}, SLOW)).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('button', { name: '지정' }))
    expect(await within(dlg).findByText('지정 사유를 입력해 주세요.')).toBeInTheDocument()
    // 자주 쓰는 사유를 누르면 입력칸이 채워지고 직접 고쳐 쓸 수도 있다
    await userEvent.click(within(dlg).getByRole('button', { name: '휴가·부재 대체' }))
    expect(within(dlg).getByLabelText('지정 사유 (필수)')).toHaveValue('휴가·부재 대체')
    expect(within(dlg).getByRole('button', { name: '휴가·부재 대체' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(dlg).queryByText('지정 사유를 입력해 주세요.')).toBeNull()
    await userEvent.clear(within(dlg).getByLabelText('지정 사유 (필수)'))
    await userEvent.type(within(dlg).getByLabelText('지정 사유 (필수)'), '자동배정 실패')
    await userEvent.click(within(dlg).getByRole('button', { name: '지정' }))
    const done = await screen.findByRole('region', { name: '최근 처리 결과' }, SLOW)
    expect(within(done).getByText(/담당자를 지정했어요/)).toBeInTheDocument()
  })
})
