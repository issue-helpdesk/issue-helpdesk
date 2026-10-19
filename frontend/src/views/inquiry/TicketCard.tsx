/**
 * 접수 진행 카드: 접수 → 담당자 배정 → 처리 중 → 해결 완료 단계와 현재 안내 문구.
 * 담당자 배정 여부는 배정 상태(assignStatus)로, 처리 단계는 업무 상태(workStatus)로 본다.
 * Jira 생성이나 배정에 실패해도 문의자에게는 '담당자 확인 중'으로 안내한다. (docs/07.API_계약서.md 상태 전환)
 * 담당자가 처리 결과를 등록하면(해결 확인 대기) 문의자가 "해결됐어요 / 아직 해결되지 않았어요"를 고른다.
 */
import type { CSSProperties } from 'react'
import { WORK_STATUS } from '../../api/catalog'
import type { Ticket } from '../../api/chatTypes'
import { formatDateTime } from '../../core/format'
import { Icon } from '../../ui/Icon'

type StepState = 'done' | 'cur' | 'todo'

const LABELS = ['접수', '담당자 배정', '처리 중', '해결 완료']

/** 담당자가 배정되었는지 (배정 상태로 판단) */
const assigned = (t: Ticket) => t.assignStatus === 'ASSIGNED'

/** Jira 생성 또는 배정에 실패해 관리자가 확인하는 중인지 */
const needsAdmin = (t: Ticket) => t.jiraSyncStatus === 'NEEDS_ADMIN' || t.assignStatus === 'NEEDS_ADMIN'

/** Ticket 상태에서 네 단계의 진행 상태와 보조 문구를 정한다 */
function steps(t: Ticket): { states: StepState[]; subs: string[]; tone: string } {
  const s = assigned(t) ? t.workStatus : null
  let states: StepState[]
  if (s === 'CLS') states = ['done', 'done', 'done', 'done']
  else if (s === 'FIN') states = ['done', 'done', 'done', 'cur']
  else if (s === 'WIP' || s === 'RDY') states = ['done', 'done', 'cur', 'todo']
  else states = ['done', 'cur', 'todo', 'todo'] // 담당자 배정 전
  const subs = [
    formatDateTime(t.createdAt),
    t.assigneeName && assigned(t) ? `${t.assigneeName} 담당` : needsAdmin(t) ? '확인 중' : '연결 중',
    s === 'RDY' ? '대기' : s === 'WIP' ? '처리 중' : s === 'FIN' || s === 'CLS' ? '완료' : '',
    s === 'FIN' ? '확인 대기' : s === 'CLS' ? '확인 완료' : '',
  ]
  const tone = s === 'CLS' ? 'var(--s-ok-dot)' : s === 'FIN' ? 'var(--s-need-dot)' : 'var(--s-prog-dot)'
  return { states, subs, tone }
}

/** 문의자에게 보이는 현재 상황 안내 */
function guide(t: Ticket): string {
  if (needsAdmin(t)) return '접수되었어요. 담당자 연결을 확인하고 있어요. 접수 내용은 그대로 보관되어 있어요.'
  if (t.needReply) return `${t.assigneeName} 담당자가 추가 정보를 요청했어요. 답변을 남겨 주세요.`
  if (!assigned(t)) return '접수되었습니다. 담당자 연결을 진행하고 있어요.'
  if (t.workStatus === 'CLS') return '문의자 확인으로 종료되었어요. 감사합니다.'
  if (t.workStatus === 'FIN') return '담당자가 처리 결과를 등록했어요. 해결되었는지 확인해 주세요.'
  if (t.workStatus === 'WIP') return `${t.assigneeName} 담당자가 처리하고 있어요.`
  return `${t.assigneeName} 담당자(${t.groupName})에게 배정되었어요. 처리를 기다리고 있어요.`
}

interface Props {
  ticket: Ticket
  /** 지난 카드(다시 확인 요청 전의 기록)는 버튼 없이 보여 준다 */
  readOnly?: boolean
  busy?: boolean
  onResolve: () => void
  onReject: () => void
}

export function TicketCard({ ticket: t, readOnly = false, busy = false, onResolve, onReject }: Props) {
  const { states, subs, tone } = steps(t)
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
        <b style={{ fontSize: 15 }}>{t.title}</b>
        <span className="mono small muted">
          {t.receiptNo}
          {t.jiraKey ? ` · ${t.jiraKey}` : ''}
        </span>
      </div>

      <div className="stepper" style={{ '--tone': tone } as CSSProperties} role="list" aria-label="접수 진행 단계">
        {LABELS.map((l, k) => (
          <div key={l} role="listitem" className={`st ${states[k]}`} aria-current={states[k] === 'cur' ? 'step' : undefined}>
            <span className="n">{states[k] === 'done' && <Icon name="check" />}</span>
            <b>{l}</b>
            <small>{subs[k]}</small>
          </div>
        ))}
      </div>

      <p style={{ marginTop: 14, fontSize: 14, lineHeight: '22px' }}>{guide(t)}</p>

      {t.workStatus === 'FIN' && (
        <div className="card w" style={{ marginTop: 10 }}>
          <div className="small muted">처리 결과 · {t.assigneeName}</div>
          <div style={{ marginTop: 4 }}>{t.resolutionNote || '조치를 완료했습니다.'}</div>
        </div>
      )}

      {t.workStatus === 'FIN' && !readOnly && (
        <div className="replies">
          <button type="button" className="chip on" disabled={busy} onClick={onResolve}>
            해결됐어요
          </button>
          <button type="button" className="chip" disabled={busy} onClick={onReject}>
            아직 해결되지 않았어요
          </button>
        </div>
      )}

      {readOnly && (
        <p className="small muted" style={{ marginTop: 10 }}>
          문의자 응답: 아직 해결되지 않음 → 다시 확인 요청
        </p>
      )}

      {/* 현재 상태 이름을 글자로도 알려 스크린리더가 같은 정보를 읽게 한다 */}
      <span className="sr">현재 상태 {t.workStatus && assigned(t) ? WORK_STATUS[t.workStatus].label : '접수'}</span>
    </div>
  )
}
