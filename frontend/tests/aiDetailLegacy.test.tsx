/**
 * AI 처리 상세 패널의 "사용한 가이드": 가이드와 과거 처리 사례를 두 묶음으로 나누고,
 * 과거 사례는 누르면 본문을 짧게 펼쳐 보인다. 서버는 과거 사례를 문서 코드 없이 본문(excerpt)만 준다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { UsedGuide } from '../src/api/inquirySources'
import type { AiRow } from '../src/api/mock/aiRows'

const used = vi.hoisted(() => ({ list: [] as unknown[] }))
vi.mock('../src/api/inquirySources', async (orig) => ({
  ...(await orig<typeof import('../src/api/inquirySources')>()),
  listUsedGuides: vi.fn(async () => ({ ok: true as const, data: used.list as UsedGuide[] })),
}))
vi.mock('../src/views/staff/AssessmentHistory', () => ({ AssessmentHistory: () => null }))

const row: AiRow = { id: 'AI-1', inquiryId: 7, user: '김민지 · EMP-1003', title: 'VPN 접속 불가', categoryCode: 'NET', guide: '-', kind: 'ok', when: '오늘', day: 0, at: 1 }
const doc = (code: string, loc: string): UsedGuide => ({ docCode: code, version: 'v2', location: loc, kind: 'DOCUMENT', excerpt: '3.1 순서 안내' })
const legacy = (excerpt: string | null): UsedGuide => ({ docCode: null, version: null, location: null, kind: 'LEGACY', excerpt })

async function open() {
  const { AiDetailPanel } = await import('../src/views/admin/AiDetailPanel')
  return render(<AiDetailPanel row={row} slide={false} onSlideEnd={() => {}} onClose={() => {}} />)
}

describe('사용한 가이드와 과거 처리 사례', () => {
  beforeEach(() => {
    used.list = []
  })
  afterEach(() => vi.clearAllMocks())

  it('가이드와 과거 사례를 두 묶음으로 나누고, 사례를 누르면 본문이 펼쳐지며 다른 사례를 누르면 바뀐다', async () => {
    used.list = [doc('IT-NET-001', '3.1'), doc('IT-ACC-001', '4.2'), legacy('VPN 클라이언트 재설치 후 정상 접속 확인'), legacy('인증서를 갱신하자 해결됨')]
    await open()
    const guides = (await screen.findByRole('heading', { name: '사용한 가이드' })).parentElement as HTMLElement
    expect(within(guides).getByText(/IT-NET-001 v2 · 3.1/)).toBeInTheDocument()
    expect(within(guides).getByText(/IT-ACC-001 v2 · 4.2/)).toBeInTheDocument()
    expect(within(guides).queryByText(/과거 사례/)).toBeNull() // 사례는 가이드 묶음에 섞이지 않는다
    const cases = (await screen.findByRole('heading', { name: '참고한 과거 처리 사례' })).parentElement as HTMLElement
    const b1 = within(cases).getByRole('button', { name: '과거 사례 1' })
    const b2 = within(cases).getByRole('button', { name: '과거 사례 2' })
    expect(within(cases).queryByRole('region')).toBeNull()
    await userEvent.click(b1)
    expect(b1).toHaveAttribute('aria-expanded', 'true')
    expect(within(cases).getByRole('region', { name: '과거 사례 1 본문' })).toHaveTextContent('VPN 클라이언트 재설치 후 정상 접속 확인')
    await userEvent.click(b2)
    expect(b1).toHaveAttribute('aria-expanded', 'false')
    expect(within(cases).getByRole('region', { name: '과거 사례 2 본문' })).toHaveTextContent('인증서를 갱신하자 해결됨')
    await userEvent.click(b2)
    expect(within(cases).queryByRole('region')).toBeNull()
  })

  it('과거 사례가 없으면 묶음 자체가 없고, 가이드가 없고 사례만 있으면 그렇게 안내한다', async () => {
    used.list = [doc('IT-NET-001', '3.1')]
    const first = await open()
    await screen.findByText(/IT-NET-001/)
    expect(screen.queryByRole('heading', { name: '참고한 과거 처리 사례' })).toBeNull()
    first.unmount()
    used.list = [legacy('인증서를 갱신하자 해결됨'), legacy(null)]
    await open()
    expect(await screen.findByText('사용한 가이드가 없어요. 아래 과거 처리 사례만 참고했어요.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '과거 사례 2' }))
    expect(screen.getByRole('region', { name: '과거 사례 2 본문' })).toHaveTextContent('본문이 없어요.')
  })
})

describe('서버 응답에서 과거 사례 읽기', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('과거 사례는 본문으로 구분해 건수대로 남기고, 같은 가이드·위치는 한 번만 둔다', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    const src = (id: number, kind: string, over: Record<string, unknown> = {}) => ({ id, sourceKind: kind, docCode: null, version: null, location: null, excerpt: null, rank: id, ...over })
    const body = {
      items: [
        { sources: [src(1, 'DOCUMENT', { docCode: 'IT-NET-001', version: 'v2', location: '3.1' }), src(2, 'LEGACY', { excerpt: '재설치 후 정상' })] },
        { sources: [src(3, 'DOCUMENT', { docCode: 'IT-NET-001', version: 'v2', location: '3.1' }), src(4, 'LEGACY', { excerpt: '인증서 갱신' }), src(5, 'LEGACY', { excerpt: '재설치 후 정상' })] },
      ],
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const api = await vi.importActual<typeof import('../src/api/inquirySources')>('../src/api/inquirySources') // 위에서 가짜로 바꾼 것이 아니라 실제 코드
    const r = await api.listUsedGuides(7)
    await waitFor(() => expect(r.ok).toBe(true))
    expect(r.ok && r.data.map((g) => [g.kind, g.docCode, g.excerpt])).toEqual([
      ['DOCUMENT', 'IT-NET-001', null],
      ['LEGACY', null, '재설치 후 정상'],
      ['LEGACY', null, '인증서 갱신'],
    ])
  })
})
