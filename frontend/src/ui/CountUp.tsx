/**
 * 숫자가 0에서 올라가는 표시 (대시보드·통계·AI 운영의 건수 카드). (design/ITssue-Prototype.html 숫자 올라가기)
 * 화면에 처음 나타날 때 0에서 올라가고, 값이 바뀌면 이전 값에서 이어서 올라간다.
 * "동작 줄이기" 설정이 켜져 있거나 브라우저가 이를 알 수 없으면 움직이지 않고 값만 보여 준다.
 */
import { useEffect, useRef, useState } from 'react'

const reduced = () => typeof window === 'undefined' || typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
/** 처음엔 빠르게 올라가다 끝에서 천천히 멈춘다 */
const ease = (t: number) => 1 - Math.pow(1 - t, 3)

export function CountUp({ value, decimals = 0, prefix = '', delay = 0, duration = 900 }: { value: number; decimals?: number; prefix?: string; delay?: number; duration?: number }) {
  const [shown, setShown] = useState(() => (reduced() ? value : 0))
  const from = useRef(reduced() ? value : 0)
  useEffect(() => {
    if (reduced() || from.current === value) {
      from.current = value
      setShown(value)
      return
    }
    const start = from.current
    let raf = 0
    let t0 = 0
    const wait = setTimeout(() => {
      const tick = (now: number) => {
        t0 ||= now
        const p = Math.min(1, (now - t0) / duration)
        const v = start + (value - start) * ease(p)
        from.current = v
        setShown(p < 1 ? v : value)
        if (p < 1) raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
    }, delay)
    return () => {
      clearTimeout(wait)
      cancelAnimationFrame(raf)
    }
  }, [value, delay, duration])
  const text = shown.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return <>{prefix + text}</>
}
