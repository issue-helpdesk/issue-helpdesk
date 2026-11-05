import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Toast } from '../src/ui/Toast'

describe('토스트', () => {
  it('부모 상자(움직이는 상세 패널 등) 안이 아니라 body 에 그려서 화면 전체 기준으로 보인다', () => {
    const { container } = render(
      <aside>
        <Toast text="재배정했어요." />
      </aside>,
    )
    expect(container.querySelector('.toast')).toBeNull()
    const el = document.body.querySelector(':scope > .toast')
    expect(el).toHaveTextContent('재배정했어요.')
  })
})
