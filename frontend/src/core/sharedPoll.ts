import { visiblePoll } from './poll'

/**
 * 같은 값의 구독자들이 조회·타이머를 공유한다. 마지막 구독이 끝나면 값도 버린다.
 * 정기 조회는 진행 중이면 건너뛰고, 읽음 처리·탭 복귀는 끝난 뒤 한 번 더 읽는다.
 */
export function createSharedPoll<T>(load: () => Promise<T | null>, period: number, equal: (a: T, b: T) => boolean) {
  type Listener = { receive: (value: T) => void; ms: number }
  type Cycle = { listeners: Set<Listener>; value: T | null; running: boolean; again: boolean; stop?: () => void; ms?: number }
  let cycle: Cycle | null = null

  const run = async (c: Cycle, force: boolean) => {
    if (cycle !== c || document.visibilityState === 'hidden') return
    if (c.running) {
      if (force) c.again = true
      return
    }
    c.running = true
    try {
      const value = await load()
      // 구독이 모두 끝났거나 새 로그인에서 시작한 이전 응답은 버린다.
      if (cycle !== c || value === null) return
      if (c.value === null || !equal(c.value, value)) {
        c.value = value
        c.listeners.forEach((listener) => listener.receive(value))
      }
    } catch {
      // 일시 실패로 자동 조회가 멈추지 않도록 다음 주기에 다시 시도한다.
    } finally {
      c.running = false
      if (cycle === c && c.again) {
        c.again = false
        void run(c, false)
      }
    }
  }

  const schedule = (c: Cycle) => {
    const ms = Math.min(...[...c.listeners].map((listener) => listener.ms))
    // 화면을 오갈 때 구독자가 바뀌어도 같은 주기의 타이머를 미루지 않는다.
    if (c.ms === ms) return
    c.stop?.()
    c.ms = ms
    c.stop = visiblePoll(() => void run(c, false), ms, () => void run(c, true))
  }

  return {
    watch(receive: (value: T) => void, ms = period) {
      const first = cycle === null
      const c = cycle ??= { listeners: new Set(), value: null, running: false, again: false }
      const listener = { receive, ms }
      c.listeners.add(listener)
      schedule(c)
      if (c.value !== null) receive(c.value)
      if (first) void run(c, false)
      return () => {
        c.listeners.delete(listener)
        if (cycle !== c) return
        if (!c.listeners.size) {
          c.stop?.()
          cycle = null
        } else schedule(c)
      }
    },
    refresh() {
      if (cycle) void run(cycle, true)
    },
    get active() { return cycle !== null },
  }
}
