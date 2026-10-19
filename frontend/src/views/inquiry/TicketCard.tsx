/**
 * 접수 진행 카드: 접수 → 담당자 배정 → 처리 중 → 해결 완료 단계와 현재 안내 문구.
 * 담당자가 처리 결과를 등록하면(해결 확인 대기) 문의자가 "해결됐어요 / 아직 해결되지 않았어요"를 고른다.
 */
import type { CSSProperties } from 'react'
import { TICKET_STATUS } from '../../api/catalog'
import type { Ticket } from '../../api/chatTypes'
import { Icon } from '../../ui/Icon'

type StepState = 'done' | 'cur' | 'todo'

const LABELS = ['접수', '담당자 배정', '처리 중', '해결 완료']

/** Ticket 상태에서 네 단계의 진행 상태와 보조 문구를 정한다 */
function steps(t: Ticket): { states: StepState[]; subs: string[]; tone: string } {
  let states: StepState[]
  if (t.status === 'CLS') states = ['done', 'done', 'done', 'done']
  else if (t.status === 'FIN') states = ['done', 'done', 'done', 'cur']
  else if (t.status === 'WIP' || t.status === 'RDY') states = ['done', 'done', 'cur', 'todo']
  else states = ['done', 'cur', 'todo', 'todo'] // 담당자 배정 전
  const subs = [
    t.created,
    t.assignee ? `${t.assignee} 담당` : '연결 중',
    t.status === 'RDY' ? '대기' : t.status === 'WIP' ? '처리 중' : t.status === 'FIN' || t.status === 'CLS' ? '완료' : '',
    t.status === 'FIN' ? '확인 대기' : t.status === 'CLS' ? '확인 완료' : '',
  ]
  const tone = t.status === 'CLS' ? 'var(--s-ok-dot)' : t.status === 'FIN' ? 'var(--s-need-dot)' : 'var(--s-prog-dot)'
  return { states, subs, tone }
}

/** 문의자에게 보이는 현재 상황 안내 */
function guide(t: Ticket): string {
  if (t.needReply) return `${t.assignee} 담당자가 추가 정보를 요청했어요. 답변을 남겨 주세요.`
  if (t.status === 'CLS') return '문의자 확인으로 종료되었어요. 감사합니다.'
  if (t.status === 'FIN') return '담당자가 처리 결과를 등록했어요. 해결되었는지 확인해 주세요.'
  if (t.status === 'WIP') return `${t.assignee} 담당자가 처리하고 있어요.`
  if (t.status === 'RDY') return `${t.assignee} 담당자(${t.group})에게 배정되었어요. 처리를 기다리고 있어요.`
  return '접수되었습니다. 담당자 연결을 진행하고 있어요.'
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
          {t.receipt}
          {t.jiraId ? ` · ${t.jiraId}` : ''}
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

      {t.status === 'FIN' && (
        <div className="card w" style={{ marginTop: 10 }}>
          <div className="small muted">처리 결과 · {t.assignee}</div>
          <div style={{ marginTop: 4 }}>{t.result || '조치를 완료했습니다.'}</div>
        </div>
      )}

      {t.status === 'FIN' && !readOnly && (
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
      <span className="sr">현재 상태 {t.status ? TICKET_STATUS[t.status].label : '접수'}</span>
    </div>
  )
}
