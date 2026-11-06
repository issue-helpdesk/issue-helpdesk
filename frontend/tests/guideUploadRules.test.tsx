/**
 * 가이드 업로드 서버 규칙 반영 (백엔드 정리 261103): 자동 현행 전환 없음, 다음 버전 v3.0 꼴, 파일 머리 version 읽기,
 * 20MB 사전 검사, 문서 등록 성공 후 업로드 실패 재시도(DC-02 다시 안 부름), 적재 실패 파일 교체 재시도(DC-10), 비활성 문서(DC-01 includeInactive·DC-04).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { FIRST_VERSION, MAX_UPLOAD_BYTES, formatBytes, listGuideVersions, mockIngestError, sameVersion, listGuides, nextVersion, readFileVersion, resetGuideMock, retryGuideIngest, setGuideActive, uploadGuide, uploadGuideVersion } from '../src/api/guides'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const pdf = () => new File(['x'], 'IT-NET-004.pdf', { type: 'application/pdf' })

/** 선택 상자(SelectBox)에서 항목 고르기: 칸을 눌러 목록을 열고 항목을 누른다 */
async function choose(scope: HTMLElement, label: string, option: string | RegExp) {
  await userEvent.click(within(scope).getByLabelText(label))
  await userEvent.click(await screen.findByRole('option', { name: option }))
}

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

describe('버전 이름·파일 검사', () => {
  it('다음 버전은 앞자리 + 1 에 .0 이고, 새 가이드 첫 버전은 v1.0 이다', () => {
    expect(nextVersion([{ version: 'v2.0' }, { version: 'v1.0' }])).toBe('v3.0')
    expect(nextVersion([{ version: 'v2' }])).toBe('v3.0')
    expect(nextVersion([])).toBe('v1.0')
    expect(FIRST_VERSION).toBe('v1.0')
  })

  it('md 파일 머리의 version: 값을 읽는다 (다른 형식은 읽지 않는다)', async () => {
    expect(await readFileVersion(new File(['---\ndoc: IT-NET-001\nversion: v2.0\n---\n본문'], 'a.md'))).toBe('v2.0')
    expect(await readFileVersion(new File(['version: 3\n본문'], 'a.txt'))).toBe('v3')
    expect(await readFileVersion(new File(['본문만 있어요'], 'a.md'))).toBeNull()
    expect(await readFileVersion(new File(['version: v9.0'], 'a.pdf'))).toBeNull()
  })

  it('v2 와 v2.0 은 같은 버전으로 본다 (뒤의 .0 은 무시)', () => {
    expect(sameVersion('v2', 'v2.0')).toBe(true)
    expect(sameVersion('2.0.0', 'v2')).toBe(true)
    expect(sameVersion('v2.1', 'v2')).toBe(false)
    expect(sameVersion('v10', 'v1.0')).toBe(false)
  })

  it('서버 한도는 20MB 이다', () => {
    expect(MAX_UPLOAD_BYTES).toBe(20 * 1024 * 1024)
  })
})

