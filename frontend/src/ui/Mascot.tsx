/**
 * 잇슈 캐릭터 (새 문의 첫 화면의 인사 장식).
 *
 * 둥실거림과 바닥 그림자는 CSS 가 맡고, 눈은 포인터를 따라가며 가끔 깜빡인다.
 * "움직임 줄이기" 설정에서는 가만히 있는다. 장식이므로 스크린리더에는 이름만 알린다.
 */
import { useEffect, useRef } from 'react'
import body from '../assets/mascot/berry-body.webp'
import eyes from '../assets/mascot/berry-eyes.webp'

/** 가만히 있을 때 눈이 가끔 향하는 자리 */
const GLANCES: [number, number][] = [[-14, 0], [14, 0], [0, -9], [-10, 6], [10, 6], [0, 0]]

export function Mascot() {
  const box = useRef<HTMLDivElement>(null)
  const eye = useRef<HTMLImageElement>(null)

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion:reduce)').matches) return
    let last = 0
    let pos: [number, number] = [0, 0]
    let timer = 0
    const move = (x: number, y: number) => {
      pos = [x, y]
      if (eye.current) eye.current.style.transform = `translate(${x}px,${y}px)`
    }
    const blink = () => {
      if (!eye.current) return
      eye.current.style.transform = `translate(${pos[0]}px,${pos[1]}px) scaleY(.12)`
      setTimeout(() => move(pos[0], pos[1]), 130)
    }
    const onMove = (ev: PointerEvent) => {
      last = Date.now()
      const el = box.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const dx = ev.clientX - (r.left + r.width / 2)
      const dy = ev.clientY - (r.top + r.height / 2)
      const d = Math.hypot(dx, dy) || 1
      const m = Math.min(d / 90, 1) * (r.width * 0.045)
      move((dx / d) * m, (dy / d) * m * 0.7)
    }
    // 2.5초 넘게 포인터가 움직이지 않으면 눈을 이리저리 돌리고, 가끔 깜빡인다
    const tick = () => {
      timer = window.setTimeout(() => {
        if (Date.now() - last > 2500) {
          const g = GLANCES[Math.floor(Math.random() * GLANCES.length)]
          move(g[0], g[1])
          if (Math.random() < 0.6) setTimeout(blink, 260)
        } else if (Math.random() < 0.3) blink()
        tick()
      }, 1800 + Math.random() * 2200)
    }
    document.addEventListener('pointermove', onMove)
    tick()
    return () => {
      document.removeEventListener('pointermove', onMove)
      clearTimeout(timer)
    }
  }, [])

  return (
    <div className="berry" ref={box} role="img" aria-label="잇슈 캐릭터">
      <img className="bb" src={body} alt="" />
      <img className="be" ref={eye} src={eyes} alt="" />
    </div>
  )
}
