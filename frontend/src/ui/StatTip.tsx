/**
 * 상태별 막대·카드 위에서 마우스를 따라다니는 건수 카드 (통계). 처리 대기·처리 중·해결 확인 대기·해결 완료 건수와 전체 건수를 보여 준다.
 * 화면 낭독기·키보드 사용자는 막대·카드 안의 숨은 글(StatSr)로 같은 내용을 읽는다.
 */
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { createPortal } from 'react-dom'
import type { StatCounts } from '../api/adminStats'
import { STATES } from '../views/staff/StatsView'

interface Tip {
  x: number
  y: number
  label: string
  v: StatCounts
  /** 카드가 붙어 있는 막대·카드. 마우스가 여기를 벗어나면 카드를 닫는다 */
  from: HTMLElement
}

const W = 190
const H = 160

/** 건수 카드는 화면에 하나만 둔다: 새 카드가 뜨면 먼저 떠 있던 카드를 닫는다 (막대와 그 아래 펼친 카드가 따로 훅을 쓴다) */
let closeShown: (() => void) | null = null

export function useStatTip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const hide = useRef(() => setTip(null))
  const bind = (label: string, v: StatCounts) => ({
    onMouseMove: (e: ReactMouseEvent) => {
      if (closeShown && closeShown !== hide.current) closeShown()
      closeShown = hide.current
      setTip({ x: e.clientX, y: e.clientY, label, v, from: e.currentTarget as HTMLElement })
    },
    onMouseLeave: () => setTip(null),
  })
  // mouseleave 는 막대가 눌려 자리가 바뀌거나 사라질 때, 스크롤할 때 오지 않을 수 있다. 마우스가 막대 밖에 있으면 닫는다
  const from = tip?.from
  useEffect(() => {
    if (!from) return
    const off = (e: Event) => {
      if (!from.isConnected || (e instanceof MouseEvent && e.target instanceof Node && !from.contains(e.target))) setTip(null)
      else if (e.type === 'scroll' || e.type === 'blur') setTip(null)
    }
    document.addEventListener('mousemove', off)
    document.addEventListener('scroll', off, true)
    window.addEventListener('blur', off)
    return () => {
      document.removeEventListener('mousemove', off)
      document.removeEventListener('scroll', off, true)
      window.removeEventListener('blur', off)
    }
  }, [from])
  const node = tip
    ? createPortal(
        <div
          className="stip"
          role="presentation"
          style={{ left: Math.max(8, tip.x + 16 + W > window.innerWidth - 8 ? tip.x - W - 16 : tip.x + 16), top: Math.max(8, tip.y + 16 + H > window.innerHeight - 8 ? tip.y - H - 16 : tip.y + 16) }}
        >
          <b>{tip.label}</b>
          <small>전체 {STATES.reduce((a, s) => a + tip.v[s.k], 0)}건</small>
          {STATES.map((s) => (
            <div key={s.k}>
              <i style={{ background: s.color }} />
              <span>{s.short}</span>
              <b>{tip.v[s.k]}건</b>
            </div>
          ))}
        </div>,
        document.body,
      )
    : null
  return { bind, node }
}
