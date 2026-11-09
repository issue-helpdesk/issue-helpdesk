/**
 * 알림 종: 안 읽은 수 배지, 목록(안 읽음 글자·굵은 제목), 안 읽음만 보기, 누르면 이동하고 읽음 처리, 빈 상태·실패.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppNotification } from '../src/api/notifications'
import { fail, ok } from '../src/api/types'

const mk = (id: number, kind: 'ASSIGNED' | 'FIN', readAt: string | null, summary: string | null = '노트북 화면이 깜빡여요'): AppNotification => ({ id, kind, ticketId: 40 + id, inquiryId: 70 + id, receiptNo: `RCPT-09${id}`, summary, readAt, createdAt: new Date().toISOString() })

const state = vi.hoisted(() => ({ list: null as null | ((unreadOnly: boolean) => unknown), count: 2 }))
const markTicketRead = vi.hoisted(() => vi.fn(async () => ({ ok: true, data: { updatedCount: 1 } })))

vi.mock('../src/api/notifications', async (orig) => {
  const real = await orig<typeof import('../src/api/notifications')>()
  return {
    ...real,
    watchUnread: (cb: (c: { count: number; ticketIds: number[] }) => void) => {
      cb({ count: state.count, ticketIds: [] })
      return () => {}
    },
    listNotifications: async (unreadOnly: boolean) => state.list?.(unreadOnly),
    markTicketRead,
    refreshUnread: () => {},
  }
})

import { NotificationBell } from '../src/ui/NotificationBell'

const Where = () => <div data-testid="at">{useLocation().pathname}</div>
const renderBell = () =>
  render(
    <MemoryRouter initialEntries={['/x']}>
      <NotificationBell />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )

beforeEach(() => {
  state.count = 2
  markTicketRead.mockClear()
  state.list = (unreadOnly) => ok({ items: [mk(1, 'ASSIGNED', null), mk(2, 'FIN', null, null), mk(3, 'ASSIGNED', '2026-11-05T00:00:00Z')].filter((n) => !unreadOnly || !n.readAt), hasMore: false })
})

describe('알림 종', () => {
  it('안 읽은 수가 종 이름과 배지에 보인다', () => {
    renderBell()
    expect(screen.getByRole('button', { name: '알림 2건' })).toBeInTheDocument()
  })

  it('안 읽은 알림이 없으면 배지가 없고 이름은 "알림"이다', () => {
    state.count = 0
    renderBell()
    expect(screen.getByRole('button', { name: '알림' })).toBeInTheDocument()
  })

  it('목록은 종류별 문구와 접수번호·제목을 보이고, 안 읽음은 글자로 표시한다 (아이콘 이미지 없음)', async () => {
    const user = userEvent.setup()
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    const dlg = await screen.findByRole('dialog', { name: '알림' })
    expect((await within(dlg).findAllByText('새 티켓이 배정됐어요', { exact: false })).length).toBe(2)
    expect(within(dlg).getAllByText('안 읽음')).toHaveLength(2)
    expect(within(dlg).getByText('RCPT-091 · 노트북 화면이 깜빡여요')).toBeInTheDocument()
    expect(within(dlg).getByText('RCPT-092')).toBeInTheDocument()
    expect(within(dlg).getByText('문의가 처리 완료됐어요', { exact: false })).toBeInTheDocument()
    expect(dlg.querySelector('img')).toBeNull()
  })

  it('"안 읽음만"을 켜면 읽은 알림이 빠진다', async () => {
    const user = userEvent.setup()
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    const dlg = await screen.findByRole('dialog', { name: '알림' })
    await within(dlg).findByText('RCPT-093 · 노트북 화면이 깜빡여요')
    await user.click(within(dlg).getByLabelText('안 읽음만'))
    await screen.findByText('RCPT-092')
    expect(within(dlg).queryByText('RCPT-093 · 노트북 화면이 깜빡여요')).not.toBeInTheDocument()
  })

  it('담당자 알림을 누르면 그 티켓으로, 문의자 알림은 그 문의로 이동하고 읽음 처리한다', async () => {
    const user = userEvent.setup()
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    await user.click(await screen.findByRole('button', { name: /새 티켓이 배정됐어요\s*안 읽음/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/queue/41')
    expect(markTicketRead).toHaveBeenCalledWith(41)
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    await user.click(await screen.findByRole('button', { name: /문의가 처리 완료됐어요\s*안 읽음/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/chat/72')
  })

  it('최근 10일 알림만 최근순으로 보이고, 안내 문구가 있다', async () => {
    const user = userEvent.setup()
    const ago = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString()
    state.list = () => ok({ items: [{ ...mk(1, 'ASSIGNED', null, '오래된 것'), createdAt: ago(12) }, { ...mk(2, 'ASSIGNED', null, '이틀 전'), createdAt: ago(2) }, { ...mk(3, 'FIN', null, '방금'), createdAt: ago(0) }, { ...mk(4, 'ASSIGNED', null, '아홉 날 전'), createdAt: ago(9) }], hasMore: false })
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    const dlg = await screen.findByRole('dialog', { name: '알림' })
    expect(within(dlg).getByText('최근 10일 알림만 보여 드려요.')).toBeInTheDocument()
    await within(dlg).findByText('RCPT-092 · 이틀 전')
    expect(within(dlg).queryByText(/오래된 것/)).not.toBeInTheDocument()
    const order = within(dlg).getAllByRole('button').filter((b) => b.className.includes('bitem')).map((b) => b.textContent)
    expect(order[0]).toContain('방금')
    expect(order[1]).toContain('이틀 전')
    expect(order[2]).toContain('아홉 날 전')
  })

  it('알림이 없으면 빈 상태 안내를, 불러오기에 실패하면 다시 불러오기 버튼을 보인다', async () => {
    const user = userEvent.setup()
    state.list = () => ok({ items: [], hasMore: false })
    const { unmount } = renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    expect(await screen.findByText('새 알림이 없어요')).toBeInTheDocument()
    unmount()
    state.list = () => fail('NETWORK_ERROR', '정보를 불러오지 못했어요. 연결 상태를 확인한 뒤 다시 불러와 주세요.')
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('불러오지 못했어요')
    expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeInTheDocument()
  })

  it('Esc 로 닫으면 종 버튼으로 초점이 돌아온다', async () => {
    const user = userEvent.setup()
    renderBell()
    await user.click(screen.getByRole('button', { name: '알림 2건' }))
    await screen.findByRole('dialog', { name: '알림' })
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '알림' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '알림 2건' })).toHaveFocus()
  })
})
