/**
 * AI 판단 이력 (관리자 전용, 접수 상세 패널). 위에서 아래로: 문의 요약 → AI 원래 판단(보라 박스) → 규칙이 바꾼 내역 → 최종 적용.
 * 서버(IQ-10)가 준 JSON 은 모양이 바뀌어도 화면이 깨지지 않게 있는 값만 보여 준다. (design/ITssue-Prototype.html assessHtml)
 */
import { useEffect, useState } from 'react'
import { ACTION_LABEL, FIELD_LABEL, listAssessments, type Assessment } from '../../api/assessments'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
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
  return s
}

export function AssessmentHistory({ inquiryId }: { inquiryId: number }) {
  const { user } = useAuth()
  const [items, setItems] = useState<Assessment[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
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
  }, [user, inquiryId])

  if (user?.serviceRole !== 'ADMIN') return null
  // 권한·없는 문의는 조용히 숨기고, 그 밖의 오류만 알린다
  if (items === null && !error) return null
  return (
    <div>
      <h4>AI 판단 이력</h4>
      {error && <div className="small muted">{error}</div>}
      {items && items.length === 0 && <div className="small muted">AI 판단 기록이 없어요.</div>}
      {items?.map((a, i) => {
        const aiUrgency = a.aiOutput.urgencySuggested ?? a.urgency
        const conf = typeof a.aiOutput.confidence === 'number' ? a.aiOutput.confidence : null
        return (
          <div className="asx" key={a.id}>
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
              <div className="asv">
                긴급도 <b>{aiUrgency ?? '-'}</b>
                {a.aiOutput.categoryCode && a.aiOutput.categoryCode !== a.categoryCode ? ` · 분류 ${catName(a.aiOutput.categoryCode)}` : ''}
                {conf !== null ? ` · 신뢰도 ${conf}` : ''}
              </div>
            </div>
            {a.overrideReasons.length ? (
              <div className="aso">
                <div className="asl">규칙이 바꾼 내역</div>
                <ul>
                  {a.overrideReasons.map((o, j) => (
                    <li key={j}>
                      {FIELD_LABEL[o.field] ?? o.field} <s>{show(o.field, o.ai)}</s> → <b>{show(o.field, o.final)}</b> · {o.reason} <span className="mono small muted">{o.rule}</span>
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
              {a.urgency && <StateBadge tone={pTone(a.urgency)} label={a.urgency} />}
              {a.action && <StateBadge tone="recv" label={ACTION_LABEL[a.action] ?? a.action} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
