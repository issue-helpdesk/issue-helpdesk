import { useCallback, useEffect, useRef, useState } from 'react'

/** 보이는 시간(ms): 짧은 문구는 3.5초, 긴 문구는 읽을 시간을 더해 최대 7초 (글자당 90ms) */
export const toastMs = (text: string) => Math.min(7000, Math.max(3500, 2000 + text.length * 90))

/**
 * 토스트 문구와 띄우는 함수. 모든 화면이 같은 시간 규칙을 쓴다. 새 문구는 앞의 문구를 바꿔 끼우며(쌓이지 않는다) 시간도 새로 센다.
 * `const { toast, say } = useToast()` 로 쓰고 `<Toast text={toast} />` 를 그린다.
 */
export function useToast() {
  const [toast, setToast] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const say = useCallback((m: string) => {
    clearTimeout(timer.current)
    setToast(m)
    timer.current = setTimeout(() => setToast(''), toastMs(m))
  }, [])
  useEffect(() => () => clearTimeout(timer.current), [])
  return { toast, say }
}