describe('가이드 업로드 화면 (모의)', () => {
  beforeEach(() => resetGuideMock())

  it('"검색 준비가 끝나면 현행으로 전환" 체크박스는 없고, 초안으로 올린다는 안내가 있다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    expect(within(dlg).queryByRole('checkbox')).toBeNull()
    expect(within(dlg).getByText(/초안으로 올라가요/)).toBeInTheDocument()
  })

  it('20MB 를 넘는 파일은 고르는 즉시 막는다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    const big = new File(['x'], 'big.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: MAX_UPLOAD_BYTES + 1 })
    await userEvent.upload(within(dlg).getByLabelText('파일'), big)
    expect(await within(dlg).findByText(/파일이 너무 커요\. 20MB 이하 파일을 올려 주세요\. \(선택한 파일 20\.0MB\)/)).toBeInTheDocument()
    expect(within(dlg).queryByRole('button', { name: '선택 취소' })).toBeNull()
  })

  it('고른 파일의 이름·크기를 한도(20MB)와 함께 카드로 보여 주고, 선택 취소로 지운다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    expect(within(dlg).getByText(/클릭해서 파일 고르기/)).toBeInTheDocument()
    expect(within(dlg).getByText(/PDF·DOCX·PPTX·MD·TXT · 파일 1개 · 최대 20MB/)).toBeInTheDocument()
    const f = new File(['x'], 'DOC-HR-014_규정_v2.0.pdf', { type: 'application/pdf' })
    Object.defineProperty(f, 'size', { value: 2.5 * 1024 * 1024 })
    await userEvent.upload(within(dlg).getByLabelText('파일'), f)
    expect(await within(dlg).findByText('DOC-HR-014_규정_v2.0.pdf')).toBeInTheDocument()
    expect(within(dlg).getByText('파일을 확인하는 중…')).toBeInTheDocument() // 잠깐 확인 중이 보인다
    expect(within(dlg).queryByText(/클릭해서 파일 고르기/)).toBeNull() // 끌어다 놓는 칸은 사라진다
    expect(await within(dlg).findByText('용량 2.5MB')).toBeInTheDocument() // 확인이 끝난 뒤 크기가 보인다(막대는 없다)
    await userEvent.click(within(dlg).getByRole('button', { name: '선택 취소' }))
    expect(within(dlg).queryByText('DOC-HR-014_규정_v2.0.pdf')).toBeNull()
  })

  it('파일 크기 표기', () => {
    expect([formatBytes(500), formatBytes(2048), formatBytes(34 * 1024), formatBytes(2.5 * 1024 * 1024)]).toEqual(['500B', '2.0KB', '34KB', '2.5MB'])
  })

  it('이미 있는 v2 를 v2.0 으로 올리려 하면 같은 버전이라고 막는다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    await waitFor(() => expect(within(dlg).getByRole('button', { name: '기존 가이드에 새 버전 만들기' })).toHaveAttribute('aria-pressed', 'true'), SLOW)
    await userEvent.upload(within(dlg).getByLabelText('파일'), pdf())
    await choose(dlg, '분류', /계정·로그인/)
    await choose(dlg, '문서', /IT-ACC-001/) // 모의 데이터에서 현행이 v2
    const ver = within(dlg).getByLabelText('버전')
    await userEvent.clear(ver)
    await userEvent.type(ver, 'v2.0')
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await within(dlg).findByText(/이미 있는 버전 v2과 같은 번호예요/)).toBeInTheDocument()
  })

  it('md 파일을 고르면 머리의 버전으로 채우고, 다르게 적으면 막는다', async () => {
    renderAs('EMP-1178', '/guides')
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    await waitFor(() => expect(within(dlg).getByRole('button', { name: '기존 가이드에 새 버전 만들기' })).toHaveAttribute('aria-pressed', 'true'), SLOW)
    await userEvent.upload(within(dlg).getByLabelText('파일'), new File(['---\nversion: v7.0\n---\n본문'], 'a.md'))
    await waitFor(() => expect(within(dlg).getByLabelText('버전')).toHaveValue('v7.0'))
    await choose(dlg, '분류', /네트워크/)
    await choose(dlg, '문서', /IT-NET-001/)
    const ver = within(dlg).getByLabelText('버전')
    await userEvent.clear(ver)
    await userEvent.type(ver, 'v8.0')
    await userEvent.click(within(dlg).getByRole('button', { name: '업로드' }))
    expect(await within(dlg).findByText(/파일 안의 version\(v7\.0\)과 달라요/)).toBeInTheDocument()
  })

  it('비활성 문서는 목록에 표시되고, 활성화는 확인을 한 번 더 받는다. 새 버전 문서 선택에서는 빠진다', async () => {
    const r = await listGuides(admin())
    expect(r.ok && r.data.every((g) => g.isActive)).toBe(true)
    await setGuideActive(admin(), 1, false)
    renderAs('EMP-1178', '/guides')
    // 새 버전을 올릴 문서 선택에서는 비활성 문서가 빠진다
    await userEvent.click(await screen.findByRole('button', { name: /가이드 파일 업로드/ }, SLOW))
    const up = await screen.findByRole('dialog', { name: '가이드 파일 업로드' })
    await waitFor(() => expect(within(up).getByRole('button', { name: '기존 가이드에 새 버전 만들기' })).toHaveAttribute('aria-pressed', 'true'), SLOW)
    await choose(up, '분류', /네트워크/)
    expect(within(up).getByText(/이 분류의 문서가 모두 비활성이에요/)).toBeInTheDocument()
    await userEvent.click(within(up).getByRole('button', { name: '취소' }))
    // 목록에는 비활성 표시와 함께 남는다 (분류를 펼쳐야 보인다)
    await userEvent.click(await screen.findByRole('button', { name: /모두 펼치기/ }, SLOW))
    const row = (await screen.findAllByRole('button', { name: /IT-NET-001/ }, SLOW)).find((b) => within(b).queryByText('비활성'))!
    expect(row).toBeTruthy()
    await userEvent.click(row)
    await userEvent.click(await screen.findByRole('button', { name: 'IT-NET-001 활성화' }, SLOW))
    const dlg = await screen.findByRole('dialog', { name: '가이드를 활성화할까요?' })
    expect(within(dlg).getByText(/바로 검색·답변에 쓰여요/)).toBeInTheDocument()
    expect(within(dlg).getByText(/다시 게시되지 않아요/)).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('button', { name: '활성화' }))
    await waitFor(() => expect(screen.queryByText('비활성')).toBeNull(), SLOW)
  })
})

