/**
 * AI 가이드 제안의 초안 등록 흐름 (서버 연결): GC-06 등록·GC-07 다시 맞추기·GC-08 넣을 문서 변경.
 * 서버 응답은 가짜 fetch 로 대신한다. 요청 모양(본문·순서), 막는 이유, 새 가이드의 문서 연결, 충돌 표시를 본다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { displayMessage } from '../src/api/errorText'
import { tokenStore } from '../src/core/tokenStore'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (code: string, details: unknown = null) => ({ error: { code, message: '서버 문구', details, traceId: 't' } })
const ver = (o: object = {}) => ({ id: 31, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE', ...o })
const sum = (o: object = {}) => ({
  id: 12,
  category: { code: 'NET', name: 'VPN·네트워크' },
  judgment: 'ADD_ITEM',
  status: 'REVIEWING',
  title: 'VPN 연결 시 인터넷 끊김',
  ticketCount: 3,
  targetDocument: { id: 3, docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드' },
  registeredVersion: null,
  ...o,
})
const detail = (o: object = {}) => ({
  ...sum(),
  draftMd: '### 3.4 VPN을 연결하면 인터넷이 끊김',
  draftRevision: 2,
  targetSection: null,
  targetMd: null,
  conflicts: [],
  reviewInfo: { reason: '공유기 설정은 다루지 않음' },
  baseVersion: ver(),
  currentVersion: ver(),
  baseChanged: false,
  rejectReason: null,
  reviewedBy: null,
  reviewedAt: null,
  tickets: [{ ticketId: 101, receiptNo: 'RCPT-0101', summary: '재택 VPN 후 인터넷 끊김', resolutionNote: '패스스루를 켬' }],
  ...o,
})
const listOf = (items: unknown[]) => json(200, { items, page: 1, size: 100, totalCount: items.length, totalPages: 1 })

let fetchMock: ReturnType<typeof vi.fn>
type Route = (method: string, path: string, body: Record<string, unknown> | null) => Response | undefined
let route: Route
const calls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0]).replace(/^.*\/api\/v1/, '')}`)
const bodyOf = (method: string, path: string) => {
  const hit = fetchMock.mock.calls.find((c) => ((c[1] as RequestInit | undefined)?.method ?? 'GET') === method && String(c[0]).endsWith(path))
  return hit && typeof (hit[1] as RequestInit).body === 'string' ? JSON.parse((hit[1] as RequestInit).body as string) : null
}

beforeEach(() => {
  tokenStore.set('mock.EMP-1178')
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^.*\/api\/v1/, '')
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null
    return route(method, path, body) ?? json(404, err('NOT_FOUND'))
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubEnv('VITE_USE_MOCK_GUIDE', 'false')
  vi.resetModules()
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

async function mountPanel(id = '12') {
  const { AuthProvider } = await import('../src/core/session')
  const { CaseReviewPanel } = await import('../src/views/admin/CaseReviewPanel')
  return render(
    <AuthProvider>
      <CaseReviewPanel id={id} onClose={() => {}} onGoLive={() => {}} />
    </AuthProvider>,
  )
}

describe('오류 문구', () => {
  it('등록·다시 맞추기·문서 변경의 오류 코드에 화면 문구가 있고, 이유별로 다르다', () => {
    for (const code of ['GUIDE_CLUSTER_NOT_REGISTRABLE', 'GUIDE_CLUSTER_BASE_CHANGED', 'GUIDE_CLUSTER_CONFLICT_UNRESOLVED', 'GUIDE_CLUSTER_ASSEMBLE_FAILED', 'GUIDE_CLUSTER_REBASE_FAILED', 'GUIDE_CLUSTER_TARGET_UNCHANGED', 'GUIDE_CLUSTER_TARGET_INVALID']) {
      expect(displayMessage(code, '서버 문구')).not.toBe('서버 문구')
    }
    expect(displayMessage('GUIDE_CLUSTER_NOT_REGISTRABLE', 'x', [{ reason: 'NO_TARGET', message: 'x' }])).toBe('넣을 문서를 먼저 연결해 주세요.')
    expect(displayMessage('GUIDE_CLUSTER_NOT_REGISTRABLE', 'x', [{ reason: 'JUDGMENT', message: 'x' }])).toContain('직접 반영')
    expect(displayMessage('GUIDE_CLUSTER_CONFLICT_UNRESOLVED', 'x', [{ reason: 'CONFLICT', message: 'x', value: '3.3' as never }])).toContain('항목 3.3')
    expect(displayMessage('GUIDE_CLUSTER_ASSEMBLE_FAILED', 'x', [{ reason: 'ASSEMBLE', message: '묶음 12: 기준 원문이 다름' }])).toContain('묶음 12: 기준 원문이 다름')
  })
})

describe('API (GC-06·07·08)', () => {
  it('등록은 열람 범위·전송 정책을 서버 값으로 보내고, 응답의 경고를 남긴다', async () => {
    route = (m, p) => (m === 'POST' && p === '/guide-clusters/12/register' ? json(200, { ...detail({ registeredVersion: ver({ id: 40, version: 'v2.1', isCurrent: false, ingestStatus: 'PENDING' }) }), warnings: ['개인정보로 보이는 글이 있어요'] }) : undefined)
    const c = await import('../src/api/caseClusters')
    const r = await c.registerCase('12', 3, '담당자 이상', '마스킹 후 허용')
    expect(bodyOf('POST', '/guide-clusters/12/register')).toEqual({ draftRevision: 3, viewScope: 'AGENT', transferPolicy: 'MASKED' })
    expect(r.ok && r.data.state).toBe('preparing')
    expect(r.ok && r.data.server?.fresh).toEqual(['개인정보로 보이는 글이 있어요'])
  })

  it('다시 맞추기는 draftRevision 만 보내고, 풀리지 않은 충돌을 담는다', async () => {
    route = (m, p) =>
      m === 'POST' && p === '/guide-clusters/12/rebase'
        ? json(200, { ...detail({ judgment: 'CHANGE', targetSection: '3.3', targetMd: '옛 3.3', draftRevision: 3, conflicts: [{ section: '3.3', kind: 'CHANGED', message: '현행에서 바뀜', oldMd: '옛 3.3', newMd: '새 3.3' }] }), warnings: [] })
        : undefined
    const c = await import('../src/api/caseClusters')
    const r = await c.rebaseServerCase('12', 2)
    expect(bodyOf('POST', '/guide-clusters/12/rebase')).toEqual({ draftRevision: 2 })
    expect(r.ok && r.data.server?.conflicts?.[0]).toMatchObject({ section: '3.3', newMd: '새 3.3' })
    expect(r.ok && r.data.target?.section).toBe('3.3')
    expect(r.ok && r.data.before).toBe('옛 3.3')
  })

  it('넣을 문서 변경은 문서 id 와 (변경만) 항목 번호를 보낸다', async () => {
    route = (m, p) => (m === 'POST' && p === '/guide-clusters/12/target' ? json(200, { ...detail({ draftRevision: 3 }), warnings: [] }) : undefined)
    const c = await import('../src/api/caseClusters')
    await c.changeCaseTarget('12', 2, 7, ' 3.3 ')
    expect(bodyOf('POST', '/guide-clusters/12/target')).toEqual({ draftRevision: 2, documentId: 7, targetSection: '3.3' })
    await c.changeCaseTarget('12', 3, 8)
    expect(fetchMock.mock.calls.filter((x) => String(x[0]).endsWith('/target')).map((x) => JSON.parse((x[1] as RequestInit).body as string))[1]).toEqual({ draftRevision: 3, documentId: 8 })
  })

  it('초안이 어긋나면(409) 최신 상세를 다시 읽는다', async () => {
    route = (m, p) => {
      if (m === 'POST' && p === '/guide-clusters/12/register') return json(409, err('GUIDE_CLUSTER_DRAFT_CONFLICT'))
      if (m === 'GET' && p === '/guide-clusters/12') return json(200, detail({ draftRevision: 5 }))
    }
    const c = await import('../src/api/caseClusters')
    const r = await c.registerCase('12', 2, '전 직원', '금지')
    expect(!r.ok && r.error.code).toBe('GUIDE_CLUSTER_DRAFT_CONFLICT')
    expect(calls()).toContain('GET /guide-clusters/12')
    expect(c.getServerCases().find((x) => x.id === '12')?.server?.draftRevision).toBe(5)
  })
})

describe('검토 패널 (서버 연결)', () => {
  it('고친 글이 있으면 먼저 저장하고, 그 응답의 번호로 등록한다', async () => {
    route = (m, p) => {
      if (m === 'GET' && p === '/guide-clusters/12') return json(200, detail())
      if (m === 'PATCH' && p === '/guide-clusters/12') return json(200, detail({ draftRevision: 3, draftMd: '### 3.4 고친 글' }))
      if (m === 'POST' && p === '/guide-clusters/12/register') return json(200, { ...detail({ draftRevision: 3, registeredVersion: ver({ id: 40, version: 'v2.1', isCurrent: false, ingestStatus: 'PENDING' }) }), warnings: [] })
      if (m === 'GET' && p.startsWith('/guide-clusters?')) return listOf([sum({ registeredVersion: ver({ id: 40, version: 'v2.1', isCurrent: false, ingestStatus: 'PENDING' }) })])
    }
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const field = await within(panel).findByLabelText(/AI 수정 제안문/)
    await userEvent.type(field, ' 추가')
    await userEvent.click(within(panel).getByRole('button', { name: '승인하고 초안 등록' }))
    const dlg = await screen.findByRole('dialog', { name: '등록 설정을 확인해 주세요' })
    await userEvent.click(within(dlg).getByRole('button', { name: '초안으로 등록' }))
    await waitFor(() => expect(bodyOf('POST', '/guide-clusters/12/register')).toMatchObject({ draftRevision: 3 }))
    const order = calls().filter((x) => x.startsWith('PATCH') || x.includes('/register'))
    expect(order).toEqual(['PATCH /guide-clusters/12', 'POST /guide-clusters/12/register'])
    expect(bodyOf('PATCH', '/guide-clusters/12')).toMatchObject({ draftRevision: 2 })
  })

  it('기준 가이드가 바뀌었으면 등록을 막고 "다시 맞추기"를 보인다', async () => {
    route = (m, p) => (m === 'GET' && p === '/guide-clusters/12' ? json(200, detail({ baseChanged: true, currentVersion: ver({ id: 33, version: 'v2.1' }) })) : undefined)
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const approve = await within(panel).findByRole('button', { name: '승인하고 초안 등록' })
    expect(approve).toBeDisabled()
    expect(approve).toHaveAttribute('title', expect.stringContaining('다시 맞추기'))
    expect(within(panel).getByRole('button', { name: '다시 맞추기' })).toBeInTheDocument()
  })

  it('풀리지 않은 충돌은 예전 원문과 지금 현행 원문을 나란히 보이고 등록을 막는다', async () => {
    route = (m, p) =>
      m === 'GET' && p === '/guide-clusters/12'
        ? json(200, detail({ judgment: 'CHANGE', targetSection: '3.3', targetMd: '옛 3.3 원문', conflicts: [{ section: '3.3', kind: 'CHANGED', message: '현행에서 항목이 바뀜', oldMd: '옛 3.3 원문', newMd: '새 3.3 원문' }] }))
        : undefined
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const sec = await within(panel).findByRole('region', { name: '새 현행과 달라진 항목' })
    expect(within(sec).getByText('옛 3.3 원문')).toBeInTheDocument()
    expect(within(sec).getByText('새 3.3 원문')).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeDisabled()
  })

  it('보안 사고 사례는 초안 편집·등록 없이 근거 티켓을 보고 "반영했어요"나 "반영 안함"만 고른다', async () => {
    route = (m, p) => (m === 'GET' && p === '/guide-clusters/12' ? json(200, detail({ judgment: 'SEC_MANUAL', category: { code: 'SEC', name: '정보보안' }, draftMd: '### 의심 메일' })) : undefined)
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(await within(panel).findByText('보안 사고 사례', { selector: 'h3' })).toBeInTheDocument()
    expect(within(panel).getByText(/AI가 만든 초안은 없어요/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: '승인하고 초안 등록' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: '임시 저장' })).toBeNull()
    expect(within(panel).queryByRole('textbox')).toBeNull()
    expect(within(panel).getByRole('button', { name: '반영 안함' })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: '가이드·매뉴얼에 반영했어요' })).toBeInTheDocument()
  })

  it('새 가이드는 문서를 연결하기 전에는 등록할 수 없고, 새 문서를 만들어 연결할 수 있다', async () => {
    let linked = false
    route = (m, p, body) => {
      if (m === 'GET' && p === '/guide-clusters/12') return json(200, detail({ judgment: 'NEW_GUIDE', targetDocument: linked ? { id: 77, docCode: 'IT-NET-009', title: 'VPN 인터넷 끊김' } : null, draftRevision: linked ? 3 : 2 }))
      if (m === 'GET' && p.startsWith('/documents')) return json(200, { items: [{ id: 3, docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드', docType: 'GUIDE', categoryCode: 'NET', isActive: true, currentVersion: { id: 31, version: 'v2.0', viewScope: 'ALL', transferPolicy: 'ALLOWED' } }], page: 1, size: 100, totalCount: 1, totalPages: 1 })
      if (m === 'POST' && p === '/documents') return json(201, { id: 77, docCode: body?.docCode, title: body?.title, docType: 'GUIDE', categoryCode: 'NET', isActive: true, currentVersion: null })
      if (m === 'POST' && p === '/guide-clusters/12/target') {
        linked = true
        return json(200, { ...detail({ judgment: 'NEW_GUIDE', targetDocument: { id: 77, docCode: 'IT-NET-009', title: 'VPN 인터넷 끊김' }, draftRevision: 3 }), warnings: [] })
      }
      if (m === 'GET' && p.startsWith('/guide-clusters?')) return listOf([sum({ judgment: 'NEW_GUIDE' })])
    }
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const approve = await within(panel).findByRole('button', { name: '승인하고 초안 등록' })
    expect(approve).toBeDisabled()
    expect(approve).toHaveAttribute('title', '넣을 문서를 먼저 연결해 주세요.')
    await userEvent.click(within(panel).getByRole('button', { name: '문서 연결' }))
    const dlg = await screen.findByRole('dialog', { name: '새 가이드 문서 연결' })
    await userEvent.click(within(dlg).getByRole('button', { name: '새 문서 만들기' }))
    await waitFor(() => expect((within(dlg).getByLabelText('문서 번호') as HTMLInputElement).value).toBe('IT-NET-002'))
    await userEvent.clear(within(dlg).getByLabelText('문서 번호'))
    await userEvent.type(within(dlg).getByLabelText('문서 번호'), 'IT-NET-009')
    await userEvent.click(within(dlg).getByRole('button', { name: '만들고 연결' }))
    await waitFor(() => expect(bodyOf('POST', '/guide-clusters/12/target')).toEqual({ draftRevision: 2, documentId: 77 }))
    expect(bodyOf('POST', '/documents')).toMatchObject({ docCode: 'IT-NET-009', docType: 'GUIDE', categoryCode: 'NET' })
    expect(calls().indexOf('POST /documents')).toBeLessThan(calls().indexOf('POST /guide-clusters/12/target'))
    await waitFor(() => expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeEnabled())
  })

  it('검토 정보의 추가 항목(변경 이유·추측한 칸·해결 방법 차이)을 AI 판단 구역에 보인다', async () => {
    route = (m, p) =>
      m === 'GET' && p === '/guide-clusters/12'
        ? json(200, detail({ judgment: 'CHANGE', targetSection: '3.3', targetMd: '옛', reviewInfo: { reason: '첫째 이유\n둘째 이유', warnings: [], change_note: '순서를 바꿨어요', guessed: ['원인'], differences: ['한 건은 재시작으로 해결'] } }))
        : undefined
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const sec = await within(panel).findByRole('region', { name: 'AI 판단' })
    expect(within(sec).getByText('첫째 이유')).toBeInTheDocument()
    expect(within(sec).getByText('둘째 이유')).toBeInTheDocument()
    expect(sec).toHaveTextContent('변경 이유 · 순서를 바꿨어요')
    expect(sec).toHaveTextContent('AI가 추측해서 쓴 칸 · 원인')
    expect(within(sec).getByText('티켓마다 해결 방법이 달라요')).toBeInTheDocument()
    expect(within(sec).getByText('한 건은 재시작으로 해결')).toBeInTheDocument()
  })

  it('매뉴얼 후보는 초안이 없어도 AI가 정리한 내용과 가까운 매뉴얼 항목을 보인다', async () => {
    route = (m, p) =>
      m === 'GET' && p === '/guide-clusters/12'
        ? json(200, detail({ judgment: 'MANUAL_CANDIDATE', draftMd: null, targetDocument: null, reviewInfo: { reason: '내부 절차', warnings: [], manual_note: '- 명단은 인사팀 파일 기준', manual_items: ['IT-MAN-001 3.2 계정 발급'] } }))
        : undefined
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const sec = await within(panel).findByRole('region', { name: '가이드 내용' })
    expect(within(sec).getByText('매뉴얼에 넣을 만한 내용')).toBeInTheDocument()
    expect(within(sec).getByText('- 명단은 인사팀 파일 기준')).toBeInTheDocument()
    expect(within(sec).getByText('가까운 매뉴얼 항목')).toBeInTheDocument()
    expect(within(sec).getByText('IT-MAN-001 3.2 계정 발급')).toBeInTheDocument()
  })

  it('새 가이드는 새 가이드 제목을 보이고, "(작성 필요)"가 남은 장이 있으면 등록을 막고 장을 알려 준다', async () => {
    route = (m, p) =>
      m === 'GET' && p === '/guide-clusters/12'
        ? json(200, detail({ judgment: 'NEW_GUIDE', draftMd: '# 제목\n\n## 1. 개요\n\n(작성 필요)\n\n## 2. 먼저 확인할 사항\n\n(작성 필요)\n\n## 3. 증상별 조치 방법\n\n### 3.1 항목\n', reviewInfo: { reason: 'r', warnings: [], guide_title: '노트북 배터리 신고 절차' } }))
        : undefined
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(await within(panel).findByDisplayValue('노트북 배터리 신고 절차')).toBeInTheDocument()
    expect(await within(panel).findByText('아직 채워야 할 장이 있어요.')).toBeInTheDocument()
    expect(panel).toHaveTextContent('1. 개요, 2. 먼저 확인할 사항')
    const approve = within(panel).getByRole('button', { name: '승인하고 초안 등록' })
    expect(approve).toBeDisabled()
    expect(approve).toHaveAttribute('title', expect.stringContaining('1. 개요'))
  })

  it('변경은 바꿀 항목 번호가 있어야 문서를 바꿀 수 있다', async () => {
    route = (m, p) => {
      if (m === 'GET' && p === '/guide-clusters/12') return json(200, detail({ judgment: 'CHANGE', targetSection: '3.3', targetMd: '옛 3.3 원문' }))
      if (m === 'GET' && p.startsWith('/documents')) return json(200, { items: [{ id: 7, docCode: 'IT-NET-002', title: '사내 Wi-Fi 가이드', docType: 'GUIDE', categoryCode: 'NET', isActive: true, currentVersion: { id: 71, version: 'v1.0', viewScope: 'ALL', transferPolicy: 'ALLOWED' } }], page: 1, size: 100, totalCount: 1, totalPages: 1 })
    }
    await mountPanel()
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    await userEvent.click(await within(panel).findByRole('button', { name: '넣을 문서 변경' }))
    const dlg = await screen.findByRole('dialog', { name: '넣을 문서 변경' })
    const sec = within(dlg).getByLabelText('바꿀 항목 번호') as HTMLInputElement
    expect(sec.value).toBe('3.3')
    await userEvent.clear(sec)
    await userEvent.click(within(dlg).getByRole('button', { name: '문서 변경' }))
    expect(await within(dlg).findByText(/바꿀 항목 번호를 적어 주세요/)).toBeInTheDocument()
    expect(calls().some((x) => x.includes('/target'))).toBe(false)
  })
})

describe('목록 탭: 종류 이름과 분석 일정', () => {
  it('서버가 판단한 종류 이름(항목 추가·변경·새 가이드)을 그대로 보이고, 마지막·다음 분석 시각을 보인다', async () => {
    route = (method, path) => {
      if (path === '/guide-clusters/analysis-status') return json(200, { lastAnalyzedAt: '2026-11-09T00:00:00+09:00', nextAnalysisAt: '2026-11-16T00:00:00+09:00', lastRunStatus: 'FAILED' })
      if (method === 'GET' && path.startsWith('/guide-clusters?'))
        return listOf([sum({ id: 1, title: '추가 건' }), sum({ id: 2, title: '변경 건', judgment: 'CHANGE' }), sum({ id: 3, title: '새 건', judgment: 'NEW_GUIDE', targetDocument: null })])
    }
    const { AuthProvider } = await import('../src/core/session')
    const { CaseGuideTab } = await import('../src/views/admin/CaseGuideTab')
    render(
      <AuthProvider>
        <CaseGuideTab onReview={() => {}} onVersion={() => {}} onGoLive={() => {}} />
      </AuthProvider>,
    )
    await screen.findAllByRole('region')
    expect(screen.getByText('항목 추가')).toBeInTheDocument()
    expect(screen.getByText('변경')).toBeInTheDocument()
    expect(screen.getByText('새 가이드')).toBeInTheDocument()
    expect(screen.queryByText('기존 가이드 보강')).toBeNull()
    expect(await screen.findByText(/마지막 분석 \d+월 \d+일/)).toBeInTheDocument()
    expect(screen.getByText(/가장 최근 분석이 실패했어요/)).toBeInTheDocument()
  })
})
