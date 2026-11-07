/**
 * 가이드 관리 → 해결 사례 → 가이드 초안 탭 (모의): 제안 목록, 검토 패널, 승인·등록·검색 준비·현행 전환·비가이드화·재시도,
 * 기준 가이드가 바뀐 제안의 차단. 서버 없이 시연 데이터와 모의 상태 전환만 쓴다.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { PREPARE_DELAY_MS, approveCase, baseChanged, dropCase, failNextPrepare, getCases, goLiveCase, rebaseCase, resetCaseGuides, retryCase } from '../src/api/mock/caseGuides'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const get = (id: string) => getCases().find((c) => c.id === id)!

describe('가이드 초안 모의 상태 전환', () => {
  beforeEach(() => {
    resetCaseGuides()
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('승인하면 초안으로 등록되어 검색 준비 중이 되고, 시간이 지나면 준비 완료가 되며, 현행 전환은 따로 한다', () => {
    const c = get('c1')
    expect(c.state).toBe('review')
    expect(approveCase('c1', { after: c.after, scope: '담당자 이상', tx: '마스킹 후 허용' })).toEqual({ ok: true })
    expect(get('c1')).toMatchObject({ state: 'preparing', scope: '담당자 이상', tx: '마스킹 후 허용', registered: { docCode: 'IT-NET-001', version: 'v3' } })
    // 중복 승인은 막는다
    expect(approveCase('c1', { after: c.after, scope: '전 직원', tx: '허용' }).ok).toBe(false)
    act(() => {
      vi.advanceTimersByTime(PREPARE_DELAY_MS + 10)
    })
    expect(get('c1').state).toBe('ready') // 자동으로 현행이 되지 않는다
    expect(goLiveCase('c1')).toEqual({ ok: true })
    expect(get('c1').state).toBe('live')
  })

  it('검색 준비에 실패하면 같은 버전으로 다시 시도하고, 후보로 되돌아가지 않는다', () => {
    failNextPrepare('c2')
    approveCase('c2', { title: '사내 메신저 알림이 오지 않을 때', cat: 'SYS', after: get('c2').after, scope: '전 직원', tx: '허용' })
    act(() => {
      vi.advanceTimersByTime(PREPARE_DELAY_MS + 10)
    })
    expect(get('c2').state).toBe('failed')
    expect(get('c2').failReason).toBeTruthy()
    expect(retryCase('c2')).toEqual({ ok: true })
    expect(get('c2').state).toBe('preparing')
    act(() => {
      vi.advanceTimersByTime(PREPARE_DELAY_MS + 10)
    })
    expect(get('c2').state).toBe('ready')
    expect(retryCase('c2').ok).toBe(false)
  })

  it('기준 가이드가 바뀐 제안은 등록이 막히고, 최신 내용에 맞춰 바꾸면 풀린다', () => {
    const c = get('c3')
    expect(baseChanged(c)).toBe(true)
    expect(approveCase('c3', { after: c.after, scope: '전 직원', tx: '허용' }).ok).toBe(false)
    expect(rebaseCase('c3')).toEqual({ ok: true })
    expect(baseChanged(get('c3'))).toBe(false)
    expect(get('c3').target!.baseVersion).toBe('v2')
    expect(approveCase('c3', { after: get('c3').after, scope: '전 직원', tx: '허용' })).toEqual({ ok: true })
  })

  it('비가이드화는 사유가 있어야 하고, 승인한 건에는 쓸 수 없다', () => {
    expect(dropCase('c1', '  ').ok).toBe(false)
    expect(dropCase('c1', '일회성 조치예요')).toEqual({ ok: true })
    expect(get('c1')).toMatchObject({ state: 'dropped', dropReason: '일회성 조치예요' })
    expect(dropCase('c4', '사유').ok).toBe(false) // 이미 검색 준비 중
  })
})

function renderAdmin() {
  tokenStore.set('mock.EMP-1178')
  return render(
    <MemoryRouter initialEntries={['/guides']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
const cardsOf = () => screen.getAllByRole('region').filter((r) => r.classList.contains('cgc'))

describe('가이드 초안 탭 화면', () => {
  beforeEach(() => resetCaseGuides())

  it('근거 건수가 많은 순으로 카드가 보이고, 검토 대상과 처리한 건을 나눠 보며, 개발 용어가 보이지 않는다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: /해결 사례 → 가이드 초안/ }, SLOW))
    expect(await screen.findByText(/주 1회/, undefined, SLOW)).toBeInTheDocument()
    expect(screen.getByText(/마지막 분석/)).toBeInTheDocument()
    // 일간·주간 선택과 유사도 퍼센트는 없다
    expect(screen.queryByRole('button', { name: '일간' })).toBeNull()
    expect(screen.queryByText(/%/)).toBeNull()
    const cards = cardsOf()
    expect(cards.map((c) => /근거 티켓\s*(\d+)건/.exec(c.textContent ?? '')![1])).toEqual(['7', '5', '4'])
    expect(within(cards[0]).getByText('기존 가이드 보강')).toBeInTheDocument()
    expect(within(cards[1]).getByText('신규 가이드')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/CLS|WAITING|guide_status|APPLIED|REVIEWING/)
    // 승인·처리한 건
    await userEvent.click(screen.getByRole('button', { name: /^승인·처리한 건/ }))
    const done = cardsOf()
    expect(done).toHaveLength(5)
    const text = done.map((c) => c.textContent ?? '').join('|')
    for (const label of ['검색 준비 중', '검색 준비 실패', '검색 준비 완료', '가이드화 안 함']) expect(text).toContain(label)
  })

  it('검토하기로 패널을 열어 제안문을 고치고 승인하면 검색 준비 중으로 바뀐다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: /해결 사례 → 가이드 초안/ }, SLOW))
    await screen.findByText(/주 1회/, undefined, SLOW)
    await userEvent.click(within(cardsOf()[0]).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(within(panel).getByText('근거 티켓')).toBeInTheDocument()
    expect(within(panel).getByText(/초안으로 등록하고 검색 준비를 시작합니다/)).toBeInTheDocument()
    await userEvent.type(within(panel).getByLabelText(/AI 수정 제안문/), ' 추가 확인')
    await userEvent.click(within(panel).getByRole('button', { name: '담당자 이상' }))
    await userEvent.click(within(panel).getByRole('button', { name: '승인하고 초안 등록' }))
    await waitFor(() => expect(get('c1').state).toBe('preparing'), SLOW)
    expect(get('c1')).toMatchObject({ scope: '담당자 이상' })
    expect(get('c1').after).toMatch(/추가 확인/)
    expect(await within(panel).findByText(/검색 준비 중이에요/, undefined, SLOW)).toBeInTheDocument()
  })

  it('기준 가이드가 바뀐 제안은 안내와 함께 등록 버튼이 막히고, 최신 버전과 비교해 바꾸면 풀린다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: /해결 사례 → 가이드 초안/ }, SLOW))
    await screen.findByText(/주 1회/, undefined, SLOW)
    const card = cardsOf().find((r) => /SSO 재로그인/.test(r.textContent ?? ''))!
    expect(within(card).getByText(/v1에서 v2로 변경됐어요/)).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(within(panel).getByRole('alert')).toHaveTextContent('기준 가이드가 v1에서 v2로 변경됐어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.')
    expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeDisabled()
    await userEvent.click(within(panel).getByRole('button', { name: '최신 버전과 비교' }))
    await userEvent.click(within(panel).getByRole('button', { name: '이 제안으로 바꾸고 다시 검토' }))
    await waitFor(() => expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeEnabled(), SLOW)
  })

  it('비가이드화는 사유를 입력해야 처리된다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: /해결 사례 → 가이드 초안/ }, SLOW))
    await screen.findByText(/주 1회/, undefined, SLOW)
    await userEvent.click(within(cardsOf()[0]).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    await userEvent.click(within(panel).getByRole('button', { name: '비가이드화' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '가이드화 안 함' }))
    expect(within(dlg).getByText('사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText(/사유/), '일회성이에요')
    await userEvent.click(within(dlg).getByRole('button', { name: '가이드화 안 함' }))
    await waitFor(() => expect(get('c1').state).toBe('dropped'), SLOW)
  })
})
