/**
 * 잇슈 캐릭터. 새 문의 첫 화면에서는 인사 장식으로, 로그인 화면에서는 상담 창 위로 엿보는 모습으로 쓴다.
 *
 * 둥실거림과 바닥 그림자는 CSS 가 맡고, 눈은 포인터를 따라가며 가끔 깜빡인다.
 * "움직임 줄이기" 설정에서는 가만히 있는다. 엿보기(peek)는 비밀번호 칸에 있는 동안(shy) 눈을 감는다.
 * 눈 감기는 움직임이 아니라 가려 주는 표현이라 움직임 줄이기에서도 동작한다.
 */
import { useEffect, useRef } from 'react'
import body from '../assets/mascot/berry-body.webp'
import eyes from '../assets/mascot/berry-eyes.webp'

/** 가만히 있을 때 눈이 가끔 향하는 자리 */
const GLANCES: [number, number][] = [[-14, 0], [14, 0], [0, -9], [-10, 6], [10, 6], [0, 0]]

interface Props {
  /** 상담 창 위로 엿보는 모습 (로그인 화면). 위쪽만 보이고 둥실거리지 않는다 */
  peek?: boolean
  /** 엿보는 중에 눈을 감는다 (비밀번호를 입력하는 동안) */
  shy?: boolean
}

export function Mascot({ peek = false, shy = false }: Props) {
  const shyRef = useRef(shy)
  // 눈 감기 상태를 깜빡임 타이머가 최신 값으로 읽도록 맞춰 둔다
  useEffect(() => {
    shyRef.current = shy
  }, [shy])
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
      if (!eye.current || shyRef.current) return
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
    <div className={peek ? `peek${shy ? ' shy' : ''}` : 'berry'} ref={box} {...(peek ? { 'aria-hidden': true } : { role: 'img', 'aria-label': '잇슈 캐릭터' })}>
      <img className="bb" src={body} alt="" />
      <img className="be" ref={eye} src={eyes} alt="" />
      {peek && (
        // 눈을 감은 모습: 비밀번호를 입력하는 동안 눈 이미지 대신 보인다
        <svg className="ec" viewBox="0 0 720 720" aria-hidden="true">
          <path d="M205 398Q232 424 259 398M314 408Q341 434 368 408" fill="none" stroke="#43223B" strokeWidth="13" strokeLinecap="round" />
        </svg>
      )}
    </div>
  )
}
