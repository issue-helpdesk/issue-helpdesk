/**
 * 출처 미리보기의 가이드 그림(DC-11)과 FAQ 출처 본문(R-30).
 * 서버는 출처에 `images: [{ key, caption }]` 를 주고 그림 파일은 `GET /guide-images/{key}` 로 받는다 (인증 헤더 필요).
 * 본문의 `[그림] 설명` 줄을 설명이 같은 그림과 짝지어 보여 주고, 짝이 없거나 못 받으면 설명 상자를 그대로 둔다.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GuideSource } from '../src/api/chatTypes'
import { tokenStore } from '../src/core/tokenStore'
import { SourcePreview } from '../src/ui/SourcePreview'

const IMG = { key: 'SW/sw001_portal_home.png', caption: '포털 첫 화면' }
const src = (over: Partial<GuideSource> = {}): GuideSource => ({
  docCode: 'IT-SW-001',
  title: '업무용 SW 설치 가이드',
  version: 'v2',
  section: '2.1',
  excerpt: '2.1 포털 접속\n[그림] 포털 첫 화면\n[그림] 짝이 없는 그림\n포털에서 설치 버튼을 누릅니다.',
  images: [IMG],
  ...over,
})

describe('가이드 그림', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const revoke = vi.fn()
  beforeEach(() => {
    tokenStore.set('tok-abc')
    fetchMock = vi.fn(async () => new Response(new Blob(['png'], { type: 'image/png' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:fake-1'), revokeObjectURL: revoke }))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    tokenStore.clear()
  })

  it('설명이 같은 그림은 인증 헤더로 받아 실제 그림으로 보이고, 짝이 없는 줄은 설명 상자로 남는다', async () => {
    render(<SourcePreview source={src()} onClose={() => {}} />)
    const img = await screen.findByRole('img', { name: '포털 첫 화면' })
    expect(img.tagName).toBe('IMG')
    expect(img).toHaveAttribute('src', 'blob:fake-1')
    expect(screen.getByText('포털 첫 화면', { selector: 'figcaption' })).toBeInTheDocument()
    // 파일은 fetch 로 토큰을 실어 받는다 (<img src> 에 주소를 바로 넣을 수 없다)
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/guide-images/SW/sw001_portal_home.png')
    expect(new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers).get('Authorization')).toBe('Bearer tok-abc')
    // 짝이 없는 [그림] 줄은 지금처럼 설명 상자다
    expect(screen.getByRole('img', { name: '그림: 짝이 없는 그림' }).tagName).toBe('DIV')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('받지 못하면(404) 설명 상자를 그대로 두고, 창을 닫으면 만든 주소를 풀어 준다', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
    const first = render(<SourcePreview source={src()} onClose={() => {}} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.getByRole('img', { name: '그림: 포털 첫 화면' }).tagName).toBe('DIV')
    expect(screen.queryByText('포털 첫 화면', { selector: 'figcaption' })).toBeNull()
    first.unmount()
    expect(revoke).not.toHaveBeenCalled() // 만든 주소가 없으니 풀 것도 없다

    const { unmount } = render(<SourcePreview source={src({ docCode: 'IT-SW-002' })} onClose={() => {}} />)
    await screen.findAllByRole('img', { name: '포털 첫 화면' })
    unmount()
    expect(revoke).toHaveBeenCalledWith('blob:fake-1')
  })

  it('images 가 없는 출처(모의·시연)는 요청을 보내지 않고 설명 상자만 보인다', async () => {
    render(<SourcePreview source={src({ images: undefined })} onClose={() => {}} />)
    expect(screen.getByRole('img', { name: '그림: 포털 첫 화면' }).tagName).toBe('DIV')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('본문이 없는 출처 안내', () => {
  it('문서만 직접 지정한 FAQ 출처는 본문이 없는 게 정상이라고 안내하고, 그 밖에는 본문을 못 받았다고 안내한다', () => {
    const first = render(<SourcePreview source={src({ excerpt: '', section: '', images: undefined, documentId: 12 })} onClose={() => {}} />)
    expect(screen.getByText(/문서만 연결한 출처라서 보여 줄 본문이 없어요/)).toBeInTheDocument()
    first.unmount()
    render(<SourcePreview source={src({ excerpt: '', images: undefined })} onClose={() => {}} />)
    expect(screen.getByText(/본문을 아직 받아 오지 못해요/)).toBeInTheDocument()
  })
})

describe('서버 응답을 출처로 바꾸기', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('FAQ 출처는 서버의 본문(excerpt)과 그림 목록을 그대로 읽는다 (직접 지정 출처는 본문 없음)', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_USE_MOCK_FAQ', 'false')
    const detail = {
      id: 1,
      faqCode: 'FAQ-001',
      categoryCode: 'SW',
      question: 'q',
      answer: 'a',
      isActive: true,
      sources: [
        { documentId: 5, docCode: 'IT-SW-001', title: 'SW', version: 'v2', location: '2.1', excerpt: '2.1 포털 접속\n[그림] 포털 첫 화면', images: [IMG] },
        { documentId: 6, docCode: 'IT-SW-002', title: 'SW2', version: 'v1', location: null, excerpt: null, images: [] },
      ],
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(detail), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const api = await import('../src/api/faq')
    const r = await api.getFaqSources(1)
    expect(r.ok && r.data[0]).toMatchObject({ section: '2.1', excerpt: '2.1 포털 접속\n[그림] 포털 첫 화면', images: [IMG], documentId: 5 })
    expect(r.ok && r.data[1]).toMatchObject({ section: '', excerpt: '', documentId: 6 })
    expect(r.ok && r.data[1].images).toBeUndefined()
  })
})
