/**
 * 가이드 적재 실패 알림: 추적(api/guideWatch) → 어느 화면에서나 알림 창 → 사이드바 점 → 가이드 관리의 분류·가이드 점 → 사유 창·다시 시도.
 * 모의 모드는 파일 이름에 scan 이 들어 있으면 2.8초 뒤 "준비 실패"가 된다.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { STALL_MESSAGE, STALL_MS, breakSentences, getIngestFailures, markFailuresSeen, pollIngest, pollInterval, resetIngestWatch, trackIngest } from '../src/api/guideWatch'
import { resetGuideMock, uploadGuideVersion } from '../src/api/guides'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import type { User } from '../src/api/types'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const admin = (): User => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const scanned = () => new File(['x'], 'sample_scanned.pdf', { type: 'application/pdf' })
const good = () => new File(['x'], 'IT-ACC-003_원본.pdf', { type: 'application/pdf' })

function renderAs(employeeNo: string, path: string) {
  tokenStore.set(`mock.${employeeNo}`)
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** 모의 ACC-003(문서 id 4)에 새 버전을 올리고 추적을 시작한다 */
async function uploadAndTrack(file: File) {
  const up = await uploadGuideVersion(admin(), 4, { file, version: 'v99.0', scope: '사내 일반', tx: '금지' })
  if (!up.ok) throw new Error('업로드')
  trackIngest({ docId: 4, versionId: up.data.id, docCode: 'IT-ACC-003', title: 'MFA 인증 오류 대응 가이드', cat: 'ACC', version: 'v99.0' })
  return up.data.id
}

beforeEach(() => {
  resetGuideMock()
  resetIngestWatch()
})

describe('적재 결과 추적 (api)', () => {
  it('추적 중인 버전이 실패하면 알림 대상(seen=false)이 되고, 확인하면 seen 이 되며, 성공하면 사라진다', async () => {
    const id = await uploadAndTrack(scanned())
    expect(getIngestFailures()).toHaveLength(0)
    await waitFor(async () => {
      await pollIngest(admin())
      expect(getIngestFailures()).toHaveLength(1)
    }, { timeout: 4500 })
    expect(getIngestFailures()[0]).toMatchObject({ docCode: 'IT-ACC-003', version: 'v99.0', seen: false, error: expect.stringMatching(/스캔본/) })
    markFailuresSeen()
    expect(getIngestFailures()[0].seen).toBe(true)
    // 글자 있는 파일로 바꿔 다시 시도하면 성공해서 실패 표시가 사라진다
    const { retryGuideIngest } = await import('../src/api/guides')
    await retryGuideIngest(admin(), 4, id, good())
    trackIngest({ docId: 4, versionId: id, docCode: 'IT-ACC-003', title: 't', cat: 'ACC', version: 'v99.0' })
    expect(getIngestFailures()).toHaveLength(0)
    await waitFor(async () => {
      await pollIngest(admin())
    }, { timeout: 4500 })
    await waitFor(async () => {
      await pollIngest(admin())
      expect(getIngestFailures()).toHaveLength(0)
    }, { timeout: 4500 })
  }, 20_000)
})

describe('실패 사유 줄바꿈', () => {
  it('문장마다 줄을 바꾼다 (한 문장·끝 공백은 그대로)', () => {
    expect(breakSentences('문서에서 글자를 찾지 못했습니다. PDF라면 스캔본일 수 있으니 글자가 있는 원본을 올려 주세요.')).toBe('문서에서 글자를 찾지 못했습니다.\nPDF라면 스캔본일 수 있으니 글자가 있는 원본을 올려 주세요.')
    expect(breakSentences('빈 파일입니다.')).toBe('빈 파일입니다.')
    expect(breakSentences('v1.0 파일이 달라요')).toBe('v1.0 파일이 달라요')
  })
})

