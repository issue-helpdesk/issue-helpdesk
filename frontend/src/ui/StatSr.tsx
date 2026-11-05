import type { StatCounts } from '../api/adminStats'
import { STATES } from '../views/staff/StatsView'

/** 막대·카드 안에 둔다: 화면 낭독기가 상태별 건수를 읽는다 */
export const StatSr = ({ v }: { v: StatCounts }) => <span className="sr">{STATES.map((s) => `${s.short} ${v[s.k]}건`).join(', ')}</span>
