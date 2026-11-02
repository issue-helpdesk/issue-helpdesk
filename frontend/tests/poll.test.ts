/**
 * 서버를 주기적으로 읽는 공통 도구: 탭이 가려지면 멈추고 다시 보이면 곧바로 한 번 읽는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { visiblePoll } from '../src/core/poll'

const setVisibility = (v: 'visible' | 'hidden') => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => v })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  vi.useFakeTimers()
  setVisibility('visible')
})
afterEach(() => {
  vi.useRealTimers()
  setVisibility('visible')
})

describe('visiblePoll', () => {
  it('보이는 동안 간격마다 부르고, 멈추면 더 부르지 않는다', () => {
    const fn = vi.fn()
    const stop = visiblePoll(fn, 1000)
    vi.advanceTimersByTime(3500)
    expect(fn).toHaveBeenCalledTimes(3)
    stop()
    vi.advanceTimersByTime(5000)
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('탭이 가려지면 멈추고, 다시 보이면 곧바로 한 번 읽고 이어간다', () => {
    const fn = vi.fn()
    const stop = visiblePoll(fn, 1000)
    setVisibility('hidden')
    vi.advanceTimersByTime(10_000)
    expect(fn).not.toHaveBeenCalled()
    setVisibility('visible')
    expect(fn).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(2000)
    expect(fn).toHaveBeenCalledTimes(3)
    stop()
  })
})
