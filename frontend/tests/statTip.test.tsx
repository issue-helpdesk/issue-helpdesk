import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useStatTip } from '../src/ui/StatTip'

const V = { RDY: 1, WIP: 2, REV: 3, FIN: 4 } as never

function Two({ showB = true }: { showB?: boolean }) {
  const a = useStatTip()
  const b = useStatTip()
  return (
    <div>
      <div data-testid="a" {...a.bind('팀', V)}>
        A
      </div>
      {showB && (
        <div data-testid="b" {...b.bind('구성원', V)}>
          B
        </div>
      )}
      <div data-testid="out">밖</div>
      {a.node}
      {b.node}
    </div>
  )
}

const tips = () => document.querySelectorAll('.stip')

describe('통계 건수 카드', () => {
  it('막대 밖으로 마우스가 나가면 mouseleave 가 오지 않아도 닫힌다', () => {
    render(<Two />)
    fireEvent.mouseMove(screen.getByTestId('a'), { clientX: 10, clientY: 10 })
    expect(tips()).toHaveLength(1)
    fireEvent.mouseMove(screen.getByTestId('out'), { clientX: 400, clientY: 400 })
    expect(tips()).toHaveLength(0)
  })

  it('다른 막대 위로 옮기면 먼저 뜬 카드는 닫히고 하나만 보인다', () => {
    render(<Two />)
    fireEvent.mouseMove(screen.getByTestId('a'), { clientX: 10, clientY: 10 })
    fireEvent.mouseMove(screen.getByTestId('b'), { clientX: 20, clientY: 20 })
    expect(tips()).toHaveLength(1)
    expect(tips()[0]).toHaveTextContent('구성원')
  })

  it('막대가 사라지면 카드도 닫힌다', () => {
    const { rerender } = render(<Two />)
    fireEvent.mouseMove(screen.getByTestId('b'), { clientX: 20, clientY: 20 })
    expect(tips()).toHaveLength(1)
    rerender(<Two showB={false} />)
    fireEvent.mouseMove(document.body, { clientX: 30, clientY: 30 })
    expect(tips()).toHaveLength(0)
  })
})
