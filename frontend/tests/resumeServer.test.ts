/**
 * 서버 모드: 담당자 연결 없이 종료한 문의는 서버가 이어가기를 받지 않으므로 이어가기 창을 띄우지 않는다 (요청 R-28).
 * 미확인 문의는 이어갈 수 있다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllEnvs())

const closed = { status: 'CLOSED_UNRESOLVED', step: 'closed', ticket: null, draftState: 'none', messages: [] } as never

describe('이어가기 창 (서버 모드)', () => {
  it('미연결 종료 문의에는 이어가기 창이 뜨지 않고, 새 문의로 안내한다', async () => {
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'false')
    const { entryKindOf, endedMessage } = await import('../src/views/inquiry/resume')
    expect(entryKindOf(closed)).toBeNull()
    expect(endedMessage(closed)).toContain('새 문의로 시작')
  })

  it('모의 모드에서는 시안대로 이어갈 수 있다', async () => {
    vi.stubEnv('VITE_USE_MOCK_INQUIRY', 'true')
    const { entryKindOf } = await import('../src/views/inquiry/resume')
    expect(entryKindOf(closed)).toBe('un')
  })
})
