/**
 * 가이드 본문 API(DC-12·13, R-48) 연결: 서버가 주는 본문·그림을 그대로 쓰고, 오류는 "준비 중" 안내로 가리지 않고 사전 문구로 보인다.
 * 표 칸 안의 <br> 은 줄바꿈으로 보이고, 현행 전환이 막히는 두 오류의 문구가 사전에 있다.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { displayMessage } from '../src/api/errorText'
import { Markdown } from '../src/ui/Markdown'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (code: string) => ({ error: { code, message: '서버 문구', details: null, traceId: 't' } })
const DOC = { id: 12, docCode: 'IT-SW-003', title: '업무용 SW 실행·오류 대응 가이드' }
const user = (serviceRole: string) => ({ id: 1, employeeNo: 'E1', name: '테스트', serviceRole }) as never

let fetchMock: ReturnType<typeof vi.fn>
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

describe('오류 문구', () => {
  it('현행 전환이 막히는 두 경우와 본문을 읽지 못한 경우의 문구가 사전에 있다 (해요체)', () => {
    expect(displayMessage('DOCUMENT_VERSION_HAS_REJECTED_CLUSTER', '서버 문구')).toBe('거절한 제안이 포함된 버전은 현행으로 전환할 수 없어요. 거절한 항목을 뺀 새 버전을 올려 주세요.')
    expect(displayMessage('DOCUMENT_VERSION_BASE_CHANGED', '서버 문구')).toBe('제안을 만든 뒤 기준 가이드가 바뀌어서 현행으로 전환할 수 없어요. 최신 내용과 비교한 뒤 다시 등록해 주세요.')
    expect(displayMessage('DOCUMENT_CONTENT_UNAVAILABLE', '서버 문구')).toMatch(/^가이드 본문을 읽을 수 없어요\. 문제가 계속되면 IT 헬프데스크/)
  })
})

describe('가이드 본문 조회 (서버 모드)', () => {
  it('현행 본문은 DC-12, 관리자의 버전 본문은 DC-13 경로로 읽고, 본문·버전·그림을 그대로 쓴다', async () => {
    const g = await load()
    fetchMock.mockResolvedValue(json(200, { documentId: 12, versionId: 31, version: 'v2.0', content: '# 제목\n\n본문', images: [{ key: 'SW/a.png', caption: '그림 1' }] }))
    const cur = await g.getGuideContent(user('EMPLOYEE'), DOC)
    expect(cur).toMatchObject({ ok: true, data: { version: 'v2.0', text: '# 제목\n\n본문', images: [{ key: 'SW/a.png', caption: '그림 1' }] } })
    await g.getGuideContent(user('ADMIN'), DOC, 31, 'v2.0')
    await g.getGuideContent(user('EMPLOYEE'), DOC, 31, 'v2.0') // 관리자가 아니면 버전을 지정해도 현행 경로다
    expect(fetchMock.mock.calls.map((c) => String(c[0]).replace(/^.*\/api\/v1/, ''))).toEqual(['/documents/12/content', '/documents/12/versions/31/content', '/documents/12/content'])
  })

  it('서버 오류는 "준비 중"으로 바꾸지 않고 사전 문구로 보인다', async () => {
    const g = await load()
    fetchMock.mockResolvedValue(json(404, err('DOCUMENT_VERSION_NOT_FOUND')))
    expect(await g.getGuideContent(user('ADMIN'), DOC)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_FOUND', message: '가이드 버전을 찾을 수 없어요. 버전 목록을 다시 불러와 주세요.' } })
    fetchMock.mockResolvedValue(json(404, err('DOCUMENT_NOT_FOUND')))
    expect(await g.getGuideContent(user('EMPLOYEE'), DOC)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_NOT_FOUND' } })
  })

  it('파일이 없거나 읽지 못하면(409) 관리자에게는 파일 확인 안내, 그 밖의 사용자에게는 문의 안내를 보인다', async () => {
    const g = await load()
    fetchMock.mockImplementation(async () => json(409, err('DOCUMENT_CONTENT_UNAVAILABLE')))
    const admin = await g.getGuideContent(user('ADMIN'), DOC)
    expect(admin).toMatchObject({ ok: false, error: { code: 'DOCUMENT_CONTENT_UNAVAILABLE', message: '서버에 가이드 파일이 없거나 읽지 못했어요. 파일을 확인해 주세요.' } })
    const emp = await g.getGuideContent(user('EMPLOYEE'), DOC)
    expect(emp).toMatchObject({ ok: false, error: { code: 'DOCUMENT_CONTENT_UNAVAILABLE' } })
    expect(!emp.ok && emp.error.message).toMatch(/IT 헬프데스크/)
  })
})

describe('Markdown 줄바꿈', () => {
  it('표 칸 안의 <br> 은 글자가 아니라 줄바꿈으로 보인다', () => {
    const { container } = render(<Markdown text={'| 구분 | 방법 |\n| --- | --- |\n| 설치 | 1. 내려받기<br>2. 실행<br/>3. 로그인 |'} />)
    const cell = container.querySelector('td:last-child')!
    expect(cell.querySelectorAll('br')).toHaveLength(2)
    expect(cell.textContent).toBe('1. 내려받기2. 실행3. 로그인')
    expect(screen.queryByText(/<br/)).toBeNull()
  })

  it('표 밖의 글과 굵은 글씨 안의 <br> 도 줄바꿈이 된다', () => {
    const { container } = render(<Markdown text={'**첫째<br>둘째** 그리고<br>셋째'} />)
    expect(container.querySelectorAll('br')).toHaveLength(2)
    expect(container.textContent).not.toMatch(/<br/)
  })
})
