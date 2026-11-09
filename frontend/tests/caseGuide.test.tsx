/**
 * 가이드 관리 → 해결 사례 탭 (모의): 제안 목록(검토 대상·가이드화 승인·반영 안함), 검토 패널, 승인할 때 뜨는 등록 설정 창,
 * 가이드 목록에 등록되는 초안 버전과 검색 준비·현행 전환 연결, 반영 안함, 재시도, 기준 가이드가 바뀐 제안의 차단.
 * 서버 없이 시연 데이터와 모의 상태 전환만 쓴다.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { listGuideVersions, listGuides, resetGuideMock, setGuideCurrent } from '../src/api/guides'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { approveCase, baseChanged, dropCase, ensureCaseVersions, getCases, rebaseCase, resetCaseGuides, retryCase } from '../src/api/mock/caseGuides'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }
const get = (id: string) => getCases().find((c) => c.id === id)!
const admin = () => MOCK_ACCOUNTS.find((u) => u.employeeNo === 'EMP-1178')!
const INGEST_MS = 2900

function reset() {
  resetGuideMock()
  resetCaseGuides()
}

describe('해결 사례 모의 상태 전환', () => {
  beforeEach(() => {
    reset()
    vi.useFakeTimers()
    ensureCaseVersions()
  })
  afterEach(() => vi.useRealTimers())

  it('시연 이력의 제안은 가이드 목록의 버전 상태에서 상태를 읽는다', () => {
    expect(get('c4').state).toBe('preparing')
    expect(get('c5').state).toBe('failed')
    expect(get('c5').failReason).toBeTruthy()
    expect(get('c6').state).toBe('ready')
    expect(get('c7').state).toBe('live')
    expect(get('c8').state).toBe('dropped')
    // 검색 준비 중이던 건은 시간이 지나면 준비 완료가 된다 (자동으로 현행이 되지는 않는다)
    act(() => {
      vi.advanceTimersByTime(INGEST_MS)
    })
    expect(get('c4').state).toBe('ready')
  })

  it('승인하면 가이드 목록에 현행이 아닌 새 버전으로 등록되고, 현행 전환은 가이드 목록에서 한다', async () => {
    const c = get('c1')
    expect(c.state).toBe('review')
    expect(approveCase('c1', { after: c.after, scope: '담당자 이상', tx: '마스킹 후 허용' })).toEqual({ ok: true })
    const x = get('c1')
    expect(x).toMatchObject({ state: 'preparing', scope: '담당자 이상', tx: '마스킹 후 허용' })
    expect(x.registered).toMatchObject({ docCode: 'IT-NET-001', version: 'v4.0' })
    // 중복 승인은 막는다
    expect(approveCase('c1', { after: c.after, scope: '전 직원', tx: '허용' }).ok).toBe(false)
    // 가이드 목록의 문서에 초안 버전으로 보인다
    const vs = await (async () => {
      const p = listGuideVersions(admin(), x.registered!.docId)
      await vi.advanceTimersByTimeAsync(300)
      return p
    })()
    expect(vs.ok && vs.data.find((v) => v.id === x.registered!.versionId)).toMatchObject({ state: '초안', ready: '준비 중', scope: '담당자 이상', tx: '마스킹 후 허용' })
    act(() => {
      vi.advanceTimersByTime(INGEST_MS)
    })
    expect(get('c1').state).toBe('ready') // 자동으로 현행이 되지 않는다
    // 가이드 목록에서 현행으로 바꾸면 제안도 현행이 된다
    const r = setGuideCurrent(admin(), x.registered!.docId, x.registered!.versionId)
    await vi.advanceTimersByTimeAsync(300)
    expect((await r).ok).toBe(true)
    expect(get('c1').state).toBe('live')
  })

  it('신규 가이드를 승인하면 가이드 목록에 새 문서가 생긴다', async () => {
    const before = await (async () => {
      const p = listGuides(admin())
      await vi.advanceTimersByTimeAsync(200)
      return p
    })()
    expect(approveCase('c2', { title: '사내 메신저 알림이 오지 않을 때', cat: 'SYS', after: get('c2').after, scope: '전 직원', tx: '허용' })).toEqual({ ok: true })
    const after = await (async () => {
      const p = listGuides(admin())
      await vi.advanceTimersByTimeAsync(200)
      return p
    })()
    expect(after.ok && before.ok && after.data.length).toBe(before.ok ? before.data.length + 1 : -1)
    expect(get('c2').registered).toMatchObject({ docCode: expect.stringMatching(/^IT-SYS-\d{3}$/), version: 'v1.0' })
  })

  it('검색 준비에 실패한 건은 같은 버전으로 다시 시도하고, 후보로 되돌아가지 않는다', () => {
    expect(get('c5').state).toBe('failed')
    expect(retryCase('c5')).toEqual({ ok: true })
    expect(get('c5').state).toBe('preparing')
    act(() => {
      vi.advanceTimersByTime(INGEST_MS)
    })
    expect(get('c5').state).toBe('ready')
    expect(retryCase('c5').ok).toBe(false)
  })

  it('기준 가이드가 바뀐 제안은 등록이 막히고, 최신 내용에 맞춰 바꾸면 풀린다', () => {
    const c = get('c3')
    expect(baseChanged(c)).toBe(true)
    expect(approveCase('c3', { after: c.after, scope: '전 직원', tx: '허용' }).ok).toBe(false)
    expect(rebaseCase('c3')).toEqual({ ok: true })
    expect(baseChanged(get('c3'))).toBe(false)
    expect(get('c3').target!.baseVersion).toBe('v2')
    expect(approveCase('c3', { after: get('c3').after, scope: '전 직원', tx: '허용' })).toEqual({ ok: true })
  })

  it('반영 안함는 사유가 있어야 하고, 승인한 건에는 쓸 수 없다', () => {
    expect(dropCase('c1', '  ').ok).toBe(false)
    expect(dropCase('c1', '일회성 조치예요')).toEqual({ ok: true })
    expect(get('c1')).toMatchObject({ state: 'dropped', dropReason: '일회성 조치예요' })
    expect(dropCase('c4', '사유').ok).toBe(false) // 이미 승인한 건
  })
})

function renderAdmin() {
  tokenStore.set('mock.EMP-1178')
  return render(
    <MemoryRouter initialEntries={['/guides']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
const cardsOf = () => screen.getAllByRole('region').filter((r) => r.classList.contains('cgc'))
const openTab = async () => {
  await userEvent.click(await screen.findByRole('button', { name: /^AI 가이드 제안/ }, SLOW))
  await screen.findByText(/주 1회/, undefined, SLOW)
}

describe('해결 사례 탭 화면', () => {
  beforeEach(reset)

  it('상세를 아직 읽지 않은 제안도 근거 건수순이며 상세를 읽어도 순서가 바뀌지 않는다', async () => {
    // 서버 목록처럼 상세 배열이 비어 있는 경우를 모의 데이터로 재현한다.
    for (const c of getCases()) if (c.state === 'review') c.tickets = []
    renderAdmin()
    await openTab()
    const counts = () => cardsOf().map((c) => /근거 티켓\s*(\d+)건/.exec(c.textContent ?? '')![1])
    expect(counts()).toEqual(['7', '5', '4'])
    await act(async () => { get('c1').tickets = [{ no: 'RCPT-TEST', summary: '상세 조회', result: '처리 완료' }] })
    // 탭 전환으로 다시 그려도 상세 배열 길이가 정렬 기준이 되지 않는다.
    await userEvent.click(screen.getByRole('button', { name: /^가이드화 승인/ }))
    await userEvent.click(screen.getByRole('button', { name: /^검토 대상/ }))
    expect(counts()).toEqual(['7', '5', '4'])
  })

  it('탭 이름 옆 건수·검토 필요 라벨·세 가지 보기·카드 정렬이 맞고, 개발 용어와 퍼센트가 없다', async () => {
    renderAdmin()
    await openTab()
    // 이 탭에서는 가이드 파일 업로드 단추가 없다 (가이드 목록 탭에는 있다)
    expect(screen.queryByRole('button', { name: /가이드 파일 업로드/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '일간' })).toBeNull()
    expect(screen.queryByText(/%/)).toBeNull()
    const cards = cardsOf()
    expect(cards.map((c) => /근거 티켓\s*(\d+)건/.exec(c.textContent ?? '')![1])).toEqual(['7', '5', '4'])
    expect(within(cards[0]).getByText('검토 필요')).toBeInTheDocument()
    // 검토 필요 라벨은 분홍 단추와 겹치지 않는 색이다
    expect(within(cards[0]).getByText('검토 필요').closest('.badge')).toHaveClass('b-asg')
    expect(within(cards[0]).getByText('기존 가이드 보강')).toBeInTheDocument()
    expect(within(cards[1]).getByText('신규 가이드')).toBeInTheDocument()
    // 구분은 색이 다른 배지다: 기존 가이드 보강=보라, 신규 가이드=하늘
    expect(within(cards[0]).getByText('기존 가이드 보강').closest('.badge')).toHaveClass('b-prog')
    expect(within(cards[1]).getByText('신규 가이드').closest('.badge')).toHaveClass('b-info')
    // 검토 필요인 카드에는 검토하기만 있다 (같은 화면을 여는 근거 티켓 보기는 없다)
    expect(within(cards[0]).getAllByRole('button').map((b) => b.textContent)).toEqual(['검토하기'])
    expect(document.body.textContent).not.toMatch(/CLS|WAITING|guide_status|APPLIED|REVIEWING|검토 중/)
    // 가이드화 승인
    await userEvent.click(screen.getByRole('button', { name: /^가이드화 승인/ }))
    const ok = cardsOf()
    expect(ok.map((c) => /^[^]*?(검색 준비 중|검색 준비 실패|검색 준비 완료|현행)/.exec(c.textContent ?? '')![1]).sort()).toEqual(['검색 준비 실패', '검색 준비 완료', '검색 준비 중', '현행'].sort())
    const live = ok.find((c) => /메일함 용량/.test(c.textContent ?? ''))!
    expect(within(live).getAllByRole('button').map((b) => b.textContent)).toEqual(['등록 버전 보기', '처리 이력 상세 보기'])
    const ready = ok.find((c) => /관리자 권한 오류/.test(c.textContent ?? ''))!
    expect(within(ready).getAllByRole('button').map((b) => b.textContent)).toEqual(['현행으로 전환', '등록 버전 보기', '처리 이력 상세 보기'])
    // 반영 안함
    await userEvent.click(screen.getByRole('button', { name: /^반영 안함/ }))
    const dropped = cardsOf()
    expect(dropped).toHaveLength(1)
    expect(within(dropped[0]).getAllByRole('button').map((b) => b.textContent)).toEqual(['처리 이력 상세 보기'])
  })

  it('승인하고 초안 등록을 누르면 등록 설정 창이 뜨고, 거기서 확인해야 등록된다', async () => {
    renderAdmin()
    await openTab()
    await userEvent.click(within(cardsOf()[0]).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    // 검토 중에는 등록 설정이 패널에 보이지 않는다
    expect(within(panel).queryByText('열람 범위')).toBeNull()
    expect(within(panel).getByText('검토 필요')).toBeInTheDocument()
    await userEvent.type(within(panel).getByLabelText(/AI 수정 제안문/), ' 추가 확인')
    await userEvent.click(within(panel).getByRole('button', { name: '승인하고 초안 등록' }))
    const dlg = await screen.findByRole('dialog', { name: '등록 설정을 확인해 주세요' })
    expect(within(dlg).getByText(/초안으로 등록하고 검색 준비를 시작합니다/)).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('button', { name: '담당자 이상' }))
    await userEvent.click(within(dlg).getByRole('button', { name: '금지' }))
    // 버튼마다 색이 있다 (가이드 목록의 외부 AI 전송 버튼과 같다)
    expect(within(dlg).getByRole('button', { name: '담당자 이상' })).toHaveClass('on', 'prog')
    expect(within(dlg).getByRole('button', { name: '금지' })).toHaveClass('on', 'urg')
    expect(get('c1').state).toBe('review') // 창에서 확인하기 전에는 등록되지 않는다
    await userEvent.click(within(dlg).getByRole('button', { name: '초안으로 등록' }))
    await waitFor(() => expect(get('c1').state).toBe('preparing'), SLOW)
    expect(get('c1')).toMatchObject({ scope: '담당자 이상', tx: '금지' })
    expect(get('c1').after).toMatch(/추가 확인/)
    expect(await within(panel).findByText(/검색 준비 중이에요/, undefined, SLOW)).toBeInTheDocument()
    // 위의 X 로 닫으니 아래쪽 닫기 단추는 없다
    expect(within(panel).getAllByRole('button', { name: '닫기' })).toHaveLength(1)
  })

  it('현행으로 전환을 누르면 바로 바뀌지 않고 가이드 목록에서 그 문서가 펼쳐진다', async () => {
    renderAdmin()
    await openTab()
    await userEvent.click(screen.getByRole('button', { name: /^가이드화 승인/ }))
    const ready = cardsOf().find((c) => /관리자 권한 오류/.test(c.textContent ?? ''))!
    await userEvent.click(within(ready).getByRole('button', { name: '현행으로 전환' }))
    expect(get('c6').state).toBe('ready') // 아직 현행이 아니다
    // 가이드 목록으로 이동해 IT-SW-001 이 펼쳐져 있고, 등록한 버전의 현행 전환 단추가 있다
    expect(await screen.findByRole('button', { name: /^IT-SW-001 업무용 SW 설치 가이드/, expanded: true }, SLOW)).toBeInTheDocument()
    const rows = await screen.findAllByRole('row', undefined, SLOW)
    const row = rows.find((r) => within(r).queryByText('v3.0'))!
    // 넘어온 버전 줄은 강조되고, 그 문서 아래에는 현행 전환 안내 줄이 붙는다
    expect(row).toHaveClass('vfocus')
    expect(screen.getByText(/의 검색 준비가 끝났어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '현행 전환하러 가기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /현행 전환 대기 \d+건만 보기/ })).toBeInTheDocument() // 목록 위 요약
    await userEvent.click(within(row).getByRole('button', { name: '현행 전환' }))
    await waitFor(() => expect(get('c6').state).toBe('live'), SLOW)
  })

  it('검토 중인 제안이 걸린 문서에는 제안 건수가 보이고, 그 문서에 새 버전을 올리려 하면 안내가 뜬다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: /^VPN·네트워크/ }, SLOW))
    expect(await screen.findByRole('button', { name: /^IT-NET-001 VPN 접속 장애 대응 가이드/ }, SLOW)).toBeInTheDocument()
    expect(screen.getByText(/검토할 AI 제안이/)).toHaveTextContent('1건') // 그 가이드 아래 안내 줄
    expect(screen.getByRole('button', { name: '제안 보기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /AI 제안 \d+건 보기/ })).toBeInTheDocument() // 목록 위 요약
    await userEvent.click(screen.getByRole('button', { name: /가이드 파일 업로드/ }))
    const dlg = await screen.findByRole('dialog', { name: '가이드 파일 업로드' }, SLOW)
    expect(within(dlg).queryByText(/검토 중인 AI 가이드 제안/)).toBeNull() // 문서를 고르기 전에는 없다
    for (const [label, option] of [['분류', /네트워크/], ['문서', /IT-NET-001/]] as const) {
      await userEvent.click(within(dlg).getByLabelText(label))
      await userEvent.click(await screen.findByRole('option', { name: option }))
    }
    expect(await within(dlg).findByText(/IT-NET-001에 검토 중인 AI 가이드 제안이 1건 있어요/)).toBeInTheDocument()
  })

  it('검토할 제안이 있는 가이드는 현행을 바꾸지 못하게 막고, 제안을 보러 갈 수 있다', async () => {
    renderAdmin()
    // IT-NET-001 에는 검토 필요인 제안(c1)이 있다
    await userEvent.click(await screen.findByRole('button', { name: /^VPN·네트워크/ }, SLOW))
    await userEvent.click(await screen.findByRole('button', { name: /^IT-NET-001 VPN 접속 장애 대응 가이드/ }, SLOW))
    const rows = await screen.findAllByRole('row', undefined, SLOW)
    const old = rows.find((r) => within(r).queryByText('v1'))!
    await userEvent.click(within(old).getByRole('button', { name: '현행 전환' }))
    const dlg = await screen.findByRole('dialog', { name: '현행을 바꿀 수 없어요' }, SLOW)
    expect(dlg).toHaveTextContent(/검토할 AI 가이드 제안이 1건 있어요/)
    expect(dlg).toHaveTextContent(/제안을 먼저 확인한 뒤 현행을 변경해 주세요/)
    // 현행은 그대로다
    const v = await listGuideVersions(admin(), 1)
    expect(v.ok && v.data.find((x) => x.version === 'v2')?.state).toBe('현행')
    await userEvent.click(within(dlg).getByRole('button', { name: 'AI 가이드 제안 보기' }))
    expect(await screen.findByRole('button', { name: /^검토 대상/ }, SLOW)).toBeInTheDocument()
  })

  it('등록 버전 보기는 등록한 본문을, 처리 이력 상세 보기는 근거 티켓과 판단을 보여 준다', async () => {
    renderAdmin()
    await openTab()
    await userEvent.click(screen.getByRole('button', { name: /^가이드화 승인/ }))
    const live = cardsOf().find((c) => /메일함 용량/.test(c.textContent ?? ''))!
    await userEvent.click(within(live).getByRole('button', { name: '등록 버전 보기' }))
    const reader = await screen.findByRole('complementary', { name: '가이드 본문' })
    expect(await within(reader).findByText(/오래된 메일부터 삭제하고 휴지통도 비웁니다/, undefined, SLOW)).toBeInTheDocument()
    await userEvent.click(within(reader).getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '가이드 본문' })).toBeNull(), SLOW)
    await userEvent.click(within(cardsOf().find((c) => /메일함 용량/.test(c.textContent ?? ''))!).getByRole('button', { name: '처리 이력 상세 보기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(within(panel).getByText('근거 티켓')).toBeInTheDocument()
    expect(within(panel).getByText('등록 설정')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: '승인하고 초안 등록' })).toBeNull()
  })

  it('기준 가이드가 바뀐 제안은 안내와 함께 등록 버튼이 막히고, 최신 버전과 비교해 바꾸면 풀린다', async () => {
    renderAdmin()
    await openTab()
    const card = cardsOf().find((r) => /SSO 재로그인/.test(r.textContent ?? ''))!
    expect(within(card).getByText(/v1에서 v2로 변경됐어요/)).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(within(panel).getByRole('alert')).toHaveTextContent('기준 가이드가 v1에서 v2로 변경됐어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.')
    expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeDisabled()
    await userEvent.click(within(panel).getByRole('button', { name: '최신 버전과 비교' }))
    await userEvent.click(within(panel).getByRole('button', { name: '이 제안으로 바꾸고 다시 검토' }))
    await waitFor(() => expect(within(panel).getByRole('button', { name: '승인하고 초안 등록' })).toBeEnabled(), SLOW)
  })

  it('반영 안함는 사유를 입력해야 처리된다', async () => {
    renderAdmin()
    await openTab()
    await userEvent.click(within(cardsOf()[0]).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    await userEvent.click(within(panel).getByRole('button', { name: '반영 안함' }))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '반영 안함' }))
    expect(within(dlg).getByText('사유를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText(/사유/), '일회성이에요')
    await userEvent.click(within(dlg).getByRole('button', { name: '반영 안함' }))
    await waitFor(() => expect(get('c1').state).toBe('dropped'), SLOW)
  })

  it('처리한 건의 상세에서는 아래쪽 닫기 단추가 없고, 패널 밖 빈 곳을 눌러도 닫힌다. 반영 안함 안내는 두 줄이다', async () => {
    renderAdmin()
    await openTab()
    await userEvent.click(screen.getByRole('button', { name: /^반영 안함/ }))
    await userEvent.click(within(cardsOf()[0]).getByRole('button', { name: '처리 이력 상세 보기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    expect(within(panel).getByText('반영하지 않기로 한 제안이에요.')).toBeInTheDocument()
    expect(within(panel).getByText(/^사유: /)).toBeInTheDocument()
    expect(within(panel).getAllByRole('button', { name: '닫기' })).toHaveLength(1)
    // 패널 밖 빈 곳(제목 글자)을 누르면 닫힌다
    await userEvent.click(screen.getByRole('heading', { name: 'AI 답변의 근거를 관리해요', level: 1 }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '가이드 초안 검토' })).toBeNull(), SLOW)
  })

  it('신규 가이드의 본문은 편집과 미리보기를 바꿔 볼 수 있다', async () => {
    renderAdmin()
    await openTab()
    const card = cardsOf().find((c) => /메신저 알림/.test(c.textContent ?? ''))!
    await userEvent.click(within(card).getByRole('button', { name: '검토하기' }))
    const panel = await screen.findByRole('complementary', { name: '가이드 초안 검토' })
    const edit = within(panel).getByLabelText('본문') as HTMLTextAreaElement
    expect(edit.value).toMatch(/#### 조치 방법/)
    await userEvent.click(within(panel).getByRole('button', { name: '미리보기' }))
    const view = within(panel).getByRole('region', { name: '본문 미리보기' })
    // 마크다운이 풀려서 보인다: 제목 줄의 #### 기호는 보이지 않고 번호 목록이 목록으로 나온다
    expect(within(view).getByText('조치 방법')).toBeInTheDocument()
    expect(view.textContent).not.toMatch(/####/)
    expect(within(view).getAllByRole('listitem').length).toBeGreaterThanOrEqual(3)
    await userEvent.click(within(panel).getByRole('button', { name: '편집' }))
    expect(within(panel).getByLabelText('본문')).toBeInTheDocument()
  })
})
