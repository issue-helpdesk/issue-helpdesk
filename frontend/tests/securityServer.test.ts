import { beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../src/core/apiClient'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { countSecurityAlerts, getSecurityAlert, listSecurityAlerts, startSecurityReview, viewSecurityRaw } from '../src/api/security'

vi.mock('../src/core/config', async (importOriginal) => ({ ...await importOriginal<object>(), USE_MOCK_INQUIRY: false }))
vi.mock('../src/core/apiClient', () => ({ request: vi.fn() }))
const http = vi.mocked(request)
const admin = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'ADMIN')!
const employee = MOCK_ACCOUNTS.find((u) => u.serviceRole === 'EMPLOYEE')!
const alert = { id: 12, alertType: 'S02', severity: 'MEDIUM', status: 'NEW',
  subject: { id: 1, employeeNo: 'EMP-1001', name: '테스트' }, subjectDepartmentName: '개발팀',
  summary: '승인 우회 요청 의심 · 누적 2회', rule: '권한·승인 우회 요청', occurrenceCount: 2,
  firstDetectedAt: '2026-11-06T12:00:00+09:00', lastDetectedAt: '2026-11-06T12:01:00+09:00',
  hasOriginal: true, history: [] }
const counts = { new: 1, inReview: 0, closed: 0, openHigh: 0, total: 1 }
beforeEach(() => { http.mockReset() })

describe('실제 보안 알림 API 연결', () => {
  it('영문 서버 계약을 화면에 맞추고 필터·페이지를 전송한다', async () => {
    http.mockImplementation(async (path) => ({ ok: true, data: path === '/security-alerts/counts' ? counts : { items: [alert], page: 2, totalPages: 3, totalCount: 201 } }))
    const r = await listSecurityAlerts(admin, { status: '신규', type: '권한·승인 우회 요청', page: 2 })
    expect(http).toHaveBeenCalledWith(expect.stringContaining('status=NEW'))
    expect(http).toHaveBeenCalledWith(expect.stringContaining('alertType=S02'))
    expect(r.ok && r.data.items[0]).toMatchObject({ id: 'SEC-12', status: '신규', severity: '중간', hitCount: 2 })
    expect(r.ok && r.data.counts.신규).toBe(1)
    expect(r.ok && r.data.totalPages).toBe(3)
    expect(http.mock.calls.some(([p]) => p.includes('/original'))).toBe(false)
  })
  it('S01~S06 유형 이름과 심각도를 화면 용어로 바꾼다', async () => {
    const names = ['보안 사고 의심', '권한·승인 우회 요청', '보안 통제 해제·기록 은폐 요청', '제한 정보 추출 요청', '자료 반출 우회 요청', 'AI 통제 우회 요청']
    http.mockImplementation(async (path) => ({ ok: true, data: path === '/security-alerts/counts' ? counts : { items: names.map((_, i) => ({ ...alert, id: i + 1, alertType: `S0${i + 1}`, severity: i === 0 ? 'HIGH' : 'MEDIUM' })), page: 1, totalPages: 1, totalCount: 6 } }))
    const r = await listSecurityAlerts(admin)
    expect(r.ok && r.data.items.map((a) => a.type)).toEqual(names)
    expect(r.ok && r.data.items.map((a) => a.severity)).toEqual(['높음', '중간', '중간', '중간', '중간', '중간'])
  })
  it('서버 오류를 시연 데이터로 숨기지 않는다', async () => {
    http.mockResolvedValue({ ok: false, error: { code: 'NETWORK_ERROR', message: '연결 실패' } })
    const r = await listSecurityAlerts(admin)
    expect(r.ok).toBe(false)
    expect(await countSecurityAlerts(admin)).toBeNull()
  })
  it('비관리자는 서버 호출도 하지 않는다', async () => {
    expect((await listSecurityAlerts(employee)).ok).toBe(false)
    expect((await getSecurityAlert(employee, 'SEC-12')).ok).toBe(false)
    expect(await countSecurityAlerts(employee)).toBeNull()
    expect(http).not.toHaveBeenCalled()
  })
  it('확인 시작은 review 경로를 쓰고 결과를 변환한다', async () => {
    http.mockResolvedValue({ ok: true, data: { ...alert, status: 'IN_REVIEW' } })
    const r = await startSecurityReview(admin, 'SEC-12')
    expect(http).toHaveBeenCalledWith('/security-alerts/12/review', { method: 'POST', body: undefined })
    expect(r.ok && r.data.status).toBe('확인 중')
  })
  it('사유가 없으면 열람하지 않으며 명시 요청 시 저장된 글만 받는다', async () => {
    expect((await viewSecurityRaw(admin, 'SEC-12', ' ')).ok).toBe(false)
    expect(http).not.toHaveBeenCalled()
    http.mockImplementation(async (path) => ({ ok: true, data: path.endsWith('/original') ? { messages: [{ content: '비밀번호: ●●●●●●' }] } : alert }))
    const r = await viewSecurityRaw(admin, 'SEC-12', '확인')
    expect(http).toHaveBeenCalledWith('/security-alerts/12/original', { method: 'POST', body: JSON.stringify({ reason: '확인' }) })
    expect(r.ok && r.data.raw).toContain('●●●')
  })
})
