import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastHost } from '../src/ui/Toast'
import { MAX_SHOWN, OUT_MS, resetToasts, showError, showToast, toastMs } from '../src/ui/toastStore'

const texts = () => [...document.body.querySelectorAll('.toast:not(.out)')].map((e) => e.textContent)

beforeEach(() => {
  vi.useFakeTimers()
  resetToasts()
})
afterEach(() => {
  resetToasts()
  vi.useRealTimers()
})

describe('토스트 쌓기', () => {
  it('body 에 그려서 부모 상자(움직이는 상세 패널 등) 안이 아니라 화면 전체 기준이 된다', () => {
    const { container } = render(
      <aside>
        <ToastHost />
      </aside>,
    )
    act(() => showToast('재배정했어요.'))
    expect(container.querySelector('.toast')).toBeNull()
    expect(document.body.querySelector(':scope > .toasts > .toast')).toHaveTextContent('재배정했어요.')
  })

  it('새 토스트는 아래에 붙고 먼저 뜬 것은 위에 쌓인다', () => {
    render(<ToastHost />)
    act(() => {
      showToast('첫째')
      showToast('둘째')
    })
    expect(texts()).toEqual(['첫째', '둘째'])
  })

  it('같은 문구가 이미 떠 있으면 쌓지 않고 시간만 다시 센다', () => {
    render(<ToastHost />)
    act(() => showToast('저장했어요.'))
    act(() => vi.advanceTimersByTime(3000))
    act(() => showToast('저장했어요.'))
    expect(texts()).toEqual(['저장했어요.'])
    act(() => vi.advanceTimersByTime(3000)) // 처음 시각 기준이면 이미 사라졌을 시간
    expect(texts()).toEqual(['저장했어요.'])
  })

  it(`최대 ${MAX_SHOWN}개까지만 보이고 넘으면 가장 오래된 것부터 내린다`, () => {
    render(<ToastHost />)
    act(() => {
      ;['하나', '둘', '셋', '넷'].forEach(showToast)
    })
    expect(texts()).toEqual(['둘', '셋', '넷'])
    act(() => vi.advanceTimersByTime(OUT_MS + 10))
    expect(document.body.querySelectorAll('.toast')).toHaveLength(3)
  })

  it('보이는 시간이 지나면 사라지고, 다 사라지면 컨테이너도 없다', () => {
    render(<ToastHost />)
    act(() => showToast('짧아요.'))
    act(() => vi.advanceTimersByTime(toastMs('짧아요.') + OUT_MS + 10))
    expect(document.body.querySelector('.toasts')).toBeNull()
  })
})

describe('실패 안내 토스트', () => {
  it('시간이 지나도 사라지지 않고, 닫기(×)를 누르면 내려간다', () => {
    render(<ToastHost />)
    act(() => showError('저장하지 못했어요.'))
    act(() => vi.advanceTimersByTime(60000))
    const t = document.body.querySelector('.toast.err')!
    expect(t).toHaveTextContent('저장하지 못했어요.')
    expect(t).toHaveAttribute('role', 'alert')
    act(() => (t.querySelector('.toast-x') as HTMLButtonElement).click())
    act(() => vi.advanceTimersByTime(OUT_MS + 10))
    expect(document.body.querySelector('.toasts')).toBeNull()
  })

  it('일반 토스트는 닫기 버튼이 없고 그대로 사라진다', () => {
    render(<ToastHost />)
    act(() => showToast('저장했어요.'))
    expect(document.body.querySelector('.toast-x')).toBeNull()
  })
})
