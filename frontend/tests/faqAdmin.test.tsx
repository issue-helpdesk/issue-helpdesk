/**
 * 관리자 FAQ 관리: 등록·게시 중단·다시 게시·삭제 (FQ-03~05). 모의 화면 테스트와, 가짜 fetch 로 서버 계약을 확인하는 서버 모드 테스트.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { listFaqs, resetFaqMock } from '../src/api/faq'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

/** 선택 상자(SelectBox)에서 항목 고르기: 칸을 눌러 목록을 열고 항목을 누른다 */
async function choose(scope: HTMLElement, label: string, option: string | RegExp) {
  await userEvent.click(within(scope).getByLabelText(label))
  await userEvent.click(await screen.findByRole('option', { name: option }))
}

function renderAs(employeeNo: string) {
  tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={['/faq']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
const count = () => document.querySelectorAll('details.faq').length

describe('FAQ 관리 화면 (모의)', () => {
  beforeEach(() => resetFaqMock())

  it('문의자에게는 등록·게시 중단·삭제 버튼이 없다', async () => {
    renderAs('EMP-1001')
    await screen.findByRole('group', { name: '분류' }, SLOW)
    expect(screen.queryByRole('button', { name: /FAQ 등록/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '삭제' })).toBeNull()
    expect(screen.queryByRole('button', { name: '게시 중단' })).toBeNull()
  })

  it('관리자는 등록 창에서 빠진 항목을 안내받고, 등록하면 목록이 늘어난다', async () => {
    renderAs('EMP-1178')
    await screen.findByRole('group', { name: '분류' }, SLOW)
    const before = count()
    await userEvent.click(screen.getByRole('button', { name: /FAQ 등록/ }))
    const dlg = await screen.findByRole('dialog', { name: 'FAQ 등록' })
    await userEvent.click(within(dlg).getByRole('button', { name: '등록' }))
    expect(await within(dlg).findByText('질문 제목을 입력해 주세요.')).toBeInTheDocument()
    expect(within(dlg).getByText('답변을 입력해 주세요.')).toBeInTheDocument()
    expect(within(dlg).getByText('출처 가이드를 하나 이상 선택해 주세요.')).toBeInTheDocument()
    await choose(dlg, '분류', /HW/)
    // 분류별 포인트 색 막대가 목록 항목 앞에 붙는다 (가이드 관리와 같은 색)
    expect(within(dlg).getByLabelText('분류').querySelector('.tag.gcbar.c-HW')).not.toBeNull()
    await userEvent.type(within(dlg).getByLabelText('질문 제목'), '공용 프린터가 보이지 않아요')
    await userEvent.type(within(dlg).getByLabelText('답변'), '프린터 서버를 다시 추가해 주세요.')
    expect(within(dlg).queryByLabelText(/키워드/)).toBeNull() // 키워드 칸은 두지 않는다 (서버는 비워도 등록되고 화면에서 쓰이는 곳이 없다)
    // 출처 가이드는 전 직원용 현행 가이드만 고를 수 있다 (제한 가이드는 목록에 없다). 고르기 전에는 게시 체크가 잠겨 있다
    const group = await within(dlg).findByRole('group', { name: /출처 가이드/ }, SLOW)
    expect(within(group).queryByText(/IT-SEC-004/)).toBeNull()
    const pub = within(dlg).getByLabelText(/등록하면서 문의자에게 공개/)
    expect(pub).toBeDisabled()
    await userEvent.click(within(group).getByRole('checkbox', { name: /IT-HW-003/ }))
    expect(pub).toBeEnabled()
    await userEvent.click(within(dlg).getByRole('button', { name: '등록' }))
    expect(await screen.findByText(/FAQ를 등록했어요/, {}, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(count()).toBe(before + 1), SLOW)
    expect(screen.getByText('공용 프린터가 보이지 않아요')).toBeInTheDocument()
    // 고른 출처가 FAQ 에 붙는다
    const mine = screen.getByText('공용 프린터가 보이지 않아요').closest('details') as HTMLElement
    await userEvent.click(mine.querySelector('summary')!)
    expect(within(mine).getByText(/IT-HW-003/)).toBeInTheDocument()
  })

  it('수정 창은 기존 내용과 출처를 채워 열고, 저장하면 게시가 중단되며 "바로 게시"를 켜면 다시 게시된다', async () => {
    renderAs('EMP-1178')
    await screen.findByRole('group', { name: '분류' }, SLOW)
    const first = document.querySelector('details.faq') as HTMLElement
    const title = first.querySelector('summary b')!.textContent!
    await userEvent.click(first.querySelector('summary')!)
    await userEvent.click(within(first).getByRole('button', { name: '수정' }))
    const dlg = await screen.findByRole('dialog', { name: 'FAQ 수정' })
    expect(within(dlg).getByLabelText('질문 제목')).toHaveValue(title)
    expect(within(dlg).getByText(/수정을 저장하면 이 FAQ는 자동으로 게시가 중단돼요/)).toBeInTheDocument()
    const group = await within(dlg).findByRole('group', { name: /출처 가이드/ }, SLOW)
    await waitFor(() => expect(within(group).getAllByRole('checkbox').some((c) => (c as HTMLInputElement).checked)).toBe(true), SLOW)
    // 게시를 끄고 저장하면 게시 중단으로 남는다
    await userEvent.clear(within(dlg).getByLabelText('질문 제목'))
    await userEvent.type(within(dlg).getByLabelText('질문 제목'), '수정한 질문')
    await userEvent.click(within(dlg).getByLabelText(/저장하면서 바로 게시/))
    await userEvent.click(within(dlg).getByRole('button', { name: '수정 저장' }))
    expect(await screen.findByText(/게시가 중단된 상태/, {}, SLOW)).toBeInTheDocument()
    const off = (await listFaqs(true)).ok ? ((await listFaqs(true)) as { ok: true; data: { question: string; active?: boolean }[] }).data.find((f) => f.question === '수정한 질문') : undefined
    expect(off?.active).toBe(false)
    // 다시 수정하면서 바로 게시를 켜면 게시된다
    const again = (await screen.findByText('수정한 질문', {}, SLOW)).closest('details') as HTMLElement
    await userEvent.click(again.querySelector('summary')!)
    await userEvent.click(within(again).getByRole('button', { name: '수정' }))
    const dlg2 = await screen.findByRole('dialog', { name: 'FAQ 수정' })
    expect(within(dlg2).getByText(/지금은 게시 중단 상태예요/)).toBeInTheDocument()
    await within(dlg2).findByRole('group', { name: /출처 가이드/ }, SLOW)
    await waitFor(() => expect(within(dlg2).getByLabelText(/저장하면서 바로 게시/)).toBeEnabled(), SLOW)
    await userEvent.click(within(dlg2).getByLabelText(/저장하면서 바로 게시/))
    await userEvent.click(within(dlg2).getByRole('button', { name: '수정 저장' }))
    expect(await screen.findByText(/수정하고 다시 게시했어요/, {}, SLOW)).toBeInTheDocument()
    const on = await listFaqs(false)
    expect(on.ok && on.data.some((f) => f.question === '수정한 질문')).toBe(true)
  })

  it('게시 중단하면 관리자에게는 "게시 중단" 표시로 남고 문의자 목록에서는 빠지며, 다시 게시할 수 있다', async () => {
    renderAs('EMP-1178')
    await screen.findByRole('group', { name: '분류' }, SLOW)
    const first = document.querySelector('details.faq') as HTMLElement
    const title = first.querySelector('summary b')!.textContent!
    await userEvent.click(first.querySelector('summary')!)
    await userEvent.click(within(first).getByRole('button', { name: '게시 중단' }))
    expect(await screen.findByText(/게시를 멈췄어요/, {}, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(within(screen.getByText(title).closest('details')!).getByText('게시 중단')).toBeInTheDocument(), SLOW)
    const visible = await listFaqs(false)
    expect(visible.ok && visible.data.some((f) => f.question === title)).toBe(false)
    const again = screen.getByText(title).closest('details') as HTMLElement
    await userEvent.click(again.querySelector('summary')!)
    await userEvent.click(within(again).getByRole('button', { name: '다시 게시' }))
    expect(await screen.findByText(/다시 게시했어요/, {}, SLOW)).toBeInTheDocument()
    const back = await listFaqs(false)
    expect(back.ok && back.data.some((f) => f.question === title)).toBe(true)
  })

  it('삭제는 확인을 거치고, 취소하면 그대로이며 확인하면 사라진다', async () => {
    renderAs('EMP-1178')
    await screen.findByRole('group', { name: '분류' }, SLOW)
    const before = count()
    const first = document.querySelector('details.faq') as HTMLElement
    await userEvent.click(first.querySelector('summary')!)
    await userEvent.click(within(first).getByRole('button', { name: '삭제' }))
    let dlg = await screen.findByRole('alertdialog', { name: 'FAQ 삭제' })
    await userEvent.click(within(dlg).getByRole('button', { name: '취소' }))
    expect(count()).toBe(before)
    await userEvent.click(within(first).getByRole('button', { name: '삭제' }))
    dlg = await screen.findByRole('alertdialog', { name: 'FAQ 삭제' })
    await userEvent.click(within(dlg).getByRole('button', { name: '삭제' }))
    expect(await screen.findByText('FAQ를 삭제했어요.', {}, SLOW)).toBeInTheDocument()
    await waitFor(() => expect(count()).toBe(before - 1), SLOW)
  })
})

/* ------------------------------------------------------------------ 서버 모드 */
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const sfaq = (id: number, over: Record<string, unknown> = {}) => ({ id, faqCode: `FAQ-${String(id).padStart(3, '0')}`, categoryCode: 'NET', question: `질문 ${id}`, answer: `답변 ${id}`, keywords: [], isActive: true, ...over })
const page = (items: unknown[]) => ({ items, page: 1, size: 100, totalCount: items.length, totalPages: 1 })

describe('서버 모드 FAQ 관리 (VITE_USE_MOCK_FAQ=false)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const sent = () => fetchMock.mock.calls.map((c) => ({ url: String(c[0]), method: (c[1] as RequestInit | undefined)?.method ?? 'GET', body: (c[1] as RequestInit | undefined)?.body }))
  async function load() {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_FAQ', 'false')
    return import('../src/api/faq')
  }
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('관리자 목록에는 게시 중단된 FAQ 도 오고, 그 밖의 목록에는 게시 중인 것만 온다', async () => {
    const api = await load()
    fetchMock.mockImplementation(async () => json(200, page([sfaq(1), sfaq(2, { isActive: false })])))
    const admin = await api.listFaqs(true)
    expect(admin.ok && admin.data.map((f) => [f.id, f.active])).toEqual([['FAQ-001', true], ['FAQ-002', false]])
    const other = await api.listFaqs(false)
    expect(other.ok && other.data.map((f) => f.id)).toEqual(['FAQ-001'])
  })

  it('등록은 POST /faqs 로 보내고 서버가 발급한 번호를 돌려받는다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(201, sfaq(41, { isActive: false })))
    const r = await api.createFaq({ categoryCode: 'NET', question: '질문 41', answer: '답변 41', keywords: ['VPN'], isActive: false })
    expect(r.ok && r.data).toMatchObject({ id: 'FAQ-041', serverId: 41, active: false })
    expect(sent()[0]).toMatchObject({ url: '/api/v1/faqs', method: 'POST' })
    expect(JSON.parse(String(sent()[0].body))).toEqual({ categoryCode: 'NET', question: '질문 41', answer: '답변 41', keywords: ['VPN'], isActive: false })
  })

  it('게시 출처 조건을 못 채우면(409) 해야 할 일을 알려 준다', async () => {
    const api = await load()
    fetchMock.mockImplementation(async () => json(409, { error: { code: 'FAQ_SOURCE_NOT_PUBLIC', message: '출처', details: null, traceId: 't' } }))
    const r = await api.createFaq({ categoryCode: 'NET', question: 'q', answer: 'a', keywords: [], isActive: true })
    expect(r).toMatchObject({ ok: false, error: { code: 'FAQ_SOURCE_NOT_PUBLIC' } })
    expect(!r.ok && r.error.message).toContain('먼저 "게시 안 함"으로 등록')
    const f = { id: 'FAQ-001', serverId: 1, categoryCode: 'NET' as const, question: 'q', answer: 'a', sources: [], active: false }
    const again = await api.setFaqActive(f, true)
    expect(!again.ok && again.error.message).toContain('가이드 출처')
  })

  it('출처 가이드는 문서 ID 목록(sourceDocumentIds)으로 보내고, 수정은 PATCH 로 통째로 바꾼다', async () => {
    const api = await load()
    const src = [{ documentId: 12, docCode: 'IT-NET-001', title: 'VPN', version: 'v2' }]
    fetchMock.mockResolvedValueOnce(json(201, sfaq(42))).mockResolvedValueOnce(json(200, sfaq(42, { isActive: false })))
    await api.createFaq({ categoryCode: 'NET', question: 'q', answer: 'a', keywords: [], isActive: true, sources: src })
    expect(JSON.parse(String(sent()[0].body))).toEqual({ categoryCode: 'NET', question: 'q', answer: 'a', keywords: [], isActive: true, sourceDocumentIds: [12] })
    const f = { id: 'FAQ-042', serverId: 42, categoryCode: 'NET' as const, question: 'q', answer: 'a', sources: [] }
    const r = await api.updateFaq(f, { question: 'q2', isActive: false, sources: [...src, { documentId: 13, docCode: 'IT-NET-002', title: 'Wi-Fi', version: 'v1' }] })
    expect(r.ok && r.data.active).toBe(false)
    expect(sent()[1]).toMatchObject({ url: '/api/v1/faqs/42', method: 'PATCH' })
    expect(JSON.parse(String(sent()[1].body))).toEqual({ question: 'q2', isActive: false, sourceDocumentIds: [12, 13] })
  })

  it('게시 중단·삭제는 PATCH·DELETE 로 보낸다', async () => {
    const api = await load()
    const f = { id: 'FAQ-003', serverId: 3, categoryCode: 'NET' as const, question: 'q', answer: 'a', sources: [] }
    fetchMock.mockResolvedValueOnce(json(200, sfaq(3, { isActive: false }))).mockResolvedValueOnce(new Response(null, { status: 204 }))
    const off = await api.setFaqActive(f, false)
    expect(off.ok && off.data.active).toBe(false)
    expect(await api.deleteFaq(f)).toMatchObject({ ok: true })
    expect(sent().map((c) => `${c.method} ${c.url}`)).toEqual(['PATCH /api/v1/faqs/3', 'DELETE /api/v1/faqs/3'])
    expect(JSON.parse(String(sent()[0].body))).toEqual({ isActive: false })
  })
})
