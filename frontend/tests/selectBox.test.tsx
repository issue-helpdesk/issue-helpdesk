/**
 * 선택 상자(ui/SelectBox): 눌러서 열고 고르기, 키보드(↑↓ Enter Esc), 고른 항목 표시, 바깥 누르면 닫기, 비활성.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { SelectBox } from '../src/ui/SelectBox'

const OPTIONS = [
  { value: 'a', label: '관리자 전용' },
  { value: 'b', label: '사내 제한' },
  { value: 'c', label: '사내 일반' },
]

function Demo({ onEsc }: { onEsc?: () => void }) {
  const [v, setV] = useState('')
  // 바깥 창(모달)처럼 document 에서 Esc 를 듣는다
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onEsc?.()
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onEsc])
  return (
    <div>
      <label htmlFor="x">열람 범위</label>
      <SelectBox id="x" value={v} options={OPTIONS} placeholder="선택해 주세요" onChange={setV} />
      <span data-testid="v">{v}</span>
    </div>
  )
}

describe('SelectBox', () => {
  it('누르면 목록이 열리고, 항목을 고르면 닫히며 칸에 보인다(고른 항목은 선택 표시)', async () => {
    render(<Demo />)
    const box = screen.getByLabelText('열람 범위')
    expect(box).toHaveTextContent('선택해 주세요')
    expect(box).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(box)
    expect(box).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('option')).toHaveLength(3)
    await userEvent.click(screen.getByRole('option', { name: '사내 제한' }))
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box).toHaveTextContent('사내 제한')
    expect(screen.getByTestId('v')).toHaveTextContent('b')
    await userEvent.click(box)
    expect(screen.getByRole('option', { name: '사내 제한' })).toHaveAttribute('aria-selected', 'true')
  })

  it('키보드: ↓ 로 열고 옮기고 Enter 로 고르며, Esc 는 목록만 닫는다(바깥으로 번지지 않는다)', async () => {
    const onEsc = vi.fn()
    render(<Demo onEsc={onEsc} />)
    const box = screen.getByLabelText('열람 범위')
    box.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await userEvent.keyboard('{ArrowDown}{Enter}')
    expect(screen.getByTestId('v')).toHaveTextContent('b')
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(onEsc).not.toHaveBeenCalled()
    expect(box).toHaveFocus()
  })

  it('바깥을 누르면 닫히고, 비활성 칸은 열리지 않는다', async () => {
    render(
      <>
        <Demo />
        <button type="button">바깥</button>
        <label htmlFor="off">문서</label>
        <SelectBox id="off" value="" options={[]} disabled placeholder="먼저 선택해 주세요" onChange={() => {}} />
      </>,
    )
    await userEvent.click(screen.getByLabelText('열람 범위'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '바깥' }))
    expect(screen.queryByRole('listbox')).toBeNull()
    await userEvent.click(screen.getByLabelText('문서'))
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})
