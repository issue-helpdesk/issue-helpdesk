/**
 * 관리자 전체 문의 (EMP-1178 이건우). 가짜 서버(mock)로만 실행한다.
 * 담당 그룹 6개의 시연 접수(네트워크팀 16 + 다른 그룹 23) 위에 문의자 시연 접수 1건이 더해진다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { listAiInquiries } from '../src/api/inquiries'
import { listCandidates } from '../src/api/reference'
import { listTickets, reassignTicket } from '../src/api/tickets'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
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
const rows = () => [...document.querySelectorAll('.tbl tbody tr')] as HTMLElement[]

describe('전체 문의 API (모의)', () => {
  it('관리자는 모든 담당 그룹의 접수를 보고 팀·상태·배정 전으로 거른다', async () => {
    const all = await listTickets(admin(), { view: 'ALL', size: 100 })
    expect(all.ok && all.data.totalCount).toBeGreaterThanOrEqual(40)
    const groups = new Set(all.ok ? all.data.items.map((t) => t.group?.name) : [])
    expect(groups).toEqual(new Set(['네트워크팀', '서비스데스크', '엔드포인트지원팀', '시스템인프라팀', '업무시스템팀', '정보보안팀']))
    const infra = await listTickets(admin(), { view: 'ALL', size: 100, groupId: 4 })
    expect(infra.ok && infra.data.items.every((t) => t.group?.name === '시스템인프라팀')).toBe(true)
    const pre = await listTickets(admin(), { view: 'ALL', size: 100, jiraSyncStatus: ['PENDING', 'VERIFYING', 'NEEDS_ADMIN'] })
    expect(pre.ok && pre.data.items.map((t) => t.workStatus)).toEqual([null, null])
  })

  it('AI 처리한 상담은 구분별 건수와 기간으로 걸러 읽는다', async () => {
    const r = await listAiInquiries({ size: 20 })
    expect(r.ok && r.data.counts.all).toBe(r.ok ? r.data.counts.ok + r.data.counts.pend + r.data.counts.unr : -1)
    expect(r.ok && r.data.counts.all).toBeGreaterThan(270)
    const today = await listAiInquiries({ per: 'd' })
    expect(today.ok && today.data.counts.all).toBeLessThan(r.ok ? r.data.counts.all : 0)
    const unr = await listAiInquiries({ kind: 'unr' })
    expect(unr.ok && unr.data.items.every((x) => x.kind === 'unr')).toBe(true)
  })

  it('AI 처리 상담은 제목·번호·가이드 검색과 분류로 거르고, 건수는 기간만 따른다', async () => {
    const all = await listAiInquiries({ size: 100 })
    const base = all.ok ? all.data.counts.all : 0
    const byTitle = await listAiInquiries({ q: '계정 잠금', size: 100 })
    expect(byTitle.ok && byTitle.data.items.length).toBeGreaterThan(0)
    expect(byTitle.ok && byTitle.data.items.every((r) => r.title.includes('계정 잠금'))).toBe(true)
    const byGuide = await listAiInquiries({ q: 'IT-NET-001', size: 100 })
    expect(byGuide.ok && byGuide.data.items.every((r) => r.categoryCode === 'NET')).toBe(true)
    const cat = await listAiInquiries({ categoryCode: 'HW', size: 100 })
    expect(cat.ok && cat.data.items.every((r) => r.categoryCode === 'HW')).toBe(true)
    expect(cat.ok && cat.data.counts.all).toBe(base) // 구분 건수는 분류·검색에 영향받지 않는다
  })

  it('재배정은 관리자만, 처리 대기·처리 중인 접수만, 사유와 Jira 연결된 같은 그룹 담당자만', async () => {
    const a = admin()
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    const wip = await listTickets(a, { view: 'ALL', size: 100, groupId: 1, workStatus: ['WIP'] }) // 서비스데스크 처리 중
    const t = wip.ok ? wip.data.items[0] : undefined
    expect(t).toBeDefined()
    const other = t!.assignee!.id === 410 ? 411 : 410
    expect(await reassignTicket(staff, t!.id, { assigneeId: other, reason: '시험' })).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
    expect(await reassignTicket(a, t!.id, { assigneeId: other, reason: ' ' })).toMatchObject({ ok: false, error: { code: 'VALIDATION_ERROR' } })
    expect(await reassignTicket(a, t!.id, { assigneeId: 2, reason: '다른 그룹' })).toMatchObject({ ok: false, error: { code: 'ASSIGNEE_NOT_ASSIGNABLE' } })
    const r = await reassignTicket(a, t!.id, { assigneeId: other, reason: '휴가' })
    expect(r.ok && r.data.assignee?.id).toBe(other)
    expect(r.ok && r.data.workStatus).toBe('WIP') // 진행 상태는 그대로
    const fin = await listTickets(a, { view: 'ALL', size: 100, workStatus: ['FIN'] })
    expect(await reassignTicket(a, fin.ok ? fin.data.items[0].id : 0, { assigneeId: other, reason: '시험' })).toMatchObject({ ok: false, error: { code: 'TICKET_INVALID_TRANSITION' } })
    const c = await listCandidates('서비스데스크')
    expect(c.ok && c.data.find((x) => x.id === other)).toMatchObject({ avail: true, jira: true })
  })
})

describe('전체 문의 화면', () => {
  it('상태 탭 건수와 팀 필터, 담당 열이 보이고, 문의자·담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/tickets')
    const seg = await screen.findByRole('group', { name: '처리 상태' }, SLOW)
    await waitFor(() => expect(within(seg).getByRole('button', { name: /^배정 전 2/ })).toBeInTheDocument(), SLOW)
    expect(within(seg).getByRole('button', { name: /^전체 \d+/ })).toBeInTheDocument()
    expect(await screen.findByRole('columnheader', { name: /담당/ }, SLOW)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^팀\s*전체/ }))
    await userEvent.click(await screen.findByRole('option', { name: '시스템인프라팀' }))
    await waitFor(() => {
      expect(rows().length).toBeGreaterThan(0)
      expect(rows().every((r) => within(r).queryByText('시스템인프라팀'))).toBe(true)
    }, SLOW)
    unmount()
    renderAs('EMP-1004', '/tickets')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('배정 전 탭은 Jira 생성 전 접수를 접수 완료·확인 중 상태로 보여 준다', async () => {
    renderAs('EMP-1178', '/tickets')
    await userEvent.click(await screen.findByRole('button', { name: /^배정 전/ }, SLOW))
    await waitFor(() => expect(rows()).toHaveLength(2), SLOW)
    expect(within(document.body).getByText('접수 완료')).toBeInTheDocument()
    expect(within(document.body).getByText('생성 여부 확인 중')).toBeInTheDocument()
    expect(rows().every((r) => within(r).getByText('배정 전'))).toBe(true)
  })

  it('검색은 담당자 이름으로도 찾고, 조건을 걸면 필터 해제 버튼이 생긴다', async () => {
    renderAs('EMP-1178', '/tickets')
    await screen.findByRole('textbox', { name: '전체 문의 검색' }, SLOW)
    await userEvent.type(screen.getByRole('textbox', { name: '전체 문의 검색' }), '곽지민')
    await waitFor(() => expect(rows().length).toBeGreaterThan(0), SLOW)
    expect(rows().every((r) => within(r).queryByText('곽지민'))).toBe(true)
    expect(screen.queryByRole('button', { name: /필터 해제/ })).toBeNull() // 검색어만으로는 조건 칩이 없다
    await userEvent.click(screen.getByRole('button', { name: /^긴급도\s*전체/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'P1·P2 · 긴급·높음' }))
    expect(await screen.findByRole('button', { name: '✕ 필터 해제' })).toBeInTheDocument()
  })

  it('AI 처리 보기: 구분 탭 건수와 구분별 목록이 나온다', async () => {
    renderAs('EMP-1178', '/tickets')
    await userEvent.click(await screen.findByRole('button', { name: 'AI 처리' }, SLOW))
    const chips = await screen.findByRole('group', { name: 'AI 상담 결과 구분' }, SLOW)
    await waitFor(() => expect(within(chips).getByRole('button', { name: /^전체 \d+/ })).toBeInTheDocument(), SLOW)
    expect(await screen.findByRole('columnheader', { name: /사용한 가이드/ })).toBeInTheDocument()
    await userEvent.click(within(chips).getByRole('button', { name: /^미해결 종료/ }))
    await waitFor(() => {
      expect(rows().length).toBeGreaterThan(0)
      expect(rows().every((r) => within(r).queryByText('미해결 종료'))).toBe(true)
    }, SLOW)
  })

  it('AI 처리 보기에도 검색과 분류 필터가 있고, 조건을 걸면 필터 해제가 생긴다', async () => {
    renderAs('EMP-1178', '/tickets')
    await userEvent.click(await screen.findByRole('button', { name: 'AI 처리' }, SLOW))
    const box = await screen.findByRole('textbox', { name: 'AI 처리 검색' }, SLOW)
    await waitFor(() => expect(rows().length).toBeGreaterThan(0), SLOW)
    await userEvent.type(box, '모니터')
    await waitFor(() => {
      expect(rows().length).toBeGreaterThan(0)
      expect(rows().every((r) => within(r).queryByText(/모니터/))).toBe(true)
    }, SLOW)
    await userEvent.clear(box)
    await userEvent.click(screen.getByRole('button', { name: /^분류\s*전체/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'VPN·네트워크' }))
    await waitFor(() => expect(rows().every((r) => within(r).queryByText('VPN·네트워크'))).toBe(true), SLOW)
    expect(await screen.findByRole('button', { name: '✕ 필터 해제' })).toBeInTheDocument()
  })

  it('상세를 열면 관리자는 상태 버튼 없이 재배정만 하고, 사유와 담당자를 골라 바꾼다', async () => {
    renderAs('EMP-1178', '/tickets')
    await userEvent.click(await screen.findByRole('button', { name: '계정 잠금 해제 요청' }, SLOW))
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    expect(within(panel).queryByRole('button', { name: /처리 시작|처리 결과 등록/ })).toBeNull()
    expect(within(panel).queryByText(/다른 담당자가 맡은 접수예요/)).toBeNull()
    await userEvent.click(await within(panel).findByRole('button', { name: '담당자 재배정' }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '담당자 재배정' })
    expect(await within(dlg).findByText('추천 (가용 + 업무량 최소)', undefined, SLOW)).toBeInTheDocument()
    expect(within(dlg).getByText('부재 (연차)')).toBeInTheDocument() // 최하은
    await userEvent.click(within(dlg).getByRole('button', { name: '재배정' }))
    expect(await within(dlg).findByText('재배정 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('재배정 사유 (필수)'), '업무량 조정')
    await userEvent.click(within(dlg).getByRole('button', { name: '재배정' }))
    expect(await screen.findByText('재배정했어요. 진행 상태는 그대로 유지돼요.', undefined, SLOW)).toBeInTheDocument()
  })
})