describe('모의 적재 실패 시연', () => {
  beforeEach(() => resetGuideMock())

  it('이름·크기로 실패 사유를 정한다 (스캔 PDF·문서 번호 불일치·빈 파일, 나머지는 성공)', () => {
    expect(mockIngestError('sample_scanned.pdf', 100, 'IT-ACC-003')).toMatch(/글자를 찾지 못했습니다.*스캔본/)
    expect(mockIngestError('fail_doc.md', 100, 'IT-ACC-003')).toMatch(/문서 번호.*IT-ACC-003/)
    expect(mockIngestError('a.pdf', 0, 'IT-ACC-003')).toBe('빈 파일입니다.')
    expect(mockIngestError('가이드.pdf', 100, 'IT-ACC-003')).toBeNull()
  })

  it('스캔 PDF 를 올리면 준비 실패와 사유가 남고, 파일을 바꿔 다시 시도하면 준비 완료가 된다', async () => {
    const up = await uploadGuideVersion(admin(), 4, { file: new File(['x'], 'sample_scanned.pdf', { type: 'application/pdf' }), version: 'v3.0', scope: '전 직원', tx: '허용' })
    expect(up.ok).toBe(true)
    const id = up.ok ? up.data.id : 0
    const find = async () => {
      const v = await listGuideVersions(admin(), 4)
      return v.ok ? v.data.find((x) => x.id === id) : undefined
    }
    await waitFor(async () => expect((await find())?.ready).toBe('준비 실패'), { timeout: 4500 })
    expect((await find())?.error).toMatch(/스캔본/)
    // 같은 파일로 다시 시도해도 같은 이유로 실패한다
    await retryGuideIngest(admin(), 4, id)
    await waitFor(async () => expect((await find())?.ready).toBe('준비 실패'), { timeout: 4500 })
    // 글자가 있는 파일로 바꿔 다시 시도하면 성공한다
    await retryGuideIngest(admin(), 4, id, new File(['x'], 'IT-ACC-003_원본.pdf', { type: 'application/pdf' }))
    await waitFor(async () => expect((await find())?.ready).toBe('준비 완료'), { timeout: 4500 })
    expect((await find())?.error).toBeUndefined()
  }, 20_000)
})

