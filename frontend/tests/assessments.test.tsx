/**
 * AI 판단 이력 (관리자, IQ-10 GET /inquiries/{id}/assessments): 모의 데이터·서버 요청 모양·관리자 전용·접수 상세 화면.
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { listAssessments, type Assessment } from '../src/api/assessments'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { AssessmentHistory } from '../src/views/staff/AssessmentHistory'

const SLOW = { timeout: 3000 }
const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const agent = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!

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

describe('AI 판단 이력 API (모의)', () => {
  it('관리자가 아니면 막는다 (서버도 403)', async () => {
    expect(await listAssessments(agent(), 9001)).toMatchObject({ ok: false, error: { code: 'FORBIDDEN' } })
  })

  it('보안 접수는 규칙이 긴급도를 올린 내역이 있고, 일반 접수는 AI 판단 그대로다', async () => {
    const sec = await listAssessments(admin(), 9001) // 악성 첨부파일 의심 메일 수신 (SEC, P1)
    expect(sec.ok && sec.data[0]).toMatchObject({ categoryCode: 'SEC', urgency: 'P1', action: 'ESCALATE' })
    expect(sec.ok && sec.data[0].overrideReasons).toEqual([expect.objectContaining({ field: 'urgency', ai: 'P3', final: 'P1', rule: 'SEC_MIN_P2' })])
    const plain = await listAssessments(admin(), 9002)
    expect(plain.ok && plain.data[0].overrideReasons).toEqual([])
    expect(await listAssessments(admin(), 1)).toMatchObject({ ok: false, error: { code: 'INQUIRY_NOT_FOUND' } })
  })
})

describe('AI 판단 이력 (서버 모드)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('문의의 판단 이력을 GET 으로 읽고 items 만 돌려준다', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    const api = await import('../src/api/assessments')
    const item = { id: 311, inquiryId: 130, facts: { summary: '피싱 메일' }, missingItems: [], urgentSignal: true, categoryCode: 'SEC', inquiryTypeId: 51, urgency: 'P2', urgencyReason: 'x', action: 'ESCALATE', aiOutput: { urgencySuggested: 'P3', confidence: 0.8 }, overrideReasons: [], createdAt: '2026-10-21T11:02:15+09:00' }
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [item] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const r = await api.listAssessments(admin(), 130)
    expect(r.ok && r.data).toEqual([item])
    expect(`${(fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method ?? 'GET'} ${String(fetchMock.mock.calls[0][0])}`).toBe('GET /api/v1/inquiries/130/assessments')
  })
})

describe('접수 상세의 AI 판단 이력 (화면)', () => {
  it('관리자 상세에는 문의 요약 → AI 원래 판단 → 규칙이 바꾼 내역 → 최종 적용 순서로 보인다', async () => {
    renderAs('EMP-1178', '/tickets/5001')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    const h = await within(panel).findByRole('heading', { name: 'AI 판단 이력' }, SLOW)
    const box = h.parentElement!.querySelector('.asx') as HTMLElement
    const labels = [...box.querySelectorAll('.asl')].map((e) => e.textContent)
    expect(labels).toEqual(['문의 요약', 'AI 원래 판단', '규칙이 바꾼 내역', '최종 적용'])
    expect(within(box).getByText('악성 첨부파일 의심 메일 수신')).toBeInTheDocument()
    expect(box.querySelector('.asai')).toHaveTextContent('긴급도 보통')
    expect(within(box).getByText(/보안 사고 의심은 최소 높음/)).toBeInTheDocument()
    expect(within(box).getByText('SEC_MIN_P2')).toBeInTheDocument()
    // 규칙이 바꾼 항목 이름과 값이 화면 말이다
    expect(box.querySelector('.aso li')).toHaveTextContent('긴급도 보통 → 긴급')
  })

  it('규칙이 바꾼 것이 없으면 그대로 적용했다고 안내하고, 담당자 화면에는 이 섹션이 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/tickets/5002')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await within(panel).findByRole('heading', { name: 'AI 판단 이력' }, SLOW)
    expect(within(panel).getByText('없어요. AI 판단 그대로 적용했어요.')).toBeInTheDocument()
    unmount()
    renderAs('EMP-1004', '/queue/5002')
    const p2 = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await within(p2).findByRole('heading', { name: '처리 이력' }, SLOW)
    expect(within(p2).queryByRole('heading', { name: 'AI 판단 이력' })).toBeNull()
  })
})

describe('AI 판단 이력: AI 원래 판단이 없는 경우', () => {
  it('안전 거절·AI 실패로 aiOutput 이 null 이어도 화면이 깨지지 않고 안내를 보여 준다', async () => {
    tokenStore.set('mock.EMP-1178')
    const refused: Assessment = {
      id: 1, inquiryId: 677, facts: { summary: '' }, missingItems: [], urgentSignal: false, categoryCode: null, inquiryTypeId: null,
      urgency: 'P3', urgencyReason: null, action: 'ESCALATE', aiOutput: null, overrideReasons: [], createdAt: '2026-11-10T01:10:00+09:00',
    }
    render(
      <MemoryRouter>
        <AuthProvider>
          <AssessmentHistory inquiryId={677} preset={[refused]} />
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/AI 판단 없음/, {}, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'AI 판단 이력' })).toBeInTheDocument()
  })
})
