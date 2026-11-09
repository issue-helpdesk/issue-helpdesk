/**
 * 긴급·높음 문의 한 줄. 대시보드의 "긴급·높음 미해결"과 운영 현황의 "긴급 조치 필요"가 같은 칼럼 순서로 보이도록 함께 쓴다.
 * 순서: 긴급도 → 문의(제목, 접수번호 · 담당 그룹 · 담당자) → 상태 → 경과. 정렬은 긴급도가 높은 순, 같으면 접수가 오래된 순이다.
 */
import type { TicketSummary } from '../../api/ticketTypes'
import { formatElapsed } from '../../core/format'
import { StaffStatus, UrgencyChip } from '../staff/QueueView'

const ticketSub = (t: TicketSummary) => `${t.receiptNo} · ${t.group?.name ?? '-'} · ${t.assignee?.name ?? '배정 전'}`

export function UrgentRow({ t, onOpen }: { t: TicketSummary; onOpen: () => void }) {
  return (
    <button type="button" className="orow" onClick={onOpen} aria-label={`${t.summary}. ${ticketSub(t)}. 접수 후 ${formatElapsed(t.createdAt)} 경과`}>
      <span className="o-p">
        <UrgencyChip u={t.urgency} />
      </span>
      <span className="o-t">
        <b>{t.summary}</b>
        <small>{ticketSub(t)}</small>
      </span>
      <span className="o-s">
        <StaffStatus t={t} />
      </span>
      <span className="o-e">
        <b>{formatElapsed(t.createdAt)}</b> 경과
      </span>
    </button>
  )
}
