/**
 * 접수 상세 패널의 제목: 문의자 화면은 문의 제목(목록·최근 문의와 같은 것)을 쓰고, 접수 요약은 "문의 내용" 칸에 둔다.
 * 제목을 따로 받지 않는 화면(담당자·관리자)은 접수 요약을 제목으로 쓴다.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ticketIdOfInquiry } from '../src/api/mock/staffTickets'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { TicketDetailPanel } from '../src/views/staff/TicketDetailPanel'

const SLOW = { timeout: 3000 }

function panel(title?: string) {
  tokenStore.set('mock.EMP-1001')
  return render(
    <MemoryRouter>
      <AuthProvider>
        <TicketDetailPanel id={ticketIdOfInquiry(105)} tick={0} title={title} onClose={() => {}} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('접수 상세 패널 제목', () => {
  it('제목을 받으면 그 제목을 쓰고, 접수 요약은 문의 내용 칸에 남는다', async () => {
    panel('내 문의 제목')
    expect(await screen.findByRole('heading', { level: 2, name: '내 문의 제목' }, SLOW)).toBeInTheDocument()
    expect(await screen.findByText('문의 내용', undefined, SLOW)).toBeInTheDocument()
  })

  it('제목을 받지 않으면 접수 요약이 제목이다', async () => {
    panel()
    expect(await screen.findByRole('heading', { level: 2, name: '전자결재 접속이 안 돼요' }, SLOW)).toBeInTheDocument()
  })
})
