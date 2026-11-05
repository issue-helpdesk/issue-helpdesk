/**
 * 토스트 목록 (화면 전체에서 하나). 새 토스트는 아래에 붙고, 먼저 뜬 것은 위로 밀려 쌓인다.
 * - 같은 문구가 이미 떠 있으면 새로 쌓지 않고 그 토스트의 시간만 다시 센다.
 * - 한 번에 MAX_SHOWN 개까지만 보인다. 넘으면 가장 오래된(맨 위) 토스트를 먼저 내린다.
 * - 보이는 시간은 문구 길이에 따라 3.5~7초 (toastMs).
 */
export interface ToastItem {
  id: number
  text: string
  /** true 면 사라지는 모션 중 */
  out: boolean
}

/** 한 번에 보이는 최대 개수 */
export const MAX_SHOWN = 3
/** 사라지는 모션(.toast.out)이 끝나는 시간(ms) */
export const OUT_MS = 260
/** 보이는 시간(ms): 짧은 문구는 3.5초, 긴 문구는 읽을 시간을 더해 최대 7초 (글자당 90ms) */
export const toastMs = (text: string) => Math.min(7000, Math.max(3500, 2000 + text.length * 90))

let items: ToastItem[] = []
let seq = 0
const timers = new Map<number, ReturnType<typeof setTimeout>>()
const listeners = new Set<() => void>()

const emit = () => {
  items = [...items]
  listeners.forEach((f) => f())
}
export const getToasts = (): ToastItem[] => items
export function watchToasts(onChange: () => void): () => void {
  listeners.add(onChange)
  return () => {
    listeners.delete(onChange)
  }
}

function dismiss(id: number) {
  clearTimeout(timers.get(id))
  const it = items.find((x) => x.id === id)
  if (!it || it.out) return
  items = items.map((x) => (x.id === id ? { ...x, out: true } : x))
  timers.set(
    id,
    setTimeout(() => {
      timers.delete(id)
      items = items.filter((x) => x.id !== id)
      emit()
    }, OUT_MS),
  )
  emit()
}

/** 토스트를 띄운다 */
export function showToast(text: string) {
  if (!text) return
  const same = items.find((x) => x.text === text && !x.out)
  if (same) {
    clearTimeout(timers.get(same.id))
    timers.set(same.id, setTimeout(() => dismiss(same.id), toastMs(text)))
    return
  }
  const id = ++seq
  items = [...items, { id, text, out: false }]
  timers.set(id, setTimeout(() => dismiss(id), toastMs(text)))
  const live = items.filter((x) => !x.out)
  live.slice(0, Math.max(0, live.length - MAX_SHOWN)).forEach((x) => dismiss(x.id))
  emit()
}

/** 테스트에서 토스트를 모두 비운다 */
export function resetToasts() {
  timers.forEach((t) => clearTimeout(t))
  timers.clear()
  items = []
  emit()
}
