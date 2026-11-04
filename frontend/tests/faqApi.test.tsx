/**
 * 실제 서버 모드(VITE_USE_MOCK_FAQ=false) FAQ API 테스트.
 * 서버는 띄우지 않고 가짜 fetch 로 서버 계약(docs/api/04 FQ-01·02)대로 응답을 만들어 준다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const faq = (id: number, over: Record<string, unknown> = {}) => ({
  id,
  faqCode: `FAQ-${String(id).padStart(3, '0')}`,
  categoryCode: 'ACC',
  category: { code: 'ACC', name: '계정·로그인' },
  question: `질문 ${id}`,
  answer: `답변 ${id}`,
  keywords: [],
  isActive: true,
  updatedBy: null,
  createdAt: '2026-10-20T12:00:00+09:00',
  updatedAt: null,
  ...over,
})
const page = (items: unknown[], p = 1, totalPages = 1) => ({ items, page: p, size: 100, totalCount: items.length, totalPages })
const DETAIL = { ...faq(1), sources: [{ documentId: 1, docCode: 'IT-ACC-001', title: '계정·로그인 가이드', version: 'v1.0', location: 'FAQ Q1' }] }

let fetchMock: ReturnType<typeof vi.fn>
const urls = () => fetchMock.mock.calls.map((c) => String(c[0]))

async function load(serviceRole?: string) {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_FAQ', 'false')
  vi.doMock('../src/core/session', () => {
    const auth = { user: { role: 'EMPLOYEE', serviceRole } }
    return { useAuth: () => auth }
  })
  return { api: await import('../src/api/faq'), view: await import('../src/views/faq/FaqView') }
}

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('서버 모드 FAQ 목록', () => {
  it('서버의 Page 를 화면의 FAQ 로 바꾸고, 비게시 FAQ 는 빼며, FAQ 번호를 id 로 쓴다', async () => {
    const { api } = await load()
    fetchMock.mockResolvedValueOnce(json(200, page([faq(1), faq(2, { isActive: false }), faq(3)])))
    const r = await api.listFaqs()
    expect(r.ok && r.data.map((f) => [f.id, f.serverId, f.question])).toEqual([
      ['FAQ-001', 1, '질문 1'],
      ['FAQ-003', 3, '질문 3'],
    ])
    expect(r.ok && r.data[0].sources).toEqual([])
    expect(urls()).toEqual(['/api/v1/faqs?page=1&size=100&sort=faqCode,asc'])
  })

  it('여러 쪽이면 모두 읽고, 실패하면 서버 오류를 그대로 돌려준다', async () => {
    const { api } = await load()
    fetchMock.mockResolvedValueOnce(json(200, page([faq(1)], 1, 2))).mockResolvedValueOnce(json(200, page([faq(2)], 2, 2)))
    const r = await api.listFaqs()
    expect(r.ok && r.data).toHaveLength(2)
    expect(urls()[1]).toContain('page=2')

    fetchMock.mockResolvedValueOnce(json(500, { error: { code: 'INTERNAL_ERROR', message: '일시적인 오류', details: null, traceId: 't' } }))
    expect(await api.listFaqs()).toMatchObject({ ok: false, error: { code: 'INTERNAL_ERROR' } })
  })

  it('출처는 FAQ 상세에서 읽어 화면의 출처 모양으로 바꾼다', async () => {
    const { api } = await load()
    fetchMock.mockResolvedValueOnce(json(200, DETAIL))
    const r = await api.getFaqSources(1)
    expect(r.ok && r.data).toEqual([{ docCode: 'IT-ACC-001', title: '계정·로그인 가이드', version: 'v1.0', section: 'FAQ Q1', excerpt: '' }])
    expect(urls()).toEqual(['/api/v1/faqs/1'])
  })
})

describe('서버 모드 FAQ 화면', () => {
  it('FAQ 를 열 때 처음 한 번만 출처를 읽고, 못 읽으면 알려 준다', async () => {
    const { view } = await load()
    fetchMock.mockResolvedValueOnce(json(200, page([faq(1), faq(2)]))).mockResolvedValueOnce(json(200, DETAIL)).mockResolvedValueOnce(json(404, { error: { code: 'FAQ_NOT_FOUND', message: '없음', details: null, traceId: 't' } }))
    render(
      <MemoryRouter>
        <view.FaqView />
      </MemoryRouter>,
    )
    const q1 = await screen.findByText('질문 1')
    expect(urls()).toHaveLength(1) // 목록만. 출처는 아직 읽지 않았다
    await userEvent.click(q1)
    expect(await screen.findByText('IT-ACC-001 계정·로그인 가이드 v1.0')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /FAQ Q1/ })).toBeInTheDocument()
    await userEvent.click(q1) // 닫았다가
    await userEvent.click(q1) // 다시 열어도 다시 읽지 않는다
    expect(urls()).toHaveLength(2)

    await userEvent.click(screen.getByText('질문 2'))
    await waitFor(() => expect(screen.getByText('출처를 불러오지 못했어요.')).toBeInTheDocument())
  })
})

describe('서버 모드 FAQ 등록 창 (게시는 출처 연결 기능이 생길 때까지 막는다, docs/api/06 R-41)', () => {
  it('바로 게시를 눌러도 체크되지 않고 안내만 보이며, 등록하면 게시 전(isActive=false)으로 보낸다', async () => {
    const { view } = await load('ADMIN')
    fetchMock.mockImplementation(async (_u: unknown, init?: RequestInit) => (init?.method === 'POST' ? json(201, faq(41, { isActive: false })) : json(200, page([faq(1)]))))
    render(
      <MemoryRouter>
        <view.FaqView />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'FAQ 등록' }))
    const dlg = await screen.findByRole('dialog', { name: 'FAQ 등록' })
    const pub = within(dlg).getByRole('checkbox', { name: '바로 게시' })
    expect(within(dlg).queryByRole('status')).toBeNull()
    await userEvent.click(pub)
    expect(pub).not.toBeChecked()
    expect(within(dlg).getByRole('status')).toHaveTextContent('지금은 게시할 수 없어요')
    await userEvent.type(within(dlg).getByLabelText('질문 제목'), '공용 프린터가 보이지 않아요')
    await userEvent.type(within(dlg).getByLabelText('답변'), '프린터 서버를 다시 추가해 주세요.')
    await userEvent.click(within(dlg).getByRole('button', { name: '등록' }))
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'POST')).toBe(true))
    const post = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')!
    expect(JSON.parse(String((post[1] as RequestInit).body))).toMatchObject({ isActive: false, keywords: [] })
  })
})

describe('서버 모드 FAQ 카드의 다시 게시 (출처 없는 FAQ 는 게시하지 않는다)', () => {
  it('출처가 없는 게시 중단 FAQ 는 다시 게시를 눌러도 서버에 보내지 않고 안내만 보인다', async () => {
    const { view } = await load('ADMIN')
    fetchMock.mockImplementation(async (u: unknown) => (String(u).endsWith('/faqs/1') ? json(200, { ...faq(1, { isActive: false }), sources: [] }) : json(200, page([faq(1, { isActive: false })]))))
    render(
      <MemoryRouter>
        <view.FaqView />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByText('질문 1'))
    await screen.findByText('출처 정보가 없어요.')
    await userEvent.click(screen.getByRole('button', { name: '다시 게시' }))
    expect(await screen.findByText(/지금은 게시할 수 없어요/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'PATCH')).toBe(false)
  })
})
