/**
 * 관리자 가이드 관리 (EMP-1178 이건우). 모의 모드 화면·API 테스트와, 가짜 fetch 로 서버 계약(docs/api/04 DC-01·02·06·07·09)을 확인하는 서버 모드 테스트.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { createGuideDraft, listGuideVersions, listGuides, nextDocCode, nextVersion, normalizeVersion, resetGuideMock, setGuideCurrent, setGuideNote, setGuideTransfer, uploadGuide, uploadGuideVersion } from '../src/api/guides'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

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
const file = () => new File(['x'], 'IT-NET-004.pdf', { type: 'application/pdf' })

describe('가이드 API (모의)', () => {
  beforeEach(() => resetGuideMock())

  it('가이드 목록과 버전을 준다', async () => {
    const r = await listGuides(admin())
    expect(r.ok && r.data).toHaveLength(10)
    const g = r.ok ? r.data.find((x) => x.docCode === 'IT-NET-001')! : null
    expect(g?.current).toEqual({ version: 'v2', tx: '허용' })
    const v = await listGuideVersions(admin(), g!.id)
    expect(v.ok && v.data.map((x) => [x.version, x.state])).toEqual([['v3', '초안'], ['v2', '현행'], ['v1', '만료']])
  })

  it('현행 전환은 검색 준비가 끝난 버전만 되고, 이전 버전으로 되돌릴 수도 있다', async () => {
    expect((await setGuideCurrent(admin(), 1, 13)).ok).toBe(false) // v3 는 준비 중
    expect((await setGuideCurrent(admin(), 1, 11)).ok).toBe(true) // 만료 v1 로 되돌림
    const v = await listGuideVersions(admin(), 1)
    expect(v.ok && v.data.filter((x) => x.state === '현행').map((x) => x.version)).toEqual(['v1'])
  })

  it('외부 전송 정책과 메모를 바꾼다. 관리자만 쓸 수 있다', async () => {
    expect((await setGuideTransfer(admin(), 9, 91, '허용', '개인정보 없음')).ok).toBe(true)
    const l = await listGuides(admin())
    expect(l.ok && l.data.find((x) => x.id === 9)?.current?.tx).toBe('허용')
    expect((await setGuideNote(admin(), 1, 12, '새 메모')).ok).toBe(true)
    const staff = MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1004')!
    expect((await listGuides(staff)).ok).toBe(false)
  })

  it('업로드는 문서 번호 형식·중복을 막고, 초안으로 만든 뒤 잠시 뒤 검색 준비가 끝난다', async () => {
    expect(await uploadGuide(admin(), { file: file(), docCode: 'net-4', title: '새', cat: 'NET', scope: '관리자 전용', tx: '금지' })).toMatchObject({ ok: false, error: { code: 'VALIDATION_ERROR' } })
    expect(await uploadGuide(admin(), { file: file(), docCode: 'IT-NET-001', title: '새', cat: 'NET', scope: '관리자 전용', tx: '금지' })).toMatchObject({ ok: false, error: { code: 'DOCUMENT_CODE_DUPLICATE' } })
    const r = await uploadGuide(admin(), { file: file(), docCode: 'IT-NET-004', title: '사내 Wi-Fi 가이드', cat: 'NET', scope: '사내 제한', tx: '마스킹 후 허용' })
    expect(r.ok && r.data.versions?.[0]).toMatchObject({ version: 'v1.0', state: '초안', ready: '준비 중', scope: '사내 제한', tx: '마스킹 후 허용' })
    await waitFor(async () => {
      const v = await listGuideVersions(admin(), r.ok ? r.data.id : 0)
      expect(v.ok && v.data[0].ready).toBe('준비 완료')
    }, { timeout: 4500 })
  })

  it('기존 가이드에 새 버전을 올리고, 같은 버전 이름은 막는다. 번호·버전 이름 도우미', async () => {
    expect(await uploadGuideVersion(admin(), 1, { file: file(), version: 'v2', scope: '사내 일반', tx: '허용' })).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_DUPLICATE' } })
    const r = await uploadGuideVersion(admin(), 1, { file: file(), version: 'v4', scope: '사내 제한', tx: '금지' })
    expect(r.ok && r.data).toMatchObject({ version: 'v4', state: '초안', ready: '준비 중', scope: '사내 제한', tx: '금지' })
    const v = await listGuideVersions(admin(), 1)
    expect(v.ok && v.data.map((x) => x.version)).toEqual(['v4', 'v3', 'v2', 'v1'])
    const l = await listGuides(admin())
    if (!l.ok) throw new Error('목록')
    expect(nextDocCode(l.data, 'NET')).toBe('IT-NET-002')
    expect(nextDocCode(l.data, 'ACC')).toBe('IT-ACC-004')
    expect(nextDocCode([], 'SW')).toBe('IT-SW-001')
    expect(nextVersion(v.ok ? v.data : [])).toBe('v5.0')
    expect([normalizeVersion('4'), normalizeVersion(' V4 '), normalizeVersion('v1.3'), normalizeVersion('a')]).toEqual(['v4', 'v4', 'v1.3', null])
  })

  it('해결 사례 초안은 기존 가이드에 새 버전을, 없으면 새 가이드를 만든다', async () => {
    const up = await createGuideDraft(admin(), { cat: 'NET', title: 'VPN 가이드 보강', existId: 1, note: '주간 분석' })
    expect(up.ok && up.data.version).toBe('v4')
    const nw = await createGuideDraft(admin(), { cat: 'HW', title: '모니터 깜빡임 가이드', existId: null, note: '일간 분석' })
    expect(nw.ok && nw.data.guide.docCode).toMatch(/^IT-HW-\d{3}$/)
  })
})

describe('가이드 관리 화면', () => {
  beforeEach(() => resetGuideMock())

  it('분류별 아코디언을 펼쳐 버전 표를 보고, 담당자는 들어올 수 없다', async () => {
    const { unmount } = renderAs('EMP-1178', '/guides')
    expect(await screen.findByRole('heading', { name: 'AI 답변의 근거를 관리해요', level: 1 }, SLOW)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /^VPN·네트워크/ }, SLOW))
    await userEvent.click(await screen.findByRole('button', { name: /^IT-NET-001 VPN 접속 장애 대응 가이드\s*현행/ }))
    const row = (await screen.findAllByRole('row')).find((r) => within(r).queryByText('v3'))!
    expect(within(row).getByText('준비 중')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: '현행 전환' })).toBeDisabled()
    unmount()
    renderAs('EMP-1004', '/guides')
    expect(await screen.findByRole('heading', { name: /내 담당 문의/ }, SLOW)).toBeInTheDocument()
  })

  it('외부 전송 정책을 느슨하게 바꾸면 사유를 요구하고, 엄격하게 바꾸면 바로 바뀐다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /^정보보안/ }, SLOW))
    await userEvent.click(await screen.findByRole('button', { name: /^IT-SEC-004.*현행/ }))
    const grp = await screen.findByRole('group', { name: 'v2 외부 AI 전송' })
    await userEvent.click(within(grp).getByRole('button', { name: '허용' }))
    const dlg = await screen.findByRole('dialog', { name: '외부 전송 정책 변경' })
    await userEvent.click(within(dlg).getByRole('button', { name: '변경' }))
    expect(await within(dlg).findByText('변경 사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('변경 사유 (필수)'), '개인정보 없음을 확인함')
    await userEvent.click(within(dlg).getByRole('button', { name: '변경' }))
    expect(await screen.findByText('외부 전송 정책을 허용으로 바꿨어요.', {}, SLOW)).toBeInTheDocument()
    await userEvent.click(within(await screen.findByRole('group', { name: 'v2 외부 AI 전송' })).getByRole('button', { name: '금지' }))
    expect(await screen.findByText('외부 전송 정책을 금지로 바꿨어요.', {}, SLOW)).toBeInTheDocument()
  })

  it('새 가이드 만들기: 문서 번호는 분류에 따라 자동으로 정해지고(입력 불가) 올리면 새 가이드가 열린다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    await userEvent.click(within(dlg).getByRole('button', { name: '새 가이드 만들기' }))
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await within(dlg).findByText('파일을 선택해 주세요.')).toBeInTheDocument()
    expect(within(dlg).getByText('분류를 선택해 주세요.')).toBeInTheDocument()
    expect(within(dlg).getByText('가이드 제목을 입력해 주세요.')).toBeInTheDocument()
    await userEvent.upload(within(dlg).getByLabelText('파일'), file())
    expect(within(dlg).getByRole('button', { name: '선택 취소' })).toBeInTheDocument()
    await userEvent.selectOptions(within(dlg).getByLabelText('분류'), 'NET')
    const code = within(dlg).getByLabelText('문서 번호')
    expect(code).toHaveValue('IT-NET-002')
    expect(code).toHaveAttribute('readonly')
    expect(within(dlg).getByLabelText('버전')).toHaveValue('v1.0')
    await userEvent.type(within(dlg).getByLabelText('가이드 제목'), '사내 Wi-Fi 접속 가이드')
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await screen.findByText(/초안으로 올렸어요/, {}, SLOW)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /IT-NET-002 사내 Wi-Fi 접속 가이드/ }, SLOW)).toHaveAttribute('aria-expanded', 'true')
  })

  it('기존 가이드에 새 버전 만들기: 문서를 고르면 모든 버전이 보이고, 겹치는 버전은 막힌다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    // 가이드 목록이 오면 기본이 "기존 가이드에 새 버전 만들기"가 된다
    await waitFor(() => expect(within(dlg).getByRole('button', { name: '기존 가이드에 새 버전 만들기' })).toHaveAttribute('aria-pressed', 'true'), SLOW)
    await userEvent.upload(within(dlg).getByLabelText('파일'), file())
    await userEvent.selectOptions(within(dlg).getByLabelText('분류'), 'NET')
    await userEvent.selectOptions(within(dlg).getByLabelText('문서'), within(dlg).getByRole('option', { name: /IT-NET-001/ }))
    expect(await within(dlg).findByText('이 가이드의 버전 3개')).toBeInTheDocument()
    expect(within(dlg).getAllByRole('listitem').map((li) => li.textContent)).toEqual([expect.stringContaining('v3'), expect.stringContaining('v2'), expect.stringContaining('v1')])
    expect(within(dlg).getByLabelText('버전')).toHaveValue('v4.0')
    const ver = within(dlg).getByLabelText('버전')
    await userEvent.clear(ver)
    await userEvent.type(ver, '2')
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await within(dlg).findByText('이미 있는 버전이에요. 다른 번호를 적어 주세요.')).toBeInTheDocument()
    await userEvent.clear(ver)
    await userEvent.type(ver, 'v4')
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await screen.findByText(/초안으로 올렸어요/, {}, SLOW)).toBeInTheDocument()
  })

  it('해결 사례 탭에서 묶음을 보고 초안 미리보기를 열 수 있다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /해결 사례 → 가이드 초안/ }, SLOW))
    expect(await screen.findByText(/매일 자정에 AI가 해결 완료/, {}, SLOW)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '주간' }))
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^(신규 가이드 초안|버전 업데이트 초안)$/ }).length).toBeGreaterThan(0), SLOW)
    await userEvent.click(screen.getAllByRole('button', { name: /^(신규 가이드 초안|버전 업데이트 초안)$/ })[0])
    expect(await screen.findByRole('dialog', { name: '가이드 초안 미리보기' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ 서버 모드 */
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const doc = (id: number, code: string, over: Record<string, unknown> = {}) => ({ id, docCode: code, docType: 'GUIDE', title: `제목 ${id}`, categoryCode: 'NET', isActive: true, currentVersion: { id: id * 10, version: 'v1.2', viewScope: 'ALL', transferPolicy: 'MASKED', registeredAt: '2026-10-19T15:00:00+09:00' }, createdAt: '2026-10-19T15:00:00+09:00', ...over })
const ver = (id: number, over: Record<string, unknown> = {}) => ({ id, documentId: 3, version: 'v1.2', viewScope: 'ALL', transferPolicy: 'ALLOWED', isCurrent: false, versionState: 'DRAFT', ingestStatus: 'DONE', ingestError: null, chunkCount: 16, ...over })

