/**
 * 담당자 연결 없이 종료한 문의(미연결·접수 취소)는 서버·모의 모두 이어가기 창을 띄우지 않는다 (서버 IQ-06이 받지 않는다, 요청 R-28).
 * 미확인 문의는 이어갈 수 있다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllEnvs())

const closed = { status: 'CLOSED_UNRESOLVED', step: 'closed', ticket: null, draftState: 'none', messages: [] } as never
const cancelled = { status: 'CLOSED_UNRESOLVED', step: 'closed', ticket: null, draftState: 'cancel', messages: [] } as never
const unconfirmed = { status: 'IN_PROGRESS', step: 'answered', ticket: null, draftState: 'none', messages: [] } as never

describe('이어가기 창', () => {
  for (const mock of ['false', 'true']) {
    it(`미연결·접수 취소로 닫힌 문의에는 창이 뜨지 않고 새 문의로 안내한다 (모의=${mock})`, async () => {
      vi.stubEnv('VITE_USE_MOCK_INQUIRY', mock)
      const { entryKindOf, endedMessage } = await import('../src/views/inquiry/resume')
      expect(entryKindOf(closed)).toBeNull()
      expect(entryKindOf(cancelled)).toBeNull()
      expect(endedMessage(closed)).toContain('새 문의로 시작')
      expect(endedMessage(cancelled)).toContain('새 문의로 시작')
    })
  }

  it('미확인 문의는 이어갈 수 있다', async () => {
    const { entryKindOf } = await import('../src/views/inquiry/resume')
    expect(entryKindOf(unconfirmed)).toBe('ua')
  })
})
