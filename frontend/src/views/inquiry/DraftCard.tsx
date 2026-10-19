/**
 * 접수 초안 카드. 문의자가 내용을 확인하고 필요하면 고친 뒤에만 접수된다. (PRD 4.7)
 * 고치면 분류·긴급도를 다시 판단해 그 결과를 안내한다.
 */
import { useState, type ReactNode } from 'react'
import { CATEGORIES, URGENCY_LABEL } from '../../api/catalog'
import type { Draft, DraftEdit, DraftState } from '../../api/chatTypes'
import { Icon } from '../../ui/Icon'
import { StateBadge } from '../../ui/StateBadge'

interface Props {
  draft: Draft
  state: DraftState
  /** 초안 수정 후 다시 판단한 결과 안내 */
  note: string
  /** 이 카드가 대화의 마지막 초안인지 (지난 초안에는 버튼을 보이지 않는다) */
  active: boolean
  busy: boolean
  onConfirm: () => void
  /** 수정 내용을 보낸다. 성공하면 true */
  onSave: (edit: DraftEdit) => Promise<boolean>
  onCancel: () => void
}

export function DraftCard({ draft: d, state, note, active, busy, onConfirm, onSave, onCancel }: Props) {
  const [editing, setEditing] = useState(false)
  const [fields, setFields] = useState<DraftEdit>({ summary: d.summary, businessImpact: d.businessImpact, triedActions: d.triedActions })
  const canAct = active && state === 'view'

  const startEdit = () => {
    setFields({ summary: d.summary, businessImpact: d.businessImpact, triedActions: d.triedActions })
    setEditing(true)
  }
  const save = async () => {
    if (await onSave(fields)) setEditing(false)
  }

  const row = (label: string, value: ReactNode) => (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  )

  return (
    <div className="card w">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h4>접수 초안</h4>
        {state === 'confirmed' ? (
          <StateBadge tone="ok" label="접수 확인 완료" />
        ) : state === 'cancel' ? (
          <StateBadge tone="recv" label="접수하지 않음" />
        ) : (
          <StateBadge tone="warn" label="확인 대기 · 아직 접수되지 않았어요" />
        )}
      </div>

      {note && canAct && (
        <div className="alert warn" style={{ marginTop: 10 }} role="status">
          <Icon name="alert" />
          <div>{note}</div>
        </div>
      )}

      {editing ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
          <div className="field">
            <label htmlFor="d-issue">문의 내용</label>
            <textarea className="ta" id="d-issue" style={{ minHeight: 72 }} value={fields.summary} onChange={(e) => setFields({ ...fields, summary: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="d-impact">업무 영향</label>
            <input className="inp" id="d-impact" value={fields.businessImpact} onChange={(e) => setFields({ ...fields, businessImpact: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="d-tried">시도한 조치</label>
            <input className="inp" id="d-tried" value={fields.triedActions} onChange={(e) => setFields({ ...fields, triedActions: e.target.value })} />
          </div>
        </div>
      ) : (
        <dl className="dl">
          {row('문의 내용', d.summary)}
          {row('대상 시스템', d.targetSystem)}
          {row('발생 시점', d.onset)}
          {row('업무 영향', d.businessImpact)}
          {row('시도한 조치', d.triedActions)}
          {row('AI 안내', d.aiSummary)}
          {row('Category', d.categoryCode ? `${d.categoryCode} · ${CATEGORIES[d.categoryCode].name}` : '미분류 · 서비스데스크 확인')}
          {row(
            '긴급도',
            <>
              <span className={`pri-${d.urgency.toLowerCase()}`}>
                {d.urgency} · {URGENCY_LABEL[d.urgency]}
              </span>{' '}
              <span className="small muted">{d.urgencyReasons.join(' · ')}</span>
            </>,
          )}
          {row('추천 담당 그룹', d.groupName)}
        </dl>
      )}

      {canAct && (
        <div className="replies">
          {editing ? (
            <>
              <button type="button" className="btn pri sm" disabled={busy} onClick={save}>
                수정 반영하기
              </button>
              <button type="button" className="btn sec sm" disabled={busy} onClick={() => setEditing(false)}>
                취소
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn pri" disabled={busy} onClick={onConfirm}>
                이 내용으로 접수하기
              </button>
              <button type="button" className="btn sec" disabled={busy} onClick={startEdit}>
                수정할게요
              </button>
              <button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>
                접수하지 않을래요
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
