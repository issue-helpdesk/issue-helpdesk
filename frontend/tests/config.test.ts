/**
 * 가짜 응답(mock) 설정 읽기: 영역별 변수가 없으면 VITE_USE_MOCK 을 따르고, 'false' 인 영역만 실제 서버를 쓴다.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

const AREAS = ['VITE_USE_MOCK_AUTH', 'VITE_USE_MOCK_INQUIRY', 'VITE_USE_MOCK_TICKET', 'VITE_USE_MOCK_FAQ'] as const

/** 환경 변수를 정하고 config 를 새로 읽는다. 적지 않은 변수는 없는 것이고, 빈 문자열은 Docker 빌드 인자가 비어 있는 경우이다 */
async function load(env: Record<string, string>) {
  vi.resetModules()
  for (const k of ['VITE_USE_MOCK', ...AREAS]) vi.stubEnv(k, env[k])
  return import('../src/core/config')
}

afterEach(() => vi.unstubAllEnvs())

describe('mock 설정', () => {
  it('아무것도 없으면 전부 모의이다', async () => {
    const c = await load({})
    expect([c.USE_MOCK, c.USE_MOCK_AUTH, c.USE_MOCK_INQUIRY, c.USE_MOCK_TICKET, c.USE_MOCK_FAQ]).toEqual([true, true, true, true, true])
  })

  it('영역 변수가 없으면 VITE_USE_MOCK 을 따른다', async () => {
    const c = await load({ VITE_USE_MOCK: 'false' })
    expect([c.USE_MOCK_AUTH, c.USE_MOCK_INQUIRY, c.USE_MOCK_TICKET, c.USE_MOCK_FAQ]).toEqual([false, false, false, false])
  })

  it('영역 변수가 있으면 그 영역만 따로 정한다', async () => {
    const c = await load({ VITE_USE_MOCK: 'true', VITE_USE_MOCK_AUTH: 'false', VITE_USE_MOCK_TICKET: 'false' })
    expect([c.USE_MOCK_AUTH, c.USE_MOCK_INQUIRY, c.USE_MOCK_TICKET, c.USE_MOCK_FAQ]).toEqual([false, true, false, true])
    const d = await load({ VITE_USE_MOCK: 'false', VITE_USE_MOCK_INQUIRY: 'true' })
    expect([d.USE_MOCK_AUTH, d.USE_MOCK_INQUIRY]).toEqual([false, true])
  })

  it('빈 값은 없는 것으로 보고 VITE_USE_MOCK 을 따른다 (Docker 빌드 인자)', async () => {
    const c = await load({ VITE_USE_MOCK: 'true', VITE_USE_MOCK_AUTH: 'false', VITE_USE_MOCK_INQUIRY: '', VITE_USE_MOCK_TICKET: '  ' })
    expect([c.USE_MOCK_AUTH, c.USE_MOCK_INQUIRY, c.USE_MOCK_TICKET]).toEqual([false, true, true])
  })

  it('서버에 API 가 없는 기능은 항상 모의이다', async () => {
    const c = await load({ VITE_USE_MOCK: 'false' })
    expect(c.MOCK_ONLY).toBe(true)
  })
})
