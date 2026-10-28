/**
 * 문의 내역 화면과 문의 목록 조건 조회 (API 02 IQ-02 조건을 모의로 걸러 주는 부분).
 * 시연 데이터(EMP-1001) 7건: 처리 중(접수) 1, 해결 확인 대기 1, AI 해결 1, 미확인 1, 해결 완료 1, 미해결 종료 1, 접수하지 않고 종료 1.
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
    expect(r.data).toMatchObject({ page: 1, size: 20, totalCount: 7, totalPages: 1 })
    expect(r.data.items.map((i) => i.displayStatus)).toEqual(['progress', 'awaiting_confirm', 'ai_resolved', 'unconfirmed', 'resolved', 'unresolved', 'unresolved'])
    // 접수 전 배지: AI 답변 뒤 확인 대기는 미확인, 접수하지 않고 끝낸 문의도 미해결 종료로 묶인다
    expect(r.data.items.map((i) => i.stateLabel)).toEqual(['처리 중', '해결 확인 대기', 'AI 해결', '미확인', '해결 완료', '미해결 종료', '미해결 종료'])
    expect(r.data.items[0]).toMatchObject({ receiptNo: 'RCPT-1041', jiraKey: 'ITHD-1520', categoryCode: 'NET' })
  })

  it('상태·분류·기간·검색어 조건으로 걸러 낸다', async () => {
    const by = async (q: Parameters<typeof listInquiries>[1]) => {
      const r = await listInquiries(USER.employeeNo, q)
      return r.ok ? r.data.items.map((i) => i.title) : []
    }
    expect(await by({ displayStatus: ['unconfirmed', 'unresolved'] })).toEqual(['VPN 인증서 갱신이 필요한가요', '프린터 드라이버 설치가 안 돼요', '사내 메신저 알림이 안 와요'])
    expect(await by({ displayStatus: ['awaiting_confirm'] })).toEqual(['전자결재 접속이 안 돼요'])
    expect(await by({ categoryCode: ['NET'] })).toHaveLength(2)
    expect(await by({ q: 'rcpt-1030' })).toEqual(['노트북 화면 깜빡임']) // 접수번호, 대소문자 무시
    expect(await by({ q: '깜빡' })).toEqual(['노트북 화면 깜빡임'])
    expect(await by({ q: '네트워크' })).toHaveLength(2) // 분류 이름
    // 기간: 시작일이 오늘이면 어제 이전 문의는 모두 빠진다
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    expect(await by({ createdFrom: today })).toEqual([])
    expect(await by({ createdTo: '2000-01-01' })).toEqual([])
    // 기간은 최근 활동이 아니라 문의 시작일 기준이다: VPN 연결 문의는 어제 활동했지만 3일 전에 시작했다
    const ago = (n: number) => {
      const x = new Date(Date.now() - n * 86_400_000)
      return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
    }
    expect(await by({ createdFrom: ago(2) })).toEqual([])
    expect(await by({ createdFrom: ago(5) })).toEqual(['VPN 연결이 자주 끊겨요', '전자결재 접속이 안 돼요', '계정 잠금 해제 방법'])
  })

  it('정렬과 쪽 나누기를 따른다', async () => {
    const r = await listInquiries(USER.employeeNo, { sort: 'title,asc', size: 3 })
    expect(r.ok && r.data.items.map((i) => i.title)).toEqual(['VPN 연결이 자주 끊겨요', 'VPN 인증서 갱신이 필요한가요', '계정 잠금 해제 방법'])
    expect(r.ok && r.data.totalPages).toBe(3)
    const p2 = await listInquiries(USER.employeeNo, { sort: 'title,asc', size: 3, page: 2 })
    expect(p2.ok && p2.data.items.map((i) => i.title)).toEqual(['노트북 화면 깜빡임', '사내 메신저 알림이 안 와요', '전자결재 접속이 안 돼요'])
    // 없는 쪽은 마지막 쪽으로
    const far = await listInquiries(USER.employeeNo, { size: 3, page: 99 })
    expect(far.ok && far.data.page).toBe(3)
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
  it('상태 알약으로 그 문의만 남기고, "미확인" 항목 없이 해결 확인 대기와 미해결을 따로 볼 수 있다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/list')
    expect(await screen.findByRole('heading', { name: '내 문의를 한눈에 확인해요' }, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    // 칩 줄은 없고 상태는 알약 하나로 고른다
    expect(screen.queryByRole('group', { name: '상태' })).not.toBeInTheDocument()
    const openStatus = () => user.click(screen.getAllByRole('button', { name: /^상태/ }).find((b) => b.getAttribute('aria-haspopup') === 'listbox')!)
    await openStatus()
    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names.some((n) => /미확인/.test(n ?? ''))).toBe(false)
    expect(names).toContain('해결 확인 대기 · 2')
    expect(names).toContain('미해결 · 2')
    await user.click(screen.getByRole('option', { name: /^AI 해결/ }))
    await waitFor(() => expect(titles()).toEqual(['계정 잠금 해제 방법']), SLOW)
    // 해결 확인 대기: 담당자 처리 완료 뒤 건과 AI 답변 뒤 건이 함께 나오고, 보조 라벨로 구분한다
    await openStatus()
    await user.click(screen.getByRole('option', { name: /^해결 확인 대기/ }))
    await waitFor(() => expect(titles()).toEqual(['전자결재 접속이 안 돼요', 'VPN 인증서 갱신이 필요한가요']), SLOW)
    const table = screen.getByRole('table')
    expect(within(table).getByText('담당자 처리')).toBeInTheDocument()
    expect(within(table).getByText('AI 안내')).toBeInTheDocument()
    await openStatus()
    await user.click(screen.getByRole('option', { name: /^미해결/ }))
    await waitFor(() => expect(titles()).toEqual(['프린터 드라이버 설치가 안 돼요', '사내 메신저 알림이 안 와요']), SLOW)
    // 조건을 풀면 다시 전부
    await user.click(screen.getByRole('button', { name: '✕ 조건 해제' }))
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
  })

  it('AI 안내 확인 대기는 "해결 확인 대기"(분홍)로, 서버가 "미확인"을 보내도 같은 이름으로 보인다', async () => {
    renderAs('EMP-1001', '/list')
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    const row = screen.getByRole('button', { name: 'VPN 인증서 갱신이 필요한가요' }).closest('tr')!
    expect(within(row).getByText('해결 확인 대기')).toBeInTheDocument()
    expect(within(row).queryByText('미확인')).not.toBeInTheDocument()
    expect(row.querySelector('.badge.b-need')).not.toBeNull()
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
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    await user.click(screen.getByRole('button', { name: /^분류\s*전체$/ }))
    await user.click(screen.getByRole('option', { name: 'HW·업무 PC' }))
    await waitFor(() => expect(titles()).toEqual(['노트북 화면 깜빡임', '프린터 드라이버 설치가 안 돼요']), SLOW)
    await user.click(screen.getByRole('button', { name: '분류 해제' }))
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    // 문의(제목) 열: 한 번 누르면 오름차순, 다시 누르면 내림차순
    await user.click(screen.getByRole('button', { name: '문의' }))
    await waitFor(() => expect(titles()[0]).toBe('VPN 연결이 자주 끊겨요'), SLOW)
    expect(screen.getByRole('columnheader', { name: '문의' })).toHaveAttribute('aria-sort', 'ascending')
    await user.click(screen.getByRole('button', { name: '문의' }))
    await waitFor(() => expect(titles()[0]).toBe('프린터 드라이버 설치가 안 돼요'), SLOW)
  })

  it('기간 알약은 시작일 기준이고, 최근 메시지 아래에 시작일이 함께 보인다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/list')
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    // VPN 연결 문의: 어제 활동, 3일 전 시작
    const row = screen.getByRole('button', { name: 'VPN 연결이 자주 끊겨요' }).closest('tr')!
    const d = new Date()
    d.setDate(d.getDate() - 3)
    const md = `${String(d.getMonth() + 1).padStart(2, '0')}\\.${String(d.getDate()).padStart(2, '0')}`
    expect(within(row).getByText(new RegExp(`^문의 시작 · (\\d{2}\\.)?${md}$`))).toBeInTheDocument()
    // 열 머리 이름과 기준 안내(툴팁)
    expect(screen.getByRole('button', { name: '최근 메시지' })).toHaveAttribute('title', '마지막 메시지 등록 시각 기준')
    await user.click(screen.getByRole('button', { name: /^시작일\s*전체$/ }))
    await user.click(screen.getByRole('option', { name: '최근 7일' }))
    await waitFor(() => expect(titles()).toEqual(['VPN 연결이 자주 끊겨요', '전자결재 접속이 안 돼요', '계정 잠금 해제 방법', 'VPN 인증서 갱신이 필요한가요']), SLOW)
  })

  it('문의를 누르면 그 대화로 가고, 사이드바의 검색 아이콘은 검색 칸에 초점을 둔다', async () => {
    const user = userEvent.setup()
    renderAs('EMP-1001', '/new')
    await user.click(await screen.findByRole('button', { name: '최근 문의 검색' }, SLOW))
    const box = await screen.findByLabelText('내 문의 검색', {}, SLOW)
    expect(box).toHaveFocus()
    await waitFor(() => expect(titles()).toHaveLength(7), SLOW)
    await user.click(within(screen.getByRole('table')).getByRole('button', { name: '노트북 화면 깜빡임' }))
    expect(await screen.findByRole('heading', { name: '노트북 화면 깜빡임' }, SLOW)).toBeInTheDocument()
  })
})
