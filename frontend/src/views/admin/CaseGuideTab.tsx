/**
 * 가이드 관리 → 해결 사례 → 가이드 초안 탭 (관리자). 주 1회 AI가 아직 가이드에 반영하지 않은 해결 사례를 분석해
 * 비슷한 사례를 묶어, 근거 티켓이 많은 순서로 제안한다. 서버 없이 시연 데이터와 모의 상태 전환으로만 동작한다 (api/mock/caseGuides.ts, R-23).
 * 검토 중인 제안과 이미 승인·처리한 제안을 나눠 보고, 카드의 "검토하기"는 오른쪽 검토 패널을 연다.
 */
import { useState, useSyncExternalStore } from 'react'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { CASE_KIND_LABEL, CASE_STATE_LABEL, CASE_STATE_TONE, baseChanged, getCases, retryCase, goLiveCase, subscribeCases, type CaseItem } from '../../api/mock/caseGuides'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { StateBadge } from '../../ui/StateBadge'
import { useToast } from '../../ui/useToast'
import type { CaseFocus } from './CaseReviewPanel'

const DOW = ['일', '월', '화', '수', '목', '금', '토']
const fmt = (d: Date) => `${d.getMonth() + 1}월 ${d.getDate()}일(${DOW[d.getDay()]}) 00:00`
/** 시연 시각: 가장 가까운 지난 월요일 00:00 이 마지막 분석, 7일 뒤가 다음 분석 */
function analysisTimes() {
  const last = new Date()
  last.setHours(0, 0, 0, 0)
  last.setDate(last.getDate() - ((last.getDay() + 6) % 7))
  const next = new Date(last)
  next.setDate(next.getDate() + 7)
  return { last: fmt(last), next: fmt(next) }
}

type View = 'review' | 'done'

