import { describe, expect, it, vi } from 'vitest'
import { askPreLogin, PRE_LOGIN_QUESTIONS } from '../src/api/consult'
import { PASSWORD_RULE } from '../src/core/password'

describe('공개 로그인 도움말', () => {
  it('모든 질문에 네트워크 호출과 내부 문서 없이 답한다', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    try {
      for (const question of PRE_LOGIN_QUESTIONS) {
        const result = await askPreLogin(question)
        expect(result.ok).toBe(true)
        if (!result.ok) continue
        expect(result.data.paragraphs.length).toBeGreaterThan(0)
        expect(result.data.sources).toEqual([])
        expect(result.data.paragraphs.join(' ')).not.toMatch(/https?:|IT-ACC-|MFA|SSO|승인 조건|본인 확인/)
      }
      await askPreLogin('__proto__')
      expect(fetchSpy).not.toHaveBeenCalled()
    } finally {
      fetchSpy.mockRestore()
    }
  })

  it('현재 서비스의 비밀번호 규칙을 그대로 안내한다', async () => {
    const result = await askPreLogin('새 비밀번호가 규칙에 맞지 않아요')
    expect(result.ok && result.data.paragraphs).toContain(PASSWORD_RULE)
  })
})