describe('서버 모드 가이드 (VITE_USE_MOCK_GUIDE=false)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const urls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0])}`)
  async function load() {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_GUIDE', 'false')
    return import('../src/api/guides')
  }
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('문서 목록을 화면의 가이드로 바꾼다 (분류 없는 문서는 뺀다)', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [doc(3, 'IT-NET-001'), doc(4, 'IT-STD-001', { docType: 'STANDARD', categoryCode: null }), doc(5, 'IT-ACC-001', { categoryCode: 'ACC', currentVersion: null })], page: 1, size: 100, totalCount: 3, totalPages: 1 }))
    const r = await api.listGuides(admin())
    expect(r.ok && r.data.map((g) => [g.docCode, g.cat, g.current])).toEqual([
      ['IT-NET-001', 'NET', { version: 'v1.2', tx: '마스킹 후 허용' }],
      ['IT-ACC-001', 'ACC', null],
    ])
    expect(urls()[0]).toBe('GET /api/v1/documents?size=100&page=1&docType=GUIDE&docType=MANUAL&includeInactive=true&sort=docCode,asc')
  })

  it('버전 목록의 상태·적재 상태·정책을 화면 말로 바꾼다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(200, { items: [ver(31, { version: 'v1.3', ingestStatus: 'PENDING' }), ver(12, { isCurrent: true, versionState: 'CURRENT', viewScope: 'ADMIN', transferPolicy: 'BLOCKED' }), ver(9, { versionState: 'EXPIRED', ingestStatus: 'FAILED', ingestError: '본문을 추출하지 못했습니다' })] }))
    const r = await api.listGuideVersions(admin(), 3)
    expect(r.ok && r.data.map((v) => [v.state, v.ready, v.scope, v.tx])).toEqual([
      ['초안', '준비 중', '사내 일반', '허용'],
      ['현행', '준비 완료', '관리자 전용', '금지'],
      ['만료', '준비 실패', '사내 일반', '허용'],
    ])
    expect(r.ok && r.data[2].error).toBe('본문을 추출하지 못했습니다')
  })

  it('현행 전환과 정책 변경은 PATCH 로 보낸다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(200, ver(31, { isCurrent: true, versionState: 'CURRENT' }))).mockResolvedValueOnce(json(200, ver(31, { transferPolicy: 'BLOCKED' })))
    expect((await api.setGuideCurrent(admin(), 3, 31)).ok).toBe(true)
    expect((await api.setGuideTransfer(admin(), 3, 31, '금지', '')).ok).toBe(true)
    expect(urls()).toEqual(['PATCH /api/v1/documents/3/versions/31', 'PATCH /api/v1/documents/3/versions/31'])
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ isCurrent: true })
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ transferPolicy: 'BLOCKED' })
  })

  it('업로드는 문서를 만들고(DC-02) 파일을 multipart 로 올린다(DC-07)', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(201, doc(40, 'IT-NET-004', { currentVersion: null }))).mockResolvedValueOnce(json(202, ver(41, { documentId: 40, version: 'v1', ingestStatus: 'PENDING', transferPolicy: 'MASKED', viewScope: 'AGENT' })))
    const r = await api.uploadGuide(admin(), { file: file(), docCode: 'it-net-004', title: '사내 Wi-Fi', cat: 'NET', scope: '사내 제한', tx: '마스킹 후 허용' })
    expect(r.ok && r.data.versions?.[0]).toMatchObject({ version: 'v1', ready: '준비 중', scope: '사내 제한', tx: '마스킹 후 허용' })
    expect(urls()).toEqual(['POST /api/v1/documents', 'POST /api/v1/documents/40/versions'])
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ docCode: 'IT-NET-004', docType: 'GUIDE', title: '사내 Wi-Fi', categoryCode: 'NET' })
    const form = (fetchMock.mock.calls[1][1] as RequestInit).body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect([form.get('version'), form.get('viewScope'), form.get('transferPolicy')]).toEqual(['v1.0', 'AGENT', 'MASKED'])
    // multipart 경계값은 브라우저가 정해야 하므로 Content-Type 을 직접 붙이지 않는다
    expect(new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers).has('Content-Type')).toBe(false)
  })

  it('서버에 없는 메모·가이드 초안 만들기는 요청하지 않고 안내한다', async () => {
    const api = await load()
    expect(await api.setGuideNote(admin(), 3, 31, '메모')).toMatchObject({ ok: false, error: { code: 'NOT_READY' } })
    expect(await api.createGuideDraft(admin(), { cat: 'NET', title: 't', existId: null, note: '' })).toMatchObject({ ok: false, error: { code: 'NOT_READY' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('문서 번호 중복 오류는 필드 오류로 돌려준다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: 'DOCUMENT_CODE_DUPLICATE', message: '이미 있는 문서 번호예요.', details: [{ field: 'docCode', reason: 'DUPLICATE', message: '이미 있는 문서 번호예요.' }], traceId: 't' } }))
    const r = await api.uploadGuide(admin(), { file: file(), docCode: 'IT-NET-001', title: 't', cat: 'NET', scope: '관리자 전용', tx: '금지' })
    expect(r).toMatchObject({ ok: false, error: { code: 'DOCUMENT_CODE_DUPLICATE' } })
  })
})
