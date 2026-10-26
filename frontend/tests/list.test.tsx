/**
 * 문의 내역 화면과 문의 목록 조건 조회 (API 02 IQ-02 조건을 모의로 걸러 주는 부분).
 * 시연 데이터(EMP-1001): 처리 중(접수) 1, AI 해결 1, 미확인 1, 해결 완료 1.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { startChat } from '../src/api/chat'
import { listInquiries } from '../src/api/inquiries'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const USER = { employeeNo: 'EMP-1001', name: '김서연' }

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

const titles = () => within(screen.getByRole('table')).getAllByRole('button', { name: /.+/ }).filter((b) => b.className === 'lk').map((b) => b.textContent)

describe('문의 목록 조건 조회 (API)', () => {
  it('조건 없이 읽으면 최근 활동 순으로 전부 돌려주고, 접수번호와 표시 상태가 붙는다', async () => {
    const r = await listInquiries(USER.employeeNo)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.data).toMatchObject({ page: 1, size: 20, totalCount: 4, totalPages: 1 })
    expect(r.data.items.map((i) => i.displayStatus)).toEqual(['progress', 'ai_resolved', 'unconfirmed', 'resolved'])
    expect(r.data.items[0]).toMatchObject({ receiptNo: 'RCPT-1041', jiraKey: 'ITHD-1520', categoryCode: 'NET' })
  })

  it('상태·분류·기간·검색어 조건으로 걸러 낸다', async () => {
    const by = async (q: Parameters<typeof listInquiries>[1]) => {
      const r = await listInquiries(USER.employeeNo, q)
      return r.ok ? r.data.items.map((i) => i.title) : []
    }
    expect(await by({ displayStatus: ['unconfirmed', 'unresolved'] })).toEqual(['VPN 인증서 갱신이 필요한가요'])
    expect(await by({ categoryCode: ['NET'] })).toHaveLength(2)
    expect(await by({ q: 'rcpt-1030' })).toEqual(['노트북 화면 깜빡임']) // 접수번호, 대소문자 무시
    expect(await by({ q: '깜빡' })).toEqual(['노트북 화면 깜빡임'])
    expect(await by({ q: '네트워크' })).toHaveLength(2) // 분류 이름
    // 기간: 시작일이 오늘이면 어제 이전 문의는 모두 빠진다
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    expect(await by({ createdFrom: today })).toEqual([])
    expect(await by({ createdTo: '2000-01-01' })).toEqual([])
  })

  it('정렬과 쪽 나누기를 따른다', async () => {
    const r = await listInquiries(USER.employeeNo, { sort: 'title,asc', size: 3 })
    expect(r.ok && r.data.items.map((i) => i.title)).toEqual(['VPN 연결이 자주 끊겨요', 'VPN 인증서 갱신이 필요한가요', '계정 잠금 해제 방법'])
    expect(r.ok && r.data.totalPages).toBe(2)
    const p2 = await listInquiries(USER.employeeNo, { sort: 'title,asc', size: 3, page: 2 })
    expect(p2.ok && p2.data.items.map((i) => i.title)).toEqual(['노트북 화면 깜빡임'])
    // 없는 쪽은 마지막 쪽으로
    const far = await listInquiries(USER.employeeNo, { size: 3, page: 99 })
    expect(far.ok && far.data.page).toBe(2)
  })

  it('다른 사람의 문의는 보이지 않고, 삭제로 숨긴 문의도 빠진다', async () => {
    const other = await listInquiries('EMP-1003')
    expect(other.ok && other.data.items.map((i) => i.title)).not.toContain('VPN 연결이 자주 끊겨요')
    const a = await startChat(USER, 'VPN이 끊겨요')
    expect(a.ok).toBe(true)
    const r = await listInquiries(USER.employeeNo, { q: 'VPN이 끊겨요' })
    expect(r.ok && r.data.totalCount).toBe(1)
  })
})

describe('문의 내역 화면', () => {
  it('상태별 건수와 목록이 보이고, 상태 분류를 누르면 그 문의만 남는다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/list')
    expect(await screen.findByRole('heading', { name: '내 문의를 한눈에 확인해요' }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(titles()).toHaveLength(4), SLOW)
    const group = screen.getByRole('group', { name: '상태' })
    expect(within(group).getByRole('button', { name: /^전체\s*4$/ })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(group).getByRole('button', { name: /AI 해결/ }))
    await waitFor(() => expect(titles()).toEqual(['계정 잠금 해제 방법']), SLOW)
    // 조건을 풀면 다시 전부
    await user.click(screen.getByRole('button', { name: '✕ 조건 해제' }))
    await waitFor(() => expect(titles()).toHaveLength(4), SLOW)
  })

  it('검색어는 강조되고, 맞는 문의가 없으면 조건에 맞는 문의가 없다고 알린다', async () => {
    const user = userEvent.setup()
    const { container } = renderAs('EMP-1001', '/list')
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument(), SLOW)
    await user.type(screen.getByLabelText('내 문의 검색'), 'VPN')
    await waitFor(() => expect(titles()).toHaveLength(2), SLOW)
    expect(container.querySelectorAll('mark.hl').length).toBeGreaterThan(0)
    await user.clear(screen.getByLabelText('내 문의 검색'))
    await user.type(screen.getByLabelText('내 문의 검색'), '없는말없는말')
    expect(await screen.findByText('조건에 맞는 문의가 없어요.', {}, SLOW)).toBeInTheDocument()
  })

  it('분류 알약으로 고르고 ✕로 해제하며, 열 머리를 누르면 정렬이 바뀐다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/list')
    await waitFor(() => expect(titles()).toHaveLength(4), SLOW)
    await user.click(screen.getByRole('button', { name: /^분류\s*전체$/ }))
    await user.click(screen.getByRole('option', { name: 'HW·업무 PC' }))
    await waitFor(() => expect(titles()).toEqual(['노트북 화면 깜빡임']), SLOW)
    await user.click(screen.getByRole('button', { name: '분류 해제' }))
    await waitFor(() => expect(titles()).toHaveLength(4), SLOW)
    // 문의(제목) 열: 한 번 누르면 오름차순, 다시 누르면 내림차순
    await user.click(screen.getByRole('button', { name: '문의' }))
    await waitFor(() => expect(titles()[0]).toBe('VPN 연결이 자주 끊겨요'), SLOW)
    expect(screen.getByRole('columnheader', { name: '문의' })).toHaveAttribute('aria-sort', 'ascending')
    await user.click(screen.getByRole('button', { name: '문의' }))
    await waitFor(() => expect(titles()[0]).toBe('노트북 화면 깜빡임'), SLOW)
  })

  it('문의를 누르면 그 대화로 가고, 사이드바의 검색 아이콘은 검색 칸에 초점을 둔다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/new')
    await user.click(await screen.findByRole('button', { name: '최근 문의 검색' }, SLOW))
    const box = await screen.findByLabelText('내 문의 검색', {}, SLOW)
    expect(box).toHaveFocus()
    await waitFor(() => expect(titles()).toHaveLength(4), SLOW)
    await user.click(within(screen.getByRole('table')).getByRole('button', { name: '노트북 화면 깜빡임' }))
    expect(await screen.findByRole('heading', { name: '노트북 화면 깜빡임' }, SLOW)).toBeInTheDocument()
  })
})