describe('서버 모드 가이드 업로드 규칙 (VITE_USE_MOCK_GUIDE=false)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const urls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0]).replace(/^https?:\/\/[^/]+/, '')}`)
  const load = async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_GUIDE', 'false')
    return import('../src/api/guides')
  }
  const doc = (id: number, code: string) => ({ id, docCode: code, docType: 'GUIDE', title: 't', categoryCode: 'NET', isActive: true, currentVersion: null })
  const ver = (id: number, extra: Record<string, unknown> = {}) => ({ id, documentId: 40, version: 'v1.0', viewScope: 'ALL', transferPolicy: 'ALLOWED', isCurrent: false, versionState: 'DRAFT', ingestStatus: 'PENDING', ingestError: null, ...extra })
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('문서 등록(DC-02)이 됐는데 업로드(DC-07)가 실패하면, 다시 올릴 때 DC-02 를 다시 부르지 않는다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(201, doc(40, 'IT-NET-004'))).mockResolvedValueOnce(json(500, { error: { code: 'INTERNAL_ERROR', message: '서버 오류' } })).mockResolvedValueOnce(json(202, ver(41)))
    const made: number[] = []
    const base = { file: pdf(), docCode: 'IT-NET-004', title: 't', cat: 'NET' as const, scope: '관리자만' as const, tx: '금지' as const }
    const r1 = await api.uploadGuide(admin(), base, (id) => made.push(id))
    expect(r1.ok).toBe(false)
    expect(made).toEqual([40])
    const r2 = await api.uploadGuide(admin(), { ...base, docId: made[0] }, (id) => made.push(id))
    expect(r2.ok).toBe(true)
    expect(made).toEqual([40]) // 두 번째에는 문서를 다시 만들지 않는다
    expect(urls()).toEqual(['POST /api/v1/documents', 'POST /api/v1/documents/40/versions', 'POST /api/v1/documents/40/versions'])
  })

  it('적재 실패 버전의 다시 시도(DC-10): 파일 없이는 같은 파일, 파일을 주면 교체해서 multipart 로 보낸다', async () => {
    const api = await load()
    fetchMock.mockResolvedValueOnce(json(202, ver(41))).mockResolvedValueOnce(json(202, ver(41)))
    await api.retryGuideIngest(admin(), 40, 41)
    await api.retryGuideIngest(admin(), 40, 41, pdf())
    expect(urls()).toEqual(['POST /api/v1/documents/40/versions/41/retry', 'POST /api/v1/documents/40/versions/41/retry'])
    expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBeUndefined()
    const form = (fetchMock.mock.calls[1][1] as RequestInit).body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect((form.get('file') as File).name).toBe('IT-NET-004.pdf')
  })

  it('목록은 비활성 문서까지 받고, 활성화·비활성화는 DC-04 로 isActive 만 보낸다', async () => {
    const api = await load()
    fetchMock
      .mockResolvedValueOnce(json(200, { items: [doc(3, 'IT-NET-001'), { ...doc(4, 'IT-NET-002'), isActive: false }], page: 1, size: 100, totalPages: 1, totalElements: 2 }))
      .mockResolvedValueOnce(json(200, { id: 4, isActive: true }))
      .mockResolvedValueOnce(json(200, { id: 4, isActive: false }))
    const l = await api.listGuides(admin())
    expect(l.ok && l.data.map((g) => [g.docCode, g.isActive])).toEqual([['IT-NET-001', true], ['IT-NET-002', false]])
    expect(urls()[0]).toContain('includeInactive=true')
    expect(await api.setGuideActive(admin(), 4, true)).toMatchObject({ ok: true, data: { isActive: true } })
    expect(await api.setGuideActive(admin(), 4, false)).toMatchObject({ ok: true, data: { isActive: false } })
    expect(urls().slice(1)).toEqual(['PATCH /api/v1/documents/4', 'PATCH /api/v1/documents/4'])
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ isActive: true })
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toEqual({ isActive: false })
  })

  it('모의 모드 재시도·비활성 API 도 같은 모양이다', async () => {
    resetGuideMock()
    expect(await setGuideActive(admin(), 99, true)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_NOT_FOUND' } })
    expect(await retryGuideIngest(admin(), 1, 13)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_RETRYABLE' } })
    const up = await uploadGuide(admin(), { file: pdf(), docCode: 'IT-NET-009', title: 't', cat: 'NET', scope: '관리자만', tx: '금지' })
    expect(up.ok && up.data.versions?.[0].version).toBe('v1.0')
  })
})
