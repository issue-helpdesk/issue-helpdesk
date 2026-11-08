/**
 * AI 가이드 제안(해결 사례 묶음) 서버 연결: GC-01 목록, GC-02 상세, GC-05 초안 저장, GC-03 거절, GC-04 직접 반영 표시.
 * 서버 값이 화면 말(종류·상태)로 옮겨지는 규칙과, 오류 문구, 동시 수정 충돌 때의 동작을 본다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { displayMessage } from '../src/api/errorText'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const err = (code: string) => ({ error: { code, message: '서버 문구', details: null, traceId: 't' } })
const ver = (o: object = {}) => ({ id: 31, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE', ...o })
const sum = (o: object = {}) => ({
  id: 12,
  category: { code: 'NET', name: 'VPN·네트워크' },
  judgment: 'ADD_ITEM',
  status: 'REVIEWING',
  title: 'VPN 연결 시 인터넷 끊김',
  ticketCount: 3,
  targetDocument: { id: 3, docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드' },
  registeredVersion: null,
  ...o,
})
const detail = (o: object = {}) => ({
  ...sum(),
  draftMd: '### 3.4 VPN을 연결하면 인터넷이 끊김',
  draftRevision: 2,
  reviewInfo: { reason: '공유기 설정은 다루지 않음', warnings: ['원인은 추정이에요'] },
  baseVersion: ver(),
  currentVersion: ver(),
  baseChanged: false,
  rejectReason: null,
  reviewedBy: null,
  reviewedAt: null,
  tickets: [{ ticketId: 101, receiptNo: 'RCPT-0101', summary: '재택 VPN 후 인터넷 끊김', resolutionNote: '패스스루를 켬' }],
  ...o,
})

let fetchMock: ReturnType<typeof vi.fn>
async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK_GUIDE', 'false')
  return import('../src/api/caseClusters')
}
const calls = () => fetchMock.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(c[0]).replace(/^.*\/api\/v1/, '')}`)
beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('오류 문구', () => {
  it('묶음 오류 코드의 문구가 사전에 있다', () => {
    for (const code of ['GUIDE_CLUSTER_NOT_FOUND', 'GUIDE_CLUSTER_NOT_REVIEWING', 'GUIDE_CLUSTER_REGISTERED', 'GUIDE_CLUSTER_DRAFT_LOCKED', 'GUIDE_CLUSTER_NO_DRAFT', 'GUIDE_CLUSTER_DRAFT_CONFLICT']) {
      expect(displayMessage(code, '서버 문구')).not.toBe('서버 문구')
    }
  })
})

describe('묶음 목록 (GC-01)', () => {
  it('서버의 판단·상태를 화면의 종류·상태로 옮긴다', async () => {
    const c = await load()
    fetchMock.mockResolvedValue(
      json(200, {
        items: [
          sum({ id: 1, judgment: 'ADD_ITEM' }),
          sum({ id: 2, judgment: 'NEW_GUIDE', targetDocument: null, title: '새 가이드' }),
          sum({ id: 3, judgment: 'MANUAL_CANDIDATE' }),
          sum({ id: 4, judgment: 'SEC_MANUAL' }),
          sum({ id: 5, status: 'REJECTED' }),
          sum({ id: 6, status: 'APPLIED' }),
          sum({ id: 7, registeredVersion: ver({ id: 40, version: 'v2.1', isCurrent: false, ingestStatus: 'PENDING' }) }),
          sum({ id: 8, registeredVersion: ver({ id: 41, version: 'v2.1', isCurrent: false, ingestStatus: 'FAILED' }) }),
          sum({ id: 9, registeredVersion: ver({ id: 42, version: 'v2.1', isCurrent: false, ingestStatus: 'DONE' }) }),
        ],
        page: 1,
        size: 100,
        totalCount: 9,
        totalPages: 1,
      }),
    )
    const r = await c.loadCases()
    expect(r.ok).toBe(true)
    expect(calls()).toEqual(['GET /guide-clusters?size=100&page=1'])
    const by = Object.fromEntries(c.getServerCases().map((x) => [x.id, x]))
    expect(['1', '2', '3', '4'].map((i) => by[i].kind)).toEqual(['amend', 'new', 'manual', 'sec'])
    expect(['1', '5', '6', '7', '8', '9'].map((i) => by[i].state)).toEqual(['review', 'dropped', 'applied', 'preparing', 'failed', 'ready'])
    expect(by['1']).toMatchObject({ cat: 'NET', topic: 'VPN 연결 시 인터넷 끊김', ticketCount: 3, target: { docCode: 'IT-NET-001' } })
    expect(by['9'].registered).toMatchObject({ docId: 3, versionId: 42, version: 'v2.1' })
    expect(c.getServerLoad()).toMatchObject({ loaded: true, error: '' })
  })

  it('목록을 못 읽으면 서버 문구와 함께 오류 상태가 된다', async () => {
    const c = await load()
    fetchMock.mockResolvedValue(json(403, err('FORBIDDEN')))
    const r = await c.loadCases()
    expect(r.ok).toBe(false)
    expect(c.getServerLoad().loaded).toBe(false)
    expect(c.getServerLoad().error).not.toBe('')
  })
})

describe('묶음 상세 (GC-02)와 초안 저장 (GC-05)', () => {
  it('상세에서 초안·AI 판단·근거 티켓을 읽어 화면 값으로 옮긴다', async () => {
    const c = await load()
    fetchMock.mockResolvedValue(json(200, detail()))
    const r = await c.loadCaseDetail('12')
    expect(r.ok && r.data).toMatchObject({
      after: '### 3.4 VPN을 연결하면 인터넷이 끊김',
      reason: '공유기 설정은 다루지 않음',
      warnings: ['원인은 추정이에요'],
      tickets: [{ no: 'RCPT-0101', summary: '재택 VPN 후 인터넷 끊김', result: '패스스루를 켬' }],
      target: { baseVersion: 'v2.0', latestVersion: 'v2.0' },
      server: { draftRevision: 2, hasDraft: true, detail: true, baseChanged: false },
    })
  })

  it('매뉴얼 후보는 초안이 없고, 기준 가이드가 바뀌면 그 사실을 알린다', async () => {
    const c = await load()
    fetchMock.mockResolvedValue(json(200, detail({ judgment: 'MANUAL_CANDIDATE', draftMd: null, baseChanged: true, currentVersion: ver({ id: 50, version: 'v3.0' }) })))
    const r = await c.loadCaseDetail('12')
    expect(r.ok && r.data.server).toMatchObject({ hasDraft: false, baseChanged: true })
    expect(r.ok && r.data.target?.latestVersion).toBe('v3.0')
  })

  it('저장은 초안과 draftRevision 을 함께 보내고, 올라간 번호를 반영한다', async () => {
    const c = await load()
    fetchMock.mockResolvedValue(json(200, detail({ draftMd: '고친 초안', draftRevision: 3 })))
    const r = await c.saveCaseDraft('12', '고친 초안', 2)
    expect(calls()).toEqual(['PATCH /guide-clusters/12'])
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ draftMd: '고친 초안', draftRevision: 2 })
    expect(r.ok && r.data.server?.draftRevision).toBe(3)
  })

  it('다른 관리자가 먼저 고쳤으면(409) 안내 문구를 주고 최신 초안을 다시 읽는다', async () => {
    const c = await load()
    fetchMock.mockImplementation(async (_u: string, init?: RequestInit) => (init?.method === 'PATCH' ? json(409, err('GUIDE_CLUSTER_DRAFT_CONFLICT')) : json(200, detail({ draftMd: '남이 고친 초안', draftRevision: 5 }))))
    const r = await c.saveCaseDraft('12', '내가 고친 초안', 2)
    expect(r.ok).toBe(false)
    expect(!r.ok && r.error.message).toMatch(/다른 관리자가 먼저/)
    expect(calls()).toEqual(['PATCH /guide-clusters/12', 'GET /guide-clusters/12'])
    expect(c.getServerCases().find((x) => x.id === '12')).toMatchObject({ after: '남이 고친 초안', server: { draftRevision: 5 } })
  })
})

describe('거절 (GC-03)과 직접 반영 표시 (GC-04)', () => {
  it('거절은 사유를 보내고, 사유가 비면 보내지 않는다', async () => {
    const c = await load()
    expect((await c.rejectCase('12', '   ')).ok).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
    fetchMock.mockResolvedValue(json(200, detail({ status: 'REJECTED', rejectReason: '이미 매뉴얼에 있는 절차' })))
    const r = await c.rejectCase('12', ' 이미 매뉴얼에 있는 절차 ')
    expect(calls()).toEqual(['POST /guide-clusters/12/reject'])
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ reason: '이미 매뉴얼에 있는 절차' })
    expect(r.ok && r.data).toMatchObject({ state: 'dropped', dropReason: '이미 매뉴얼에 있는 절차' })
  })

  it('직접 반영 표시는 본문 없이 보내고, 반영 완료로 바뀐다. 등록한 묶음이면 오류 문구를 보인다', async () => {
    const c = await load()
    fetchMock.mockResolvedValueOnce(json(200, detail({ status: 'APPLIED', reviewedBy: { name: '관리자' } })))
    const r = await c.applyCase('12')
    expect(calls()).toEqual(['POST /guide-clusters/12/apply'])
    expect(r.ok && r.data).toMatchObject({ state: 'applied', server: { reviewedBy: '관리자' } })
    fetchMock.mockResolvedValueOnce(json(409, err('GUIDE_CLUSTER_REGISTERED')))
    const again = await c.applyCase('12')
    expect(!again.ok && again.error.message).toMatch(/가이드 목록에서 현행으로 전환/)
  })
})
