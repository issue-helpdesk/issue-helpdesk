/**
 * 오류 코드별 화면 문구 사전: 서버가 준 message 대신 코드로 정한 문구가 쓰이고, 사전에 없는 코드는 서버 문구(용어만 맞춤)를 쓴다.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanServerText, displayMessage, errorText } from '../src/api/errorText'
import { request, setPasswordRequiredHandler } from '../src/core/apiClient'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (code: string, message: string, details?: unknown) => json(409, { error: { code, message, details } })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('코드별 문구 사전', () => {
  it('사전에 있는 코드는 서버 문구 대신 사전 문구를 쓴다 (해요체)', () => {
    expect(displayMessage('INQUIRY_CLOSED', '종료된 문의입니다. 문의를 다시 열어 대화를 이어가 주세요.')).toBe('이미 종료된 문의예요. 새 문의로 시작해 주세요.')
    expect(displayMessage('TICKET_NOT_FOUND', '접수 건을 찾을 수 없습니다.')).toBe('티켓을 찾을 수 없어요. 목록을 다시 불러와 주세요.')
  })

  it('사전에 없는 코드는 서버 문구를 쓰되 Jira 는 ITSM 으로 바꾼다', () => {
    expect(displayMessage('SOME_NEW_CODE', '새 코드입니다. Jira 확인.')).toBe('새 코드입니다. ITSM 시스템 확인.')
    expect(cleanServerText('Jiraffe')).toBe('Jiraffe')
    expect(cleanServerText('JIRA 시스템 확인')).toBe('ITSM 시스템 확인') // 단어 일부는 건드리지 않는다
    expect(errorText('SOME_NEW_CODE')).toBeNull()
  })

  it('Jira 가 들어 있던 서버 문구 세 개는 ITSM 으로 보인다', () => {
    for (const c of ['TICKET_NOT_SYNCED', 'INTEGRATION_ALREADY_SYNCED', 'ASSIGNEE_NOT_ASSIGNABLE']) {
      const t = errorText(c)!
      expect(t).toContain('ITSM')
      expect(t).not.toContain('Jira')
    }
  })

  it('연락 창구는 서버 문구와 같은 "IT 헬프데스크"로 통일한다', () => {
    expect(errorText('AUTH_ACCOUNT_INACTIVE')).toContain('IT 헬프데스크')
    expect(errorText('TICKET_SAVE_FAILED')).toContain('IT 헬프데스크')
    expect(errorText('AUTH_ACCOUNT_INACTIVE')).not.toContain('서비스데스크')
  })

  it('서버가 details 로 준 값은 문구에 끼워 쓰고, 없으면 값 없는 문구를 쓴다', () => {
    expect(errorText('DOCUMENT_FILE_TOO_LARGE', [{ field: 'file', reason: 'OUT_OF_RANGE', message: '최대 크기', value: '20MB' }])).toContain('(20MB)')
    expect(errorText('DOCUMENT_FILE_TOO_LARGE')).not.toContain('MB')
    const dup = [{ field: 'file', reason: 'DUPLICATE', message: '', value: { docCode: 'IT-NET-001', version: 'v2' } as never }]
    expect(errorText('DOCUMENT_FILE_DUPLICATE', dup)).toContain('IT-NET-001 · v2')
    expect(errorText('DOCUMENT_FILE_DUPLICATE')).toBe('같은 파일이 이미 등록되어 있어요.')
    expect(errorText('AUTH_PASSWORD_POLICY_VIOLATION', [{ field: 'newPassword', reason: 'TOO_SHORT', message: '8자 이상 입력해 주세요.' }])).toContain('8자 이상 입력해 주세요.')
  })

  it('서버가 보내지 않는 코드(REQUEST_IN_PROGRESS·IDEMPOTENCY_KEY_REUSED)와 서버 간 웹훅 오류는 문구를 만들지 않는다', () => {
    expect(errorText('REQUEST_IN_PROGRESS')).toBeNull()
    expect(errorText('IDEMPOTENCY_KEY_REUSED')).toBeNull()
    expect(errorText('WEBHOOK_SIGNATURE_INVALID')).toBeNull()
  })
})

describe('요청 클라이언트의 오류 문구', () => {
  it('서버 오류의 문구는 사전으로 바뀌고 details 는 그대로 전달된다', async () => {
    const details = [{ field: 'version', reason: 'DUPLICATE', message: '이미 있음' }]
    vi.stubGlobal('fetch', vi.fn(async () => err('DOCUMENT_VERSION_DUPLICATE', '이미 등록된 버전입니다.', details)))
    const r = await request('/x')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error.code).toBe('DOCUMENT_VERSION_DUPLICATE')
      expect(r.error.message).toBe('이미 등록된 버전이에요. 버전을 확인해 주세요.')
      expect(r.error.details).toEqual(details)
    }
  })

  it('사전에 없는 코드의 서버 문구에서 Jira 를 ITSM 으로 바꾼다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => err('UNLISTED', 'Jira 작업 실패')))
    const r = await request('/x')
    expect(!r.ok && r.error.message).toBe('ITSM 시스템 작업 실패')
  })

  it('연결이 끊기면 조회는 "불러오지 못했어요", 변경 요청은 "처리 결과를 확인하지 못했어요"라고 한다 (처리 실패로 단정하지 않는다)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const read = await request('/x')
    const write = await request('/x', { method: 'POST', body: '{}' })
    expect(!read.ok && read.error.message).toContain('불러오지 못했어요')
    expect(!write.ok && write.error.message).toContain('처리 결과를 확인하지 못했어요')
    expect(!write.ok && write.error.message).not.toContain('실패')
    expect(!write.ok && write.error.code).toBe('NETWORK_ERROR')
  })
})

describe('비밀번호 변경 요구', () => {
  it('서버가 AUTH_PASSWORD_CHANGE_REQUIRED 를 주면 변경 창을 띄우는 처리기를 부른다', async () => {
    const on = vi.fn()
    setPasswordRequiredHandler(on)
    vi.stubGlobal('fetch', vi.fn(async () => json(403, { error: { code: 'AUTH_PASSWORD_CHANGE_REQUIRED', message: 'x' } })))
    const r = await request('/tickets')
    expect(on).toHaveBeenCalledTimes(1)
    expect(!r.ok && r.error.message).toBe('비밀번호를 변경한 뒤 이용할 수 있어요.')
    setPasswordRequiredHandler(null)
  })
})
