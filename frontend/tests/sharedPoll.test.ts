import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSharedPoll } from '../src/core/sharedPoll'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
let visible: 'visible' | 'hidden'
let cleanup: (() => void)[]
const show = (state: typeof visible) => { visible = state; document.dispatchEvent(new Event('visibilitychange')) }
const flush = () => vi.advanceTimersByTimeAsync(0)
beforeEach(() => {
  vi.useFakeTimers()
  visible = 'visible'
  cleanup = []
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visible)
})
afterEach(() => { cleanup.forEach((stop) => stop()); vi.restoreAllMocks(); vi.useRealTimers() })

describe('공유 자동 조회', () => {
  it('두 화면이 최초 조회·타이머·결과를 공유하고 마지막 구독 뒤에는 중단한다', async () => {
    const load = vi.fn().mockResolvedValue(1)
    const poll = createSharedPoll<number>(load, 60_000, (a, b) => a === b)
    const a = vi.fn(), b = vi.fn()
    const offA = poll.watch(a), offB = poll.watch(b)
    cleanup.push(offA, offB)
    await flush()
    expect(load).toHaveBeenCalledTimes(1)
    expect(a).toHaveBeenCalledWith(1)
    expect(b).toHaveBeenCalledWith(1)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(load).toHaveBeenCalledTimes(2)
    expect(a).toHaveBeenCalledTimes(1) // 값이 같으면 화면을 다시 갱신하지 않는다.
    offA(); offB()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('느린 응답을 기다리는 동안 정기 요청을 쌓지 않는다', async () => {
    const pending = deferred<number>()
    const load = vi.fn().mockReturnValue(pending.promise)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    cleanup.push(poll.watch(vi.fn()))
    await vi.advanceTimersByTimeAsync(5000)
    expect(load).toHaveBeenCalledTimes(1)
    pending.resolve(1); await flush()
    expect(load).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('숨겨진 탭에서는 멈추고 복귀한 즉시 다시 읽는다', async () => {
    const load = vi.fn().mockResolvedValue(1)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    cleanup.push(poll.watch(vi.fn()))
    await flush()
    show('hidden'); await vi.advanceTimersByTimeAsync(5000)
    expect(load).toHaveBeenCalledTimes(1)
    show('visible'); await flush()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('조회 도중 읽음 처리·탭 복귀가 겹치면 끝난 뒤 한 번만 더 읽는다', async () => {
    const pending = deferred<number>()
    const load = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(0)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    const receive = vi.fn()
    cleanup.push(poll.watch(receive))
    poll.refresh(); poll.refresh(); show('hidden'); show('visible')
    expect(load).toHaveBeenCalledTimes(1)
    pending.resolve(2); await flush()
    expect(load).toHaveBeenCalledTimes(2)
    expect(receive.mock.calls.map(([value]) => value)).toEqual([2, 0])
  })

  it('이전 접속의 늦은 응답과 저장된 값을 새 접속에 전달하지 않는다', async () => {
    const pending = deferred<number>()
    const load = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(9)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    const old = vi.fn(), next = vi.fn()
    const stop = poll.watch(old)
    stop()
    cleanup.push(poll.watch(next))
    pending.resolve(1); await flush()
    expect(old).not.toHaveBeenCalled()
    expect(next.mock.calls.map(([value]) => value)).toEqual([9])
  })

  it('조회 실패가 발생해도 다음 주기에 복구한다', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(null).mockResolvedValue(3)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    const receive = vi.fn()
    cleanup.push(poll.watch(receive))
    await vi.advanceTimersByTimeAsync(2000)
    expect(load).toHaveBeenCalledTimes(3)
    expect(receive).toHaveBeenCalledWith(3)
  })

  it('화면 이동으로 구독자가 바뀌어도 다음 조회 시각을 미루지 않는다', async () => {
    const load = vi.fn().mockResolvedValue(1)
    const poll = createSharedPoll<number>(load, 1000, (a, b) => a === b)
    cleanup.push(poll.watch(vi.fn()))
    await vi.advanceTimersByTimeAsync(900)
    const stop = poll.watch(vi.fn())
    stop()
    await vi.advanceTimersByTimeAsync(100)
    expect(load).toHaveBeenCalledTimes(2)
  })
})