/** 검토 패널은 화면 전체 틀(<main> 밖)에 열려야 하므로 여는 동작만 받고, 패널은 가이드 관리 화면이 그린다 */
export function CaseGuideTab({ onOpen }: { onOpen: (id: string, focus: CaseFocus) => void }) {
  const cases = useSyncExternalStore(subscribeCases, getCases)
  const [view, setView] = useState<View>('review')
  const [cat, setCat] = useState('')
  const setPanel = (p: { id: string; focus: CaseFocus }) => onOpen(p.id, p.focus)
  const { say, fail } = useToast()
  const t = analysisTimes()

  const inView = (c: CaseItem) => (view === 'review' ? c.state === 'review' : c.state !== 'review')
  const pool = cases.filter(inView)
  const cats = (Object.keys(CATEGORIES) as CategoryCode[]).filter((k) => pool.some((c) => c.cat === k))
  const shown = pool.filter((c) => !cat || c.cat === cat).sort((a, b) => b.tickets.length - a.tickets.length || a.topic.localeCompare(b.topic))
  const reviewN = cases.filter((c) => c.state === 'review').length

  return (
    <>
      <div className="alert info">
        <Icon name="file" />
        <div>
          AI가 주 1회, 아직 가이드에 반영하지 않은 해결 완료 사례를 분석해 비슷한 사례를 묶어 제안해요. 승인하면 현행이 아닌 초안 버전으로 등록되고, 현행 전환은 검색 준비가 끝난 뒤 직접 해요.{' '}
          <span className="tag gray">시연 데이터</span>
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'space-between', margin: '14px 0 10px', gap: 12 }}>
        <div className="row" style={{ gap: 8 }}>
          <div className="seg" role="group" aria-label="보기">
            <button type="button" className={view === 'review' ? 'on' : ''} aria-pressed={view === 'review'} onClick={() => { setView('review'); setCat('') }}>
              검토 대상 <span className="count">{reviewN}</span>
            </button>
            <button type="button" className={view === 'done' ? 'on' : ''} aria-pressed={view === 'done'} onClick={() => { setView('done'); setCat('') }}>
              승인·처리한 건 <span className="count">{cases.length - reviewN}</span>
            </button>
          </div>
          <FilterPill label="분류" value={cat} options={cats.map((k) => ({ value: k, label: CATEGORIES[k].name }))} onChange={setCat} />
        </div>
        <span className="small muted">
          이번 분석 결과 · 마지막 분석 {t.last} · 다음 분석 {t.next}
        </span>
      </div>

      {shown.length === 0 ? (
        <div className="panel">
          <div className="empty">{view === 'review' ? '검토할 제안이 없어요.' : '아직 승인하거나 처리한 건이 없어요.'}</div>
        </div>
      ) : (
        <div className="cgl">
          {shown.map((c) => {
            const changed = baseChanged(c) && (c.state === 'review' || c.state === 'ready')
            return (
              <section key={c.id} className="panel cgc" aria-label={c.topic}>
                <div className="cgh">
                  <span className={`tag c-${c.cat}`}>{CATEGORIES[c.cat].name}</span>
                  <b className="cgt">{c.kind === 'new' ? c.title || c.topic : c.topic}</b>
                  <StateBadge tone={CASE_STATE_TONE[c.state]} label={CASE_STATE_LABEL[c.state]} />
                </div>
                <div className="cgm small">
                  <span>
                    근거 티켓 <b>{c.tickets.length}건</b>
                  </span>
                  <span className="cgk">{CASE_KIND_LABEL[c.kind]}</span>
                  {c.target && (
                    <span className="muted">
                      {c.target.docCode} {c.target.title} · 기준 {c.target.baseVersion} · {c.target.section}
                    </span>
                  )}
                  {c.kind === 'new' && <span className="muted">새 가이드로 작성</span>}
                </div>
                {c.kind === 'amend' && c.change && <div className="cgx small muted">추가·수정할 내용: {c.change}</div>}
                {changed && c.target && (
                  <div className="cgx small" style={{ color: 'var(--s-warn-fg)' }}>
                    기준 가이드가 {c.target.baseVersion}에서 {c.target.latestVersion}로 변경됐어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.
                  </div>
                )}
                {c.registered && c.state !== 'review' && c.state !== 'dropped' && (
                  <div className="cgx small muted">
                    등록: {c.registered.docCode} {c.registered.version}
                    {c.state === 'live' ? ' (현행)' : ' (현행 아님)'}
                  </div>
                )}
                {c.state === 'failed' && <div className="cgx small" style={{ color: 'var(--s-urg-fg)' }}>{c.failReason}</div>}
                {c.state === 'dropped' && <div className="cgx small muted">사유: {c.dropReason}</div>}
                <div className="cga">
                  {c.state === 'review' && (
                    <button type="button" className="btn pri sm" onClick={() => setPanel({ id: c.id, focus: 'review' })}>
                      검토하기
                    </button>
                  )}
                  {c.state === 'failed' && (
                    <button
                      type="button"
                      className="btn pri sm"
                      onClick={() => {
                        const r = retryCase(c.id)
                        if (!r.ok) return fail(r.message)
                        say('같은 버전으로 검색 준비를 다시 시작해요.')
                      }}
                    >
                      검색 준비 다시 시도
                    </button>
                  )}
                  {c.state === 'ready' && (
                    <>
                      <button type="button" className="btn sec sm" onClick={() => setPanel({ id: c.id, focus: 'content' })}>
                        등록 버전 보기
                      </button>
                      <button
                        type="button"
                        className="btn pri sm"
                        disabled={changed}
                        title={changed ? '기준 가이드가 바뀌어서 현행으로 바꿀 수 없어요.' : undefined}
                        onClick={() => {
                          const r = goLiveCase(c.id)
                          if (!r.ok) return fail(r.message)
                          say('현행으로 바꿨어요. 이제 사용자 답변에 쓰여요.')
                        }}
                      >
                        현행으로 전환
                      </button>
                    </>
                  )}
                  {(c.state === 'preparing' || c.state === 'live' || c.state === 'dropped' || c.state === 'failed') && (
                    <button type="button" className="btn sec sm" onClick={() => setPanel({ id: c.id, focus: 'content' })}>
                      {c.state === 'dropped' ? '내용 보기' : '등록 내용 보기'}
                    </button>
                  )}
                  <button type="button" className="btn ghost sm" onClick={() => setPanel({ id: c.id, focus: 'tickets' })}>
                    근거 티켓 보기
                  </button>
                </div>
              </section>
            )
          })}
        </div>
      )}
    </>
  )
}
