/**
 * 가이드 관리 → 해결 사례 탭 (관리자). 주 1회 AI가 아직 가이드에 반영하지 않은 해결 사례를 분석해
 * 비슷한 사례를 묶어, 근거 티켓이 많은 순서로 제안한다. 서버에 연결된 환경에서는 서버의 묶음(api/caseClusters.ts, GC-01~05)을 보고,
 * 모의 환경에서는 시연 데이터와 모의 상태 전환으로 동작한다 (api/mock/caseGuides.ts).
 * 보기는 세 가지다: 검토 대상 / 가이드화 승인 / 반영 안함. 검토 필요인 카드의 "검토하기"는 오른쪽 검토 패널을 연다.
 * 승인한 카드는 등록한 버전의 본문과 처리 이력을 따로 볼 수 있고, 현행 전환은 가이드 목록에서 열람 범위를 확인하며 한다.
 * 패널은 화면 전체 틀(<main> 밖)에 열려야 해서 여는 동작만 받고 패널은 가이드 관리 화면이 그린다.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { CATEGORIES } from '../../api/catalog'
import { CASES_FROM_SERVER, getAllCases, getAnalysisStatus, getServerLoad, loadAnalysisStatus, loadCases, subscribeAllCases, subscribeServerCases } from '../../api/caseClusters'
import { retryGuideIngest } from '../../api/guides'
import { CASE_KIND_TONE, CASE_STATE_LABEL, CASE_STATE_TONE, baseChanged, kindLabel, retryCase, type CaseItem } from '../../api/mock/caseGuides'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { StateBadge } from '../../ui/StateBadge'
import { useToast } from '../../ui/useToast'

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

type View = 'review' | 'approved' | 'dropped'
const inView = (v: View, c: CaseItem) => (v === 'review' ? c.state === 'review' : v === 'dropped' ? c.state === 'dropped' : c.state !== 'review' && c.state !== 'dropped')

export function CaseGuideTab({ guide, onClearGuide, onReview, onVersion, onGoLive }: { guide?: { docCode: string; title: string } | null; onClearGuide?: () => void; onReview: (c: CaseItem) => void; onVersion: (c: CaseItem) => void; onGoLive: (c: CaseItem) => void }) {
  const cases = useSyncExternalStore(subscribeAllCases, getAllCases)
  const load = useSyncExternalStore(subscribeServerCases, getServerLoad)
  const status = useSyncExternalStore(subscribeServerCases, getAnalysisStatus)
  const { user } = useAuth()
  // 서버 연결 환경에서는 탭을 열 때마다 최신 목록을 다시 읽는다
  useEffect(() => {
    if (CASES_FROM_SERVER) {
      void loadCases()
      void loadAnalysisStatus()
    }
  }, [])
  const [view, setView] = useState<View>('review')
  const [kind, setKind] = useState('')
  const { say, fail } = useToast()
  const t = analysisTimes()
  const guideNotice = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (guide) guideNotice.current?.scrollIntoView?.({ block: 'nearest' })
  }, [guide])

  // 탭 건수와 목록에 같은 문서 조건을 적용해, 다른 가이드의 제안과 섞이지 않게 한다.
  const scoped = guide ? cases.filter((c) => c.target?.docCode === guide.docCode || c.registered?.docCode === guide.docCode) : cases
  const pool = scoped.filter((c) => inView(view, c))
  // 목록에는 상세 티켓이 없을 수 있어, 패널 조회 여부와 무관한 서버의 근거 건수로 정렬한다.
  const shown = pool.filter((c) => !kind || (kind === 'guide' ? c.kind === 'amend' || c.kind === 'new' : c.kind === kind)).sort((a, b) => b.ticketCount - a.ticketCount || a.topic.localeCompare(b.topic))
  const count = (v: View) => scoped.filter((c) => inView(v, c)).length
  const go = (v: View) => {
    setView(v)
  }

  return (
    <>
      <div className="alert info">
        <Icon name="file" />
        <div>
          {CASES_FROM_SERVER ? (
            <>AI가 주 1회, 아직 가이드에 반영하지 않은 해결 완료 사례를 분석해 비슷한 사례를 묶어 제안해요. 제안을 검토해 초안을 고친 뒤 승인하면 현행이 아닌 초안 버전으로 가이드 목록에 등록되고, 현행 전환은 검색 준비가 끝난 뒤 가이드 목록에서 직접 해요. 거절하거나, 가이드에 직접 반영했다면 반영했다고 표시할 수도 있어요.</>
          ) : (
            <>
              AI가 주 1회, 아직 가이드에 반영하지 않은 해결 완료 사례를 분석해 비슷한 사례를 묶어 제안해요. 승인하면 현행이 아닌 초안 버전으로 가이드 목록에 등록되고, 현행 전환은 검색 준비가 끝난 뒤 가이드 목록에서 직접 해요.{' '}
              <span className="tag gray">시연 데이터</span>
            </>
          )}
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'space-between', margin: '14px 0 10px', gap: 12 }}>
        <div className="row" style={{ gap: 8 }}>
          <div className="seg" role="group" aria-label="보기">
            <button type="button" className={view === 'review' ? 'on' : ''} aria-pressed={view === 'review'} onClick={() => go('review')}>
              검토 대상 <span className="count">{count('review')}</span>
            </button>
            <button type="button" className={view === 'approved' ? 'on' : ''} aria-pressed={view === 'approved'} onClick={() => go('approved')}>
              가이드화 승인 <span className="count">{count('approved')}</span>
            </button>
            <button type="button" className={view === 'dropped' ? 'on' : ''} aria-pressed={view === 'dropped'} onClick={() => go('dropped')}>
              반영 안함 <span className="count">{count('dropped')}</span>
            </button>
          </div>
          {/* 처리 상태를 바꿔도 제안 종류 조건은 유지해 승인·반영 안함 내역까지 이어서 확인한다. */}
          <FilterPill label="제안 종류" value={kind} options={[{ value: 'guide', label: '가이드 제안' }, { value: 'manual', label: '매뉴얼 후보' }, { value: 'sec', label: '보안 사고 사례' }]} onChange={setKind} />
        </div>
        {!CASES_FROM_SERVER && (
          <span className="small muted">
            이번 분석 결과 · 마지막 분석 {t.last} · 다음 분석 {t.next}
          </span>
        )}
        {CASES_FROM_SERVER && status && (
          <span className="small muted">
            마지막 분석 {status.lastAnalyzedAt ? fmt(new Date(status.lastAnalyzedAt)) : '아직 없음'} · 다음 분석 {fmt(new Date(status.nextAnalysisAt))}
            {status.lastRunStatus === 'FAILED' && <span style={{ color: 'var(--s-urg-fg)' }}> · 가장 최근 분석이 실패했어요</span>}
          </span>
        )}
      </div>

      {guide && (
        <div className="alert guide-scope" ref={guideNotice} role="status" aria-label="가이드별 제안">
          <Icon name="file" />
          <div>
            <b><span className="mono">{guide.docCode}</span> {guide.title}</b>
            <p style={{ margin: '4px 0 8px' }}>이 가이드에 해당하는 제안만 보고 있어요.</p>
            <button type="button" className="btn sec sm" onClick={onClearGuide}>전체 제안 보기</button>
          </div>
        </div>
      )}

      {CASES_FROM_SERVER && load.error && (
        <div className="alert err" role="alert">
          <Icon name="alert" />
          <div>
            {load.error}{' '}
            <button type="button" className="btn ghost sm" onClick={() => void loadCases()}>
              다시 시도
            </button>
          </div>
        </div>
      )}

      {CASES_FROM_SERVER && !load.loaded && !load.error ? (
        <div className="empty" role="status">
          불러오는 중이에요…
        </div>
      ) : shown.length === 0 ? (
        <div className="panel">
          <div className="empty">{view === 'review' ? '검토할 제안이 없어요.' : view === 'approved' ? '아직 가이드화를 승인한 건이 없어요.' : '반영하지 않은 건이 없어요.'}</div>
        </div>
      ) : (
        <div className="cgl">
          {shown.map((c) => {
            const changed = baseChanged(c) && c.state === 'review'
            return (
              <section key={c.id} className={`panel cgc${c.state === 'review' ? ' cgc-review' : ''}`} aria-label={c.topic}>
                <div className="cgh">
                  <span className={`tag c-${c.cat}`}>{CATEGORIES[c.cat].name}</span>
                  <b className="cgt">{c.kind === 'new' ? c.title || c.topic : c.topic}</b>
                  <StateBadge tone={CASE_STATE_TONE[c.state]} label={CASE_STATE_LABEL[c.state]} />
                </div>
                <div className="cgm small">
                  <span>
                    근거 티켓 <b>{c.ticketCount}건</b>
                  </span>
                  <StateBadge tone={CASE_KIND_TONE[c.kind]} label={kindLabel(c)} />
                  {c.target && (
                    <span className="muted">
                      {c.target.docCode} {c.target.title}
                      {c.target.baseVersion && ` · 기준 ${c.target.baseVersion}`}
                      {c.target.section && ` · ${c.target.section}`}
                    </span>
                  )}
                  {c.kind === 'new' && <span className="muted">새 가이드로 작성</span>}
                </div>
                {c.kind === 'amend' && c.change && <div className="cgx small muted">추가·수정할 내용: {c.change}</div>}
                {changed && c.target && (
                  <div className="cgx small" style={{ color: 'var(--s-warn-fg)' }}>
                    {c.target.baseVersion && c.target.latestVersion ? `기준 가이드가 ${c.target.baseVersion}에서 ${c.target.latestVersion}로 변경됐어요.` : '제안을 만든 뒤 기준 가이드가 바뀌었어요.'} 최신 내용과 비교한 뒤 다시 검토해 주세요.
                  </div>
                )}
                {c.registered && c.state !== 'dropped' && (
                  <div className="cgx small muted">
                    등록: {c.registered.docCode} {c.registered.version}
                    {c.state === 'live' ? ' (현행)' : ' (현행 아님)'}
                  </div>
                )}
                {c.state === 'failed' && <div className="cgx small" style={{ color: 'var(--s-urg-fg)' }}>{c.failReason}</div>}
                {c.state === 'dropped' && c.dropReason && <div className="cgx small muted">사유: {c.dropReason}</div>}
                <div className="cga">
                  {c.state === 'review' && (
                    <button type="button" className="btn pri sm" onClick={() => onReview(c)}>
                      검토하기
                    </button>
                  )}
                  {c.state === 'failed' && (
                    <button
                      type="button"
                      className="btn pri sm"
                      onClick={async () => {
                        if (CASES_FROM_SERVER) {
                          if (!user || !c.registered) return
                          const r = await retryGuideIngest(user, c.registered.docId, c.registered.versionId)
                          if (!r.ok) return fail(r.error.message)
                          void loadCases()
                          return say('같은 버전으로 검색 준비를 다시 시작해요.')
                        }
                        const r = retryCase(c.id)
                        if (!r.ok) return fail(r.message)
                        say('같은 버전으로 검색 준비를 다시 시작해요.')
                      }}
                    >
                      검색 준비 다시 시도
                    </button>
                  )}
                  {c.state === 'ready' && (
                    <button type="button" className="btn pri sm" onClick={() => onGoLive(c)}>
                      현행으로 전환
                    </button>
                  )}
                  {c.registered && c.state !== 'dropped' && (
                    <button type="button" className="btn sec sm" onClick={() => onVersion(c)}>
                      등록 버전 보기
                    </button>
                  )}
                  {c.state !== 'review' && (
                    <button type="button" className="btn ghost sm" onClick={() => onReview(c)}>
                      처리 이력 상세 보기
                    </button>
                  )}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </>
  )
}
