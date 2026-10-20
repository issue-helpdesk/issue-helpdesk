/**
 * 접수 초안 카드. 문의자가 내용을 확인하고 필요하면 고친 뒤에만 접수된다. (PRD 4.7)
 *
 * 수정 화면도 보기 화면과 같은 줄 구성을 유지한다. 문의자가 직접 쓴 말(문의 내용·발생 시점·업무 영향·시도한 조치)만
 * 그 자리에서 입력칸으로 바뀌고(기존 내용이 미리 채워져 있다), 나머지는 잠금 표시와 함께 글자 그대로 둔다.
 * 잠긴 항목(분류·세부 유형·긴급도·담당 그룹)은 고친 글로 다시 판단하며, 값이 바뀐 줄에는 "다시 판단됨"을 붙인다.
 */
import { useState, type ReactNode } from 'react'
import { CATEGORIES, URGENCY_LABEL } from '../../api/catalog'
import type { Draft, DraftEdit, DraftState, RejudgedField } from '../../api/chatTypes'
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

/** 수정 화면에서 입력칸이 되는 항목 */
type EditKey = 'summary' | 'onset' | 'businessImpact' | 'triedActions'
const toFields = (d: Draft): Required<DraftEdit> => ({ summary: d.summary, onset: d.onset, businessImpact: d.businessImpact, triedActions: d.triedActions })

export function DraftCard({ draft: d, state, note, active, busy, onConfirm, onSave, onCancel }: Props) {
  const [editing, setEditing] = useState(false)
  const [fields, setFields] = useState<Required<DraftEdit>>(toFields(d))
  const canAct = active && state === 'view'
  const rejudged = d.rejudged ?? []

  const startEdit = () => {
    setFields(toFields(d))
    setEditing(true)
  }
  const save = async () => {
    if (await onSave(fields)) setEditing(false)
  }

  /** 값이 바뀐 줄 옆에만 붙는 작은 태그 */
  const chg = (k: RejudgedField): ReactNode => (rejudged.includes(k) ? <span className="tag chg">다시 판단됨</span> : null)

  /** 보기 화면의 한 줄 */
  const row = (label: string, value: ReactNode) => (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  )

  /** 고칠 수 있는 줄: 수정 화면에서는 입력칸이 된다 */
  const field = (label: string, id: string, key: EditKey, multiline = false) =>
    editing ? (
      <>
        <dt className="ed">
          <label htmlFor={id}>{label}</label>
        </dt>
        <dd>
          {multiline ? (
            <textarea className="ta" id={id} value={fields[key]} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} />
          ) : (
            <input className="inp" id={id} value={fields[key]} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} />
          )}
        </dd>
      </>
    ) : (
      row(label, d[key])
    )

  /** 자동으로 판단하는 줄: 수정 화면에서는 오른쪽에 잠금 표시를 둔다 */
  const locked = (label: string, value: ReactNode, k?: RejudgedField) =>
    editing ? (
      <>
        <dt>{label}</dt>
        <dd className="lkd">
          <span>
            {value}
            {k && chg(k)}
          </span>
          <span className="lk" title="자동으로 판단하는 항목">
            <Icon name="lock" />
            <span className="sr">자동으로 판단하는 항목</span>
          </span>
        </dd>
      </>
    ) : (
      row(
        label,
        <>
          {value}
          {k && chg(k)}
        </>,
      )
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

      <dl className={`dl${editing ? ' edit' : ''}`}>
        {field('문의 내용', 'd-issue', 'summary', true)}
        {locked('대상 시스템', d.targetSystem)}
        {field('발생 시점', 'd-onset', 'onset')}
        {field('업무 영향', 'd-impact', 'businessImpact')}
        {field('시도한 조치', 'd-tried', 'triedActions')}
        {locked('AI 안내', d.aiSummary)}
        {locked('분류', d.categoryCode ? `${d.categoryCode} · ${CATEGORIES[d.categoryCode].name}` : '미분류 · 서비스데스크 확인', 'category')}
        {locked('세부 유형', d.inquiryTypeCode ? `${d.inquiryTypeCode} · ${d.inquiryTypeName ?? ''}` : '담당자가 확인해요', 'inquiryType')}
        {locked(
          '긴급도',
          <>
            <span className={`pri-${d.urgency.toLowerCase()}`}>
              {d.urgency} · {URGENCY_LABEL[d.urgency]}
            </span>{' '}
            <span className="small muted">{d.urgencyReasons.join(' · ')}</span>
          </>,
          'urgency',
        )}
        {locked('추천 담당 그룹', d.groupName, 'group')}
      </dl>

      {editing && (
        <p className="hint lkh">
          <Icon name="lock" />
          <span>잠금 표시 항목은 적어 주신 내용으로 자동 판단해요. 내용을 고치면 다시 판단해요.</span>
        </p>
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
