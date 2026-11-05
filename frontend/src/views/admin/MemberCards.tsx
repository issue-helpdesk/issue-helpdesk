/**
 * 팀원별 카드 (관리자 통계). 팀을 누르면 팀원마다 카드가 3열로 깔린다.
 * 카드 왼쪽 위에 이름, 가운데에 처리 상태 도넛(가운데 전체 건수, 그 아래 완료율)이 보이고,
 * 카드를 누르면 왼쪽(이름·도넛)은 그대로 두고 오른쪽 칸이 펼쳐지며 상태별 건수·비율과 티켓 목록 버튼이 보인다.
 * 도넛은 화면에 들어올 때 호가 차오른다(.donut 의 공통 모션). 개인별 분류 분포는 서버 집계에 없어 보여 주지 않는다.
 */
import type { StatCounts } from '../../api/adminStats'
import { StatSr } from '../../ui/StatSr'
import { useStatTip } from '../../ui/StatTip'
import { STATES, sumOf } from '../staff/StatsView'

const SIZE = 124
const SW = 15

/** 처리 상태 도넛: 가운데에 전체 건수, 그 아래에 완료율 */
export function MiniDonut({ v }: { v: StatCounts }) {
  const total = sumOf(v)
  const R = (SIZE - SW) / 2 - 1
  const C = 2 * Math.PI * R
  const c = SIZE / 2
  const shown = STATES.filter((s) => v[s.k])
  const starts = shown.map((_, i) => shown.slice(0, i).reduce((a, s) => a + (v[s.k] / (total || 1)) * C, 0))
  return (
    <div className="donut mcdn">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} aria-hidden="true">
        <circle cx={c} cy={c} r={R} fill="none" stroke="var(--track)" strokeWidth={SW} />
        {shown.map((s, i) => {
          const len = (v[s.k] / (total || 1)) * C
          return <circle key={s.k} cx={c} cy={c} r={R} fill="none" stroke={s.color} strokeWidth={SW} strokeDasharray={`${Math.max(0, len - 1.5)} ${C - Math.max(0, len - 1.5)}`} strokeDashoffset={-starts[i]} transform={`rotate(-90 ${c} ${c})`} />
        })}
        <text x={c} y={c + SIZE * 0.03} textAnchor="middle" style={{ fontSize: Math.round(SIZE * 0.27), fontWeight: 700, fill: 'var(--ink)' }}>
          {total}
        </text>
        <text x={c} y={c + SIZE * 0.19} textAnchor="middle" style={{ fontSize: Math.round(SIZE * 0.105), fill: 'var(--mute)' }}>
          {total ? `완료 ${Math.round((v.CLS / total) * 100)}%` : '-'}
        </text>
      </svg>
    </div>
  )
}

export interface MemberCardData {
  id: number
  name: string
  v: StatCounts
}

/** meName 이 있으면 그 카드에 "나" 표시, canList 로 티켓 목록 버튼을 보일 카드를 정한다 (담당자는 자기 카드만) */
export function MemberCards({ members, open, onOpen, onList, meName, canList }: { members: MemberCardData[]; open: string | null; onOpen: (name: string | null) => void; onList: (name: string) => void; meName?: string; canList?: (name: string) => boolean }) {
  const tip = useStatTip()
  return (
    <>
      <div className="mcards">
        {members.map((m, i) => {
          const isOpen = open === m.name
          const total = sumOf(m.v)
          return (
            <div key={m.id} className={`mcard${isOpen ? ' open' : ''}${i % 3 === 2 ? ' last3' : ''}`} {...(isOpen ? {} : tip.bind(m.name, m.v))}>
              <button type="button" className="mcb" aria-pressed={isOpen} aria-label={`${m.name} 처리 상태 ${total}건`} onClick={() => onOpen(isOpen ? null : m.name)}>
                <span className="mcn">
                  {m.name}
                  {meName === m.name && <span className="mebadge">나</span>}
                </span>
                <MiniDonut v={m.v} />
                <StatSr v={m.v} />
              </button>
              {isOpen && (
                <div className="mcd">
                  <ul className="dl3">
                    {STATES.map((s) => (
                      <li key={s.k}>
                        <i style={{ background: s.color }} />
                        <span>{s.short}</span>
                        <b>{m.v[s.k]}건</b>
                        <em>{total ? Math.round((m.v[s.k] / total) * 100) : 0}%</em>
                      </li>
                    ))}
                  </ul>
                  <div className="mcf">
                    <span className="small muted">
                      전체 {total}건 · 완료 {total ? Math.round((m.v.CLS / total) * 100) : 0}%
                    </span>
                    {(canList?.(m.name) ?? true) && (
                      <button type="button" className="btn sec sm" onClick={() => onList(m.name)}>
                        티켓 목록 ›
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      {tip.node}
    </>
  )
}