describe('조회 간격과 멈춘 적재', () => {
  it('오래 기다릴수록 조회 간격이 길어진다 (3초 → 10초 → 30초)', () => {
    expect([pollInterval(0), pollInterval(29_000), pollInterval(31_000), pollInterval(119_000), pollInterval(121_000)]).toEqual([3000, 3000, 10_000, 10_000, 30_000])
  })

  it('10분이 넘도록 준비 중이면 멈춘 것으로 알리고(실패 표시·알림), 더 조회하지 않는다', async () => {
    const t0 = Date.now()
    const now = vi.spyOn(Date, 'now')
    now.mockReturnValue(t0)
    trackIngest({ docId: 4, versionId: 777, docCode: 'IT-ACC-003', title: 'MFA', cat: 'ACC', version: 'v99.0' })
    now.mockReturnValue(t0 + STALL_MS + 1000)
    await pollIngest(admin())
    expect(getIngestFailures()).toEqual([expect.objectContaining({ versionId: 777, stalled: true, seen: false, error: STALL_MESSAGE })])
    // 이미 멈춘 것으로 본 버전은 다시 조회 대상이 아니다
    const before = getIngestFailures()
    await pollIngest(admin())
    expect(getIngestFailures()).toBe(before)
    now.mockRestore()
  })
})

describe('가이드 적재 실패 알림 (화면)', () => {
  it('다른 화면에 있어도 알림 창이 뜨고, 사이드바·분류·가이드 옆 점이 남으며, 사유 창에서 다시 시도할 수 있다', async () => {
    await uploadAndTrack(scanned())
    renderAs('EMP-1178', '/ops')
    const dlg = await screen.findByRole('alertdialog', { name: '가이드 적재에 실패했어요' }, { timeout: 9000 })
    expect(within(dlg).getByText(/IT-ACC-003 MFA 인증 오류 대응 가이드 · v99\.0/)).toBeInTheDocument()
    expect(within(dlg).getByText(/스캔본일 수 있으니/)).toBeInTheDocument()
    // 안내문과 실패 사유 모두 문장 단위로 줄이 나뉜다
    expect(dlg.querySelector('p br')).not.toBeNull()
    expect(dlg.querySelector('.gia em')!.textContent).toBe('문서에서 글자를 찾지 못했습니다.\nPDF라면 스캔본일 수 있으니 글자가 있는 원본을 올려 주세요.')
    // 사이드바 가이드 관리 옆 점
    const nav = screen.getByRole('navigation', { name: '주 메뉴' })
    expect(within(nav).getByRole('img', { name: '적재 실패 1건' })).toBeInTheDocument()
    // 가이드 관리에서 보기: 그 가이드가 펼쳐지고 분류·가이드 옆에 점이 있다
    await userEvent.click(within(dlg).getByRole('button', { name: '가이드 관리에서 보기' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect((await screen.findAllByRole('img', { name: '적재 실패가 있어요' }, { timeout: 4000 })).length).toBeGreaterThanOrEqual(2)
    // 버전 표에서는 "준비 실패" 배지를 눌러 사유 창을 연다 (표에는 긴 사유 글이 없다)
    const failBtn = await screen.findByRole('button', { name: 'v99.0 준비 실패 사유 보기' }, { timeout: 4000 })
    await userEvent.click(failBtn)
    const reason = await screen.findByRole('dialog', { name: '검색 준비에 실패했어요' })
    expect(within(reason).getByText(/글자를 찾지 못했습니다/)).toBeInTheDocument()
    await userEvent.click(within(reason).getByRole('button', { name: '같은 파일로 다시 시도' }))
    expect(await screen.findByText(/v99\.0 검색 준비를 다시 시작했어요/)).toBeInTheDocument()
  }, 30_000)

  it('알림 창을 닫아도(나중에 볼게요) 점은 해결될 때까지 남고, 같은 알림 창이 다시 뜨지 않는다', async () => {
    await uploadAndTrack(scanned())
    renderAs('EMP-1178', '/ops')
    const dlg = await screen.findByRole('alertdialog', { name: '가이드 적재에 실패했어요' }, { timeout: 9000 })
    await userEvent.click(within(dlg).getByRole('button', { name: '나중에 볼게요' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(within(screen.getByRole('navigation', { name: '주 메뉴' })).getByRole('img', { name: '적재 실패 1건' })).toBeInTheDocument()
  }, 20_000)

  it('담당자에게는 알림 창이 뜨지 않는다', async () => {
    await uploadAndTrack(scanned())
    renderAs('EMP-1004', '/my')
    await screen.findByRole('navigation', { name: '주 메뉴' }, { timeout: 4000 })
    await new Promise((r) => setTimeout(r, 3500))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  }, 15_000)
})
