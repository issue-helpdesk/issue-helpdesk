/**
 * AI 판단 이력 (관리자 전용, 접수 상세 패널). 위에서 아래로: 문의 요약 → AI 원래 판단(보라 박스) → 규칙이 바꾼 내역 → 최종 적용.
 * 서버(IQ-10)가 준 JSON 은 모양이 바뀌어도 화면이 깨지지 않게 있는 값만 보여 준다. (design/ITssue-Prototype.html assessHtml)
 * AI 가 추가 질문(ASK_MORE)을 해서 다음 판단이 생긴 경우, 두 판단 사이에 "AI가 더 물어본 항목"을 화살표로 이어 보여 준다.
 * preset 을 주면 서버에서 읽지 않고 그 판단들을 쓴다 (모의 시연).
 */
import { Fragment, useEffect, useState } from 'react'
import { ACTION_LABEL, FIELD_LABEL, MISSING_LABEL, listAssessments, type Assessment } from '../../api/assessments'
import { CATEGORIES, urgencyText } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { urgencyReasonText } from '../../api/urgencyReason'
import { formatDateTime } from '../../core/format'
import { useAuth } from '../../core/session'
import { StateBadge } from '../../ui/StateBadge'

const catName = (code: string | null | undefined) => (code ? (CATEGORIES[code as CategoryCode]?.name ?? code) : '-')
const pTone = (p: string | null) => (p === 'P1' ? 'urg' : p === 'P2' ? 'warn' : 'recv')
/** 바뀐 값 보여 주기: 처리 방향·분류 코드는 화면 말로, 나머지는 그대로 */
function show(field: string, v: unknown): string {
  if (v == null || v === '') return '-'
  const s = String(v)
  if (field === 'action') return ACTION_LABEL[s] ?? s
  if (field === 'categoryCode' || field === 'category') return catName(s)
  if (field === 'urgency') return urgencyText(s)
  return s
}

export function AssessmentHistory({ inquiryId, preset }: { inquiryId: number; preset?: Assessment[] }) {
  const { user } = useAuth()
  const [items, setItems] = useState<Assessment[] | null>(preset ?? null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user || preset) return
    let alive = true
    listAssessments(user, inquiryId).then((r) => {
      if (!alive) return
      if (r.ok) {
        setItems(r.data)
        setError('')
      } else setError(r.error.code === 'FORBIDDEN' || r.error.code === 'INQUIRY_NOT_FOUND' ? '' : r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, inquiryId, preset])

  if (user?.serviceRole !== 'ADMIN') return null
  // 권한·없는 문의는 조용히 숨기고, 그 밖의 오류만 알린다
  if (items === null && !error) return null
  return (
    <div>
      <h4>AI 판단 이력</h4>
      {error && <div className="small muted">{error}</div>}
      {items && items.length === 0 && <div className="small muted">AI 판단 기록이 없어요.</div>}
      {items?.map((a, i) => {
        // 안전 거절·AI 실패로 기본값이 나간 판단은 AI 원래 판단(aiOutput)이 null 이다
        const ai = a.aiOutput
        const aiUrgency = ai?.urgencySuggested ?? a.urgency
        const conf = typeof ai?.confidence === 'number' ? ai.confidence : null
        // 추가 질문(ASK_MORE) 뒤에는 AI 가 더 물어본 항목을 화살표로 보여 준다. 다음 판단이 없으면 그 사실도 알린다
        const asked = a.action === 'ASK_MORE'
        const next = items[i + 1]
        return (
          <Fragment key={a.id}>
          <div className="asx">
            <div className="ash">
              <b>판단 {i + 1}</b>
              <small className="muted">{formatDateTime(a.createdAt)}</small>
            </div>
            <div>
              <div className="asl">문의 요약</div>
              <div className="asv">{a.facts.summary || '-'}</div>
            </div>
            <div className="asai">
              <div className="asl">AI 원래 판단</div>
              {ai ? (
                <div className="asv">
                  긴급도 <b>{urgencyText(aiUrgency)}</b>
                  {ai.categoryCode && ai.categoryCode !== a.categoryCode ? ` · 분류 ${catName(ai.categoryCode)}` : ''}
                  {conf !== null ? ` · 신뢰도 ${conf}` : ''}
                </div>
              ) : (
                <div className="asv small muted">AI 판단 없음 (안전 거절·AI 실패로 기본값 적용)</div>
              )}
            </div>
            {a.overrideReasons.length ? (
              <div className="aso">
                <div className="asl">규칙이 바꾼 내역</div>
                <ul>
                  {a.overrideReasons.map((o, j) => (
                    <li key={j}>
                      {FIELD_LABEL[o.field] ?? o.field} <s>{show(o.field, o.ai)}</s> → <b>{show(o.field, o.final)}</b> · {urgencyReasonText(o.reason)} <span className="mono small muted">{o.rule}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="aso none">
                <div className="asl">규칙이 바꾼 내역</div>
                <div className="small muted">없어요. AI 판단 그대로 적용했어요.</div>
              </div>
            )}
            <div className="asfin">
              <span className="asl">최종 적용</span>
              <StateBadge tone="prog" label={catName(a.categoryCode)} />
              {a.urgency && <StateBadge tone={pTone(a.urgency)} label={urgencyText(a.urgency)} />}
              {a.action && <StateBadge tone="recv" label={ACTION_LABEL[a.action] ?? a.action} />}
            </div>
          </div>
          {asked && (
            <div className="asc">
              <svg className="i" viewBox="0 0 20 20" aria-hidden="true">
                <path d="M10 3.5v12M5.5 11 10 15.5 14.5 11" />
              </svg>
              <span>
                <b>AI가 더 물어봤어요</b>
                {a.missingItems.length > 0 && ` · ${a.missingItems.map((m) => MISSING_LABEL[m] ?? m).join(', ')}`}
                {!next && ' · 이어진 판단이 없어요 (AI 응답이 실패했거나 아직 처리 중일 수 있어요)'}
              </span>
            </div>
          )}
          </Fragment>
        )
      })}
    </div>
  )
}
