/**
 * 상태별 막대·카드 위에서 마우스를 따라다니는 건수 카드 (통계). 처리 대기·처리 중·해결 확인 대기·해결 완료 건수와 전체 건수를 보여 준다.
 * 화면 낭독기·키보드 사용자는 막대·카드 안의 숨은 글(StatSr)로 같은 내용을 읽는다.
 */
import { useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import type { StatCounts } from '../api/adminStats'
import { STATES } from '../views/staff/StatsView'

interface Tip {
  x: number
  y: number
  label: string
  v: StatCounts
}

const W = 190
const H = 160

export function useStatTip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const bind = (label: string, v: StatCounts) => ({
    onMouseMove: (e: MouseEvent) => setTip({ x: e.clientX, y: e.clientY, label, v }),
    onMouseLeave: () => setTip(null),
  })
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

/** 막대·카드 안에 둔다: 화면 낭독기가 상태별 건수를 읽는다 */
export const StatSr = ({ v }: { v: StatCounts }) => <span className="sr">{STATES.map((s) => `${s.short} ${v[s.k]}건`).join(', ')}</span>
