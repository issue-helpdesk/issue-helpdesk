/**
 * 담당자 화면: 처리할 문의 목록과 상세 패널 (EMP-1107 김담당, 네트워크팀).
 * 시연 접수 14건이 내 몫: 진행 중 8(시연 7 + 문의자 시연 접수 'VPN 연결이 자주 끊겨요.' 1), 해결 확인 대기 3, 해결 완료 4.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { changeTicketStatus, getTicket, listTickets } from '../src/api/tickets'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { mockConfig } from '../src/api/mock/chatStore'
import type { User } from '../src/api/types'

const SLOW = { timeout: 3000 }

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

const staff = (): User => {
  const a = MOCK_ACCOUNTS.find((x) => x.employeeNo === 'EMP-1107')!
  return { id: a.id, employeeNo: a.employeeNo, name: a.name, serviceRole: 'AGENT', departmentName: '네트워크팀' } as User
}

describe('접수 목록·상세 API (모의)', () => {
  it('담당자는 자기 몫을 상태별로 읽고, 긴급도·검색어로 걸러 낸다', async () => {
    const u = staff()
    const by = async (q: Parameters<typeof listTickets>[1]) => {
      const r = await listTickets(u, { assigneeId: u.id, ...q })
      return r.ok ? r.data.items.map((i) => i.summary) : []
    }
    expect(await by({ workStatus: ['RDY', 'WIP'] })).toHaveLength(8)
    expect(await by({ workStatus: ['FIN'] })).toHaveLength(3)
    expect(await by({ workStatus: ['CLS'] })).toHaveLength(4)
    expect(await by({ urgency: ['P1'] })).toEqual(['악성 첨부파일 의심 메일 수신'])
    expect(await by({ q: '프린터' })).toEqual(['프린터 네트워크 연결 오류'])
  })

  it('상세를 처음 열 때만 Jira 알림이 있고, 두 번째부터는 지워진다', async () => {
    const u = staff()
    const a = await getTicket(u, 5001)
    const b = await getTicket(u, 5001)
    expect(a.ok && a.data.jiraMention).toBe(true)
    expect(b.ok && b.data.jiraMention).toBe(false)
  })

  it('상태 변경은 202 처럼 PENDING 으로 답하고, 규칙에 어긋나면 막는다', async () => {
    mockConfig.pipelineScale = 1 // Jira 반영 확인 구간(1.2초)을 실제로 거친다
    const u = staff()
    const bad = await changeTicketStatus(u, 5004, { workStatus: 'FIN', resolutionNote: 'x' }) // RDY → FIN
    expect(!bad.ok && bad.error.code).toBe('TICKET_INVALID_TRANSITION')
    const noNote = await changeTicketStatus(u, 5002, { workStatus: 'FIN' })
    expect(!noNote.ok && noNote.error.code).toBe('TICKET_RESOLUTION_NOTE_REQUIRED')
    const r = await changeTicketStatus(u, 5004, { workStatus: 'WIP' })
    expect(r.ok && r.data.transitionStatus).toBe('PENDING')
    const again = await changeTicketStatus(u, 5004, { workStatus: 'WIP' })
    expect(!again.ok && again.error.code).toBe('INTEGRATION_JOB_IN_PROGRESS')
    await waitFor(async () => {
      const t = await getTicket(u, 5004)
      expect(t.ok && t.data.workStatus).toBe('WIP')
    }, SLOW)
  })
})

describe('처리할 문의 화면', () => {
  it('탭에 건수가 보이고 진행 중 목록이 긴급도 순으로 나온다', async () => {
    renderAs('EMP-1107', '/queue')
    const tab = await screen.findByRole('tab', { name: /진행 중/ }, SLOW)
    await waitFor(() => expect(tab).toHaveTextContent('8'), SLOW)
    expect(screen.getByRole('tab', { name: /해결 확인 대기/ })).toHaveTextContent('3')
    const rows = await within(await screen.findByRole('table')).findAllByRole('row')
    expect(rows[1]).toHaveTextContent('악성 첨부파일 의심 메일 수신') // P1 먼저
  })

  it('검색어로 목록을 줄인다', async () => {
    renderAs('EMP-1107', '/queue')
    const box = await screen.findByLabelText('처리할 문의 검색', undefined, SLOW)
    await userEvent.type(box, '프린터')
    await waitFor(() => expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2), SLOW)
  })

  it('접수를 열면 상세 패널이 붙고, 처리 시작을 누르면 확인 중을 거쳐 처리 중이 된다', async () => {
    mockConfig.pipelineScale = 1
    renderAs('EMP-1107', '/queue/5004')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    expect(await within(panel).findByRole('heading', { name: '재택 VPN 인증 오류' }, SLOW)).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: /처리 시작/ }))
    await waitFor(() => expect(within(panel).getAllByText(/Jira 반영 확인 중/).length).toBeGreaterThan(0), SLOW)
    await waitFor(() => expect(within(panel).getByRole('button', { name: /처리 결과 등록/ })).toBeInTheDocument(), SLOW)
  })

  it('처리 결과는 비워 둘 수 없고, 입력하면 해결 확인 대기가 된다', async () => {
    renderAs('EMP-1107', '/queue/5002')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await userEvent.click(await within(panel).findByRole('button', { name: /처리 결과 등록/ }, SLOW))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: /등록하고/ }))
    expect(await within(dlg).findByText('처리 결과를 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('처리 결과'), 'VPN 인증서를 갱신했습니다.')
    await userEvent.click(within(dlg).getByRole('button', { name: /등록하고/ }))
    await waitFor(() => expect(within(panel).getByText(/문의자의 해결 확인을 기다리고/)).toBeInTheDocument(), SLOW)
  })

  it('다른 담당자의 접수는 열 수 없고, 닫기 버튼으로 패널이 닫힌다', async () => {
    renderAs('EMP-1107', '/queue/5001')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await userEvent.click(within(panel).getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '티켓 상세' })).toBeNull(), SLOW)
  })
})

describe('문의자 접수 상세 (문의 대화)', () => {
  it('접수 상세 버튼으로 패널이 열리고 진행 단계가 보이며, 상태를 바꾸는 버튼은 없다', async () => {
    renderAs('EMP-1001', '/chat/101')
    await userEvent.click(await screen.findByRole('button', { name: /접수 상세/ }, SLOW))
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' })
    expect(await within(panel).findByRole('list', { name: '접수 진행 단계' }, SLOW)).toBeInTheDocument()
    expect(within(panel).getByText('RCPT-1041', { selector: 'dd' })).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /처리 시작|처리 결과 등록/ })).toBeNull()
  })

  it('접수 카드의 상세 보기 칩으로도 열리고, 닫기를 누르면 밀려 나간 뒤 닫힌다', async () => {
    renderAs('EMP-1001', '/chat/101')
    await userEvent.click((await screen.findAllByRole('button', { name: /상세 보기/ }, SLOW))[0])
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' })
    await userEvent.click(within(panel).getByRole('button', { name: '닫기' }))
    expect(panel).toHaveClass('leave') // 움직임 줄이기가 아니면 밀려 나가는 클래스가 먼저 붙는다
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '티켓 상세' })).toBeNull(), SLOW)
  })
})

describe('담당자 내 대시보드', () => {
  it('상태별 건수와 먼저 볼 문의, 우리 팀 현황이 보인다', async () => {
    renderAs('EMP-1107', '/my')
    expect(await screen.findByRole('button', { name: /^처리 중 \(WIP\) 7건/ }, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^해결 확인 대기 \(FIN\) 3건/ })).toBeInTheDocument()
    const first = await screen.findByRole('region', { name: '먼저 볼 문의' })
    expect(await within(first).findByText('악성 첨부파일 의심 메일 수신', undefined, SLOW)).toBeInTheDocument() // P1 이 맨 위
    const team = screen.getByRole('region', { name: '우리 팀 현황' })
    expect(await within(team).findByText('부재 1명', { exact: false }, SLOW)).toBeInTheDocument()
  })

  it('Jira 알림 띠를 누르면 알림이 온 문의만 처리할 문의에서 본다', async () => {
    renderAs('EMP-1107', '/my')
    await userEvent.click(await screen.findByRole('button', { name: /확인할 Jira 알림 2건/ }, SLOW))
    expect(await screen.findByText('확인할 Jira 알림', { selector: 'span' }, SLOW)).toBeInTheDocument()
    expect(await screen.findByRole('tab', { name: /전체 상태/ })).toBeInTheDocument()
    await waitFor(() => expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3), SLOW) // 머리글 + 2건
  })

  it('건수 칸을 누르면 그 상태의 목록으로 이어지고, 검색하면 검색 결과만 나온다', async () => {
    renderAs('EMP-1107', '/my')
    await userEvent.click(await screen.findByRole('button', { name: /^처리 대기 \(RDY\)/ }, SLOW))
    expect(await screen.findByRole('button', { name: /처리 대기 1/ }, SLOW)).toHaveAttribute('aria-pressed', 'true')
  })

  it('검색어를 넣으면 대시보드 대신 검색 결과가 나온다', async () => {
    renderAs('EMP-1107', '/my')
    await userEvent.type(await screen.findByLabelText('내 담당 문의 검색', undefined, SLOW), '프린터')
    const res = await screen.findByRole('region', { name: '검색 결과' })
    expect(await within(res).findByText('프린터 네트워크 연결 오류', undefined, SLOW)).toBeInTheDocument()
  })
})

describe('담당자 통계', () => {
  it('내 통계에는 상태별 현황·접수 추이·긴급도 분포가 있고 팀원별 진행도는 없다', async () => {
    renderAs('EMP-1107', '/stats')
    const sum = await screen.findByRole('region', { name: '상태별 현황' }, SLOW)
    expect(await within(sum).findByRole('button', { name: /^처리 중 \(WIP\) 7건/ }, SLOW)).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /접수 추이 곡선 그래프/ }, SLOW)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '긴급도 분포' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '팀원별 진행도' })).toBeNull()
  })

  it('구역은 따로 불러오는 중으로 먼저 보인다', async () => {
    renderAs('EMP-1107', '/stats')
    const sec = await screen.findByRole('region', { name: '상태별 현황' })
    expect(sec).toHaveAttribute('aria-busy', 'true')
    await waitFor(() => expect(sec).not.toHaveAttribute('aria-busy', 'true'), SLOW)
  })

  it('접수 추이만 실패해도 다른 구역은 보이고, 다시 시도하면 그래프가 나온다', async () => {
    mockConfig.statFail = true
    renderAs('EMP-1107', '/stats')
    const trend = await screen.findByRole('region', { name: '접수 추이' })
    expect(await within(trend).findByText('이 구역을 불러오지 못했어요.', undefined, SLOW)).toBeInTheDocument()
    expect(await within(screen.getByRole('region', { name: '상태별 현황' })).findByRole('button', { name: /^처리 중/ }, SLOW)).toBeInTheDocument()
    await userEvent.click(within(trend).getByRole('button', { name: '다시 시도' }))
    expect(await within(trend).findByRole('img', { name: /접수 추이 곡선 그래프/ }, SLOW)).toBeInTheDocument()
  })

  it('그래프에 초점을 두고 방향키를 누르면 값 말풍선이 뜨고, 표로 바꿀 수 있다', async () => {
    renderAs('EMP-1107', '/stats')
    const chart = await screen.findByRole('img', { name: /접수 추이 곡선 그래프/ }, SLOW)
    chart.focus()
    await waitFor(() => expect(document.querySelectorAll('.hvtip span').length).toBe(2))
    await userEvent.keyboard('{ArrowLeft}')
    await userEvent.click(screen.getByRole('button', { name: '표' }))
    expect(within(screen.getByRole('region', { name: '접수 추이' })).getByRole('table')).toBeInTheDocument()
  })

  it('팀 통계는 팀원별 진행도가 나오고, 이름을 누르면 도넛 개인 현황이 펼쳐진다', async () => {
    renderAs('EMP-1107', '/stats?scope=team')
    const mem = await screen.findByRole('region', { name: '팀원별 진행도' }, SLOW)
    await userEvent.click(await within(mem).findByRole('button', { name: /김담당/ }, SLOW))
    expect(await within(mem).findByText('김담당 · 개인 현황')).toBeInTheDocument()
    expect(within(mem).getAllByRole('img', { name: /건\./ }).length).toBeGreaterThanOrEqual(2) // 처리 상태·분류 도넛
  })

  it('기간을 오늘로 바꾸면 추이 대신 건수만 보인다', async () => {
    renderAs('EMP-1107', '/stats')
    await userEvent.click(await screen.findByRole('button', { name: '오늘' }, SLOW))
    expect(await screen.findByText(/추이 그래프는 보여주지 않아요/, undefined, SLOW)).toBeInTheDocument()
  })

  it('긴급도 줄을 누르면 처리할 문의가 그 긴급도로 걸러진다', async () => {
    renderAs('EMP-1107', '/stats')
    await userEvent.click(await screen.findByRole('button', { name: /^P1 \d+건/ }, SLOW))
    expect(await screen.findByRole('tab', { name: /전체 상태/ }, SLOW)).toBeInTheDocument()
  })
})

describe('문의자에게 메시지(제안)·Slack 미리보기·사이드바 표시', () => {
  it('담당자가 메시지를 보내면 목록과 Slack 미리보기에 남고, 비어 있으면 막는다', async () => {
    renderAs('EMP-1107', '/queue/5002')
    const panel = await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    await userEvent.click(await within(panel).findByRole('button', { name: /문의자에게 메시지/ }, SLOW))
    const dlg = await screen.findByRole('dialog')
    await userEvent.click(within(dlg).getByRole('button', { name: '보내기' }))
    expect(await within(dlg).findByText('내용을 입력해 주세요.')).toBeInTheDocument()
    await userEvent.type(within(dlg).getByLabelText('내용'), '단말 인증서 만료일을 알려 주세요. 비밀번호는 abc123')
    await userEvent.click(within(dlg).getByRole('button', { name: '보내기' }))
    expect(await within(panel).findByText(/김담당 담당자 · 추가 정보 요청/, undefined, SLOW)).toBeInTheDocument()
    expect(within(panel).getByText(/●●●●●●/)).toBeInTheDocument() // 민감정보는 가려서 저장
    expect(await within(panel).findByText('Slack 알림 미리보기')).toBeInTheDocument()
  })

  it('다른 담당자의 접수에는 메시지 버튼이 없다', async () => {
    renderAs('EMP-1107', '/queue/5015')
    await screen.findByRole('complementary', { name: '티켓 상세' }, SLOW)
    expect(screen.queryByRole('button', { name: /문의자에게 메시지/ })).toBeNull()
  })

  it('사이드바 처리할 문의에 건수와 새 알림 표시가 붙고, 알림이 온 건수가 보인다', async () => {
    renderAs('EMP-1107', '/my')
    const nav = await within(await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)).findByRole('button', { name: /처리할 문의/ }, SLOW)
    await waitFor(() => expect(nav).toHaveTextContent('11'), SLOW) // 처리 대기+처리 중+해결 확인 대기
    expect(within(nav).getByRole('img')).toHaveAttribute('aria-label', expect.stringContaining('새 알림 2건'))
  })
})

describe('프로토타입과 맞춘 표시', () => {
  it('긴급도 분포의 설명은 프로토타입의 기준 문구이고 긴급도 이름을 덧붙이지 않는다', async () => {
    renderAs('EMP-1107', '/stats')
    const sec = await screen.findByRole('region', { name: '긴급도 분포' }, SLOW)
    expect(await within(sec).findByText('전사·여러 부서의 주요 업무 중단 또는 광범위한 보안 대응 필요', undefined, SLOW)).toBeInTheDocument()
    expect(within(sec).queryByText(/긴급 ·|높음 ·/)).toBeNull()
  })

  it('접수 추이 범례와 끝 이름표는 프로토타입의 이름을 쓴다', async () => {
    renderAs('EMP-1107', '/stats')
    const sec = await screen.findByRole('region', { name: '접수 추이' }, SLOW)
    expect(await within(sec).findByText('담당자 처리 접수', undefined, SLOW)).toBeInTheDocument()
    expect(within(sec).getByText(/AI 해결은 해결 완료와 합산하지 않아요/)).toBeInTheDocument()
  })

  it('담당자는 사이드바의 문의 메뉴를 접고 펼 수 있고, 문의자에게는 접기 버튼이 없다', async () => {
    const { unmount } = renderAs('EMP-1107', '/my')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    const tg = within(nav).getByRole('button', { name: '문의 메뉴 접기' })
    expect(tg).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(tg)
    expect(within(nav).queryByRole('button', { name: '새 문의' })).toBeNull()
    await userEvent.click(within(nav).getByRole('button', { name: '문의 메뉴 펼치기' }))
    expect(within(nav).getByRole('button', { name: '새 문의' })).toBeInTheDocument()
    unmount()
    renderAs('EMP-1001', '/list')
    const nav2 = await screen.findByRole('navigation', { name: '주 메뉴' }, SLOW)
    expect(within(nav2).queryByRole('button', { name: /문의 메뉴/ })).toBeNull()
  })

  it('사이드바 최근 문의에는 상태 이름만 나오고 담당자 처리·AI 안내 같은 보조 문구는 없다', async () => {
    renderAs('EMP-1001', '/list')
    await waitFor(() => expect(document.querySelectorAll('.recent .rs').length).toBeGreaterThan(0), SLOW)
    document.querySelectorAll('.recent .rs').forEach((e) => expect(e.textContent).not.toContain(' · '))
  })
})
