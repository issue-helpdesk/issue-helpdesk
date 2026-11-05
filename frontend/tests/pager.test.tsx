/**
 * 페이지 이동: 처음·이전 / 번호 / 생략 / 다음·마지막. 한 쪽 분량 이하면 총 건수만 보인다.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pager } from '../src/ui/Pager'
import { pageSlots } from '../src/ui/pageSlots'

describe('pageSlots', () => {
  it('쪽이 7개 이하면 모두, 많으면 7칸 안에서 앞쪽·가운데·뒤쪽 모양으로 보여 준다', () => {
    expect(pageSlots(2, 5)).toEqual([1, 2, 3, 4, 5])
    expect(pageSlots(1, 10)).toEqual([1, 2, 3, 4, 5, '…', 10])
    expect(pageSlots(4, 10)).toEqual([1, 2, 3, 4, 5, '…', 10])
    expect(pageSlots(5, 10)).toEqual([1, '…', 4, 5, 6, '…', 10])
    expect(pageSlots(7, 10)).toEqual([1, '…', 6, 7, 8, 9, 10])
    expect(pageSlots(10, 10)).toEqual([1, '…', 6, 7, 8, 9, 10])
  })
})

describe('Pager', () => {
  it('한 쪽 분량 이하면 총 건수만 보인다', () => {
    render(<Pager page={1} size={20} total={12} onPage={() => {}} />)
    expect(screen.getByText('총 12건')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('처음·이전·번호·다음·마지막으로 옮기고, 첫·끝 쪽에서는 해당 단추가 잠긴다', async () => {
    const onPage = vi.fn()
    const first = render(<Pager page={1} size={20} total={200} onPage={onPage} />)
    expect(screen.getByRole('button', { name: '처음 페이지' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '이전 페이지' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '1쪽' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('button', { name: '3쪽' }))
    await userEvent.click(screen.getByRole('button', { name: '다음 페이지' }))
    await userEvent.click(screen.getByRole('button', { name: '마지막 페이지' }))
    expect(onPage.mock.calls.map((c) => c[0])).toEqual([3, 2, 10])
    first.unmount()

    onPage.mockClear()
    render(<Pager page={10} size={20} total={200} onPage={onPage} />)
    expect(screen.getByRole('button', { name: '다음 페이지' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '마지막 페이지' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '처음 페이지' }))
    await userEvent.click(screen.getByRole('button', { name: '이전 페이지' }))
    expect(onPage.mock.calls.map((c) => c[0])).toEqual([1, 9])
    expect(screen.getByText('181–200 / 200건 · 20개씩')).toBeInTheDocument()
  })
})
