/**
 * 해결 확인 대기(FIN) 카드: 해결·미해결을 보낸 뒤 Jira 반영 중(transitionStatus ≠ IDLE)에는 버튼을 잠그고 안내한다.
 * (서버는 같은 접수의 상태 변경이 진행 중일 때 다시 보내면 409 INTEGRATION_JOB_IN_PROGRESS)
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Ticket } from '../src/api/chatTypes'
import { TicketCard } from '../src/views/inquiry/TicketCard'

const fin = (extra: Partial<Ticket> = {}): Ticket => ({
  id: 7,
  receiptNo: 'RCPT-0007',
  jiraKey: 'ITHD-7',
  title: '네트워크 속도 문의',
  categoryCode: 'NET',
  urgency: 'P3',
  groupId: 1,
  groupName: '네트워크팀',
  assigneeId: 2,
  assigneeName: '김담당',
  workStatus: 'FIN',
  assignStatus: 'ASSIGNED',
  jiraSyncStatus: 'SYNCED',
  createdAt: '2026-11-03T09:00:00+09:00',
  resolutionNote: '조치했어요.',
  needReply: false,
  ...extra,
})

describe('해결 확인 대기 카드', () => {
  it('Jira 반영 중이면 해결·미해결 버튼을 잠그고 안내한다', () => {
    render(<TicketCard ticket={fin({ transitionPending: true })} onResolve={() => {}} onReject={() => {}} />)
    expect(screen.getByRole('button', { name: '해결' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '미해결' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Jira에 반영하는 중')
  })

  it('반영 중이 아니면 눌러서 보낼 수 있다', () => {
    render(<TicketCard ticket={fin({ transitionPending: false })} onResolve={() => {}} onReject={() => {}} />)
    expect(screen.getByRole('button', { name: '해결' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '미해결' })).toBeEnabled()
    expect(screen.queryByRole('status')).toBeNull()
  })
})
