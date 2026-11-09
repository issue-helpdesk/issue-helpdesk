/**
 * 가이드 적재 요약(R-47): 서버 문서 목록의 ingestSummary 로 실패·진행 중 표시를 맞춘다.
 * 서버가 알려 준 실패는 점으로만 보이고(알림 창 없음), 이미 해결됐거나 사라진 문서의 기록은 지워지며,
 * 요약이 없는 목록(모의·구버전 서버)은 예전 추적을 건드리지 않는다.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getIngestFailures, recordVersions, resetIngestWatch, syncIngestSummary, trackIngest } from '../src/api/guideWatch'
import type { Guide, GuideVersion } from '../src/api/guides'
import type { User } from '../src/api/types'

const versionsOf = vi.fn()
vi.mock('../src/api/guides', async (orig) => {
  const m = await orig<typeof import('../src/api/guides')>()
  return { ...m, listGuideVersions: (...a: unknown[]) => versionsOf(...a) }
})

const admin = { id: 3, employeeNo: 'EMP-1178', name: '이건우', serviceRole: 'ADMIN' } as User
const agent = { id: 2, employeeNo: 'EMP-1004', name: '성민경', serviceRole: 'AGENT' } as User
const guide = (id: number, ingest?: Guide['ingest']): Guide => ({ id, docCode: `IT-NET-00${id}`, title: `가이드 ${id}`, cat: 'NET', isActive: true, current: null, versions: null, ingest })
const ver = (id: number, ready: GuideVersion['ready'], error?: string): GuideVersion => ({ id, version: `v${id}`, state: '초안', ready, scope: '전 직원', tx: '금지', error })
const none = { failed: 0, pending: 0, lastError: null }

beforeEach(() => {
  localStorage.clear()
  resetIngestWatch()
  versionsOf.mockReset()
})

describe('적재 요약 반영', () => {
  it('요약에 실패가 있고 이 브라우저가 모르는 버전이면 그 문서의 버전을 읽어 실패로 기록하되, 알림 창은 띄우지 않는다', async () => {
    versionsOf.mockResolvedValue({ ok: true, data: [ver(21, '준비 실패', '문서 변환 오류'), ver(20, '준비 완료')] })
    await syncIngestSummary(admin, [guide(2, { failed: 1, pending: 0, lastError: '문서 변환 오류' }), guide(3, none)])
    expect(versionsOf).toHaveBeenCalledTimes(1) // 문제가 없는 문서는 읽지 않는다
    expect(getIngestFailures()).toMatchObject([{ docId: 2, versionId: 21, error: '문서 변환 오류', seen: true }])
  })

  it('요약이 실패 0건이면 예전에 기록한 실패의 점을 지운다 (이미 해결됐거나 지워진 버전)', async () => {
    recordVersions({ docId: 2, docCode: 'IT-NET-002', title: '가이드 2', cat: 'NET' }, [ver(21, '준비 실패', '오류')])
    expect(getIngestFailures()).toHaveLength(1)
    await syncIngestSummary(admin, [guide(2, none)])
    expect(getIngestFailures()).toHaveLength(0)
    expect(versionsOf).not.toHaveBeenCalled()
  })

  it('목록에 없는 문서의 기록은 지운다', async () => {
    recordVersions({ docId: 9, docCode: 'IT-NET-009', title: '사라진 가이드', cat: 'NET' }, [ver(91, '준비 실패', '오류')])
    await syncIngestSummary(admin, [guide(2, none)])
    expect(getIngestFailures()).toHaveLength(0)
  })

  it('이미 아는 실패는 다시 읽지 않는다', async () => {
    recordVersions({ docId: 2, docCode: 'IT-NET-002', title: '가이드 2', cat: 'NET' }, [ver(21, '준비 실패', '오류')])
    await syncIngestSummary(admin, [guide(2, { failed: 1, pending: 0, lastError: '오류' })])
    expect(versionsOf).not.toHaveBeenCalled()
    expect(getIngestFailures()).toHaveLength(1)
  })

  it('요약이 없는 목록(모의·구버전 서버)이면 예전 추적을 건드리지 않는다', async () => {
    recordVersions({ docId: 2, docCode: 'IT-NET-002', title: '가이드 2', cat: 'NET' }, [ver(21, '준비 실패', '오류')])
    await syncIngestSummary(admin, [guide(2)])
    expect(getIngestFailures()).toHaveLength(1)
    expect(versionsOf).not.toHaveBeenCalled()
  })

  it('방금 시작한 추적(진행 중)은 서버 요약에 아직 안 잡혀도 지우지 않는다', async () => {
    trackIngest({ docId: 2, versionId: 30, docCode: 'IT-NET-002', title: '가이드 2', cat: 'NET', version: 'v30' })
    versionsOf.mockResolvedValue({ ok: true, data: [ver(30, '준비 중')] })
    await syncIngestSummary(admin, [guide(2, none)])
    // 추적이 남아 있어야 한다 (결과는 3초 주기 확인이 알려 준다)
    expect(JSON.parse(localStorage.getItem('itssue-guide-watch') ?? '{}').pending).toHaveLength(1)
  })

  it('관리자가 아니면 아무것도 하지 않는다', async () => {
    await syncIngestSummary(agent, [guide(2, { failed: 1, pending: 0, lastError: '오류' })])
    expect(versionsOf).not.toHaveBeenCalled()
    expect(getIngestFailures()).toHaveLength(0)
  })
})
