/**
 * AI 처리 상세 패널 (관리자, 전체 문의 → AI 처리). 티켓이 없는 AI 상담 한 건의 제목·요약·AI 판단 이력·사용한 가이드를 오른쪽에 연다.
 * 접수 상세 패널(TicketDetailPanel)과 같은 자리·모양이고, 판단 이력은 접수 상세에서 쓰는 AssessmentHistory 를 그대로 쓴다.
 * 다른 행을 누르면 패널을 닫았다 열지 않고 안의 내용만 바뀐다. 대화 원문은 보여 주지 않는다.
 * 데이터: 제목·구분·분류·문의자는 목록 행, 판단 이력은 GET /inquiries/{id}/assessments, 사용한 가이드는 GET /inquiries/{id}/messages 의 출처.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { CATEGORIES } from '../../api/catalog'
import { USE_MOCK_INQUIRY } from '../../core/config'
import { listUsedGuides, type UsedGuide } from '../../api/inquirySources'
import type { AiRow } from '../../api/inquiries'
import { mockJudgments } from '../../api/mock/aiRows'
import { Icon } from '../../ui/Icon'
import { StateBadge } from '../../ui/StateBadge'
import { AssessmentHistory } from '../staff/AssessmentHistory'

/** 목록과 같은 구분 배지 */
export function AiKindBadge({ kind }: { kind: AiRow['kind'] }) {
  if (kind === 'pend') return <StateBadge tone="need" label="해결 확인 대기" sub="AI 안내" block />
  if (kind === 'unr') return <StateBadge tone="warn" label="미연결 종료" />
  return <StateBadge tone="ok" label="AI 해결" />
}

export function AiDetailPanel({ row, slide, onSlideEnd, onClose }: { row: AiRow; slide: boolean; onSlideEnd: () => void; onClose: () => void }) {
  // 열릴 때 밀려 들어오고, 닫을 때 밀려 나간 뒤에 실제로 닫는다 (움직임 줄이기 설정이면 바로 닫는다)
  const [slid, setSlid] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeBtn.current?.focus({ preventScroll: true })
  }, [])
  const finish = () => {
    const el = opener.current
    onClose()
    if (el && el !== document.body) setTimeout(() => el.isConnected && el.focus({ preventScroll: true }), 0)
  }
  const close = () => {
    if (leaving) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) finish()
    else setLeaving(true)
  }
  useEffect(() => {
    if (!leaving) return
    const t = setTimeout(finish, 400)
    return () => clearTimeout(t)
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.querySelector('[role="dialog"]')) close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  // 사용한 가이드: 행이 바뀌면 다시 읽는다 (그동안 이전 내용을 두지 않는다)
  const [guides, setGuides] = useState<UsedGuide[] | null>(null)
  const [guideErr, setGuideErr] = useState(false)
  useEffect(() => {
    let alive = true
    setGuides(null)
    setGuideErr(false)
    listUsedGuides(row.inquiryId, row.guide).then((r) => {
      if (!alive) return
      if (r.ok) setGuides(r.data)
      else setGuideErr(true)
    })
    return () => {
      alive = false
    }
  }, [row.id, row.inquiryId, row.guide])

  return (
    <aside
      className={`detail${slide && !slid && !leaving ? ' slide' : ''}${leaving ? ' leave' : ''}`}
      role="complementary"
      aria-label="AI 처리 상세"
      onAnimationEnd={() => {
        if (leaving) finish()
        else {
          setSlid(true)
          onSlideEnd()
        }
      }}
    >
      <div className="dh">
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <div style={{ minWidth: 0 }}>
            <div className="mono small muted">{row.id}</div>
            <h3>{row.title}</h3>
          </div>
          <span style={{ flex: 1 }} />
          <button type="button" ref={closeBtn} className="btn sec sm ico" aria-label="닫기" onClick={close}>
            <Icon name="x" />
          </button>
        </div>
      </div>
      <div className="db">
        <div>
          <dl className="dl" style={{ marginTop: 0 }}>
            <dt>구분</dt>
            <dd>
              <AiKindBadge kind={row.kind} />
            </dd>
            <dt>분류</dt>
            <dd>{row.categoryCode ? <span className={`tag c-${row.categoryCode}`}>{CATEGORIES[row.categoryCode].name}</span> : <span className="muted">미분류</span>}</dd>
            {row.user && (
              <>
                <dt>문의자</dt>
                <dd>{row.user}</dd>
              </>
            )}
            <dt>시점</dt>
            <dd>{row.when}</dd>
          </dl>
        </div>
        {/* 같은 문의에서 패널 안만 바뀌도록 key 로 판단 이력을 다시 읽는다 */}
        {USE_MOCK_INQUIRY ? <AssessmentHistory key={row.id} inquiryId={row.inquiryId ?? 0} preset={mockJudgments(row)} /> : row.inquiryId !== null && <AssessmentHistory key={row.id} inquiryId={row.inquiryId} />}
        {/* 다른 행을 누르면 펼침도 처음으로 */}
        <UsedSources key={`used-${row.id}`} guides={guides} failed={guideErr} />
      </div>
    </aside>
  )
}

/**
 * 사용한 가이드와 참고한 과거 처리 사례. 서버는 과거 처리 사례를 문서 코드 없이 본문(excerpt)만 주므로,
 * 가이드와 묶음을 나누고 사례는 누르면 아래에 본문을 짧게 펼쳐 보인다 (한 번에 하나).
 */
function UsedSources({ guides, failed }: { guides: UsedGuide[] | null; failed: boolean }) {
  const uid = useId()
  const [open, setOpen] = useState<number | null>(null)
  const docs = guides?.filter((g) => g.kind !== 'LEGACY') ?? []
  const cases = guides?.filter((g) => g.kind === 'LEGACY') ?? []
  return (
    <>
      <div>
        <h4>사용한 가이드</h4>
        {failed ? (
          <div className="small muted" style={{ marginTop: 8 }}>
            사용한 가이드를 불러오지 못했어요.
          </div>
        ) : guides === null ? (
          <div className="small muted" role="status" style={{ marginTop: 8 }}>
            불러오는 중이에요…
          </div>
        ) : docs.length === 0 ? (
          <div className="small muted" style={{ marginTop: 8 }}>
            {cases.length ? '사용한 가이드가 없어요. 아래 과거 처리 사례만 참고했어요.' : '사용한 가이드가 없어요. 근거가 될 문서를 찾지 못했거나 차단되어 AI가 답하지 못했을 수 있어요.'}
          </div>
        ) : (
          docs.map((g, i) => (
            <span className="src" key={i} style={{ cursor: 'default' }}>
              <Icon name="file" size={16} />
              {[g.docCode, g.version].filter(Boolean).join(' ')}
              {g.location ? ` · ${g.location}` : ''}
            </span>
          ))
        )}
      </div>
      {cases.length > 0 && (
        <div>
          <h4>참고한 과거 처리 사례</h4>
          <div style={{ marginTop: 8 }}>
            {cases.map((_, i) => (
              <button key={i} type="button" className="src" aria-expanded={open === i} aria-controls={`${uid}-case`} onClick={() => setOpen(open === i ? null : i)}>
                과거 사례 {i + 1}
              </button>
            ))}
          </div>
          {open !== null && (
            <div id={`${uid}-case`} className="small" role="region" aria-label={`과거 사례 ${open + 1} 본문`} style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '8px 10px', marginTop: 6, whiteSpace: 'pre-wrap' }}>
              {cases[open].excerpt?.trim() || '본문이 없어요.'}
            </div>
          )}
        </div>
      )}
    </>
  )
}
