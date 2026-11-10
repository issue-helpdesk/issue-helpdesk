/**
 * AI 운영 (관리자, /ai). (design/ITssue-Prototype.html viewAI)
 * 기간별 AI 상담 건수·AI 해결률·추정 비용·예산 사용을 본다.
 * 사용 현황은 OP-03을 사용하고, 모의 모드에서는 시연 데이터를 표시한다. 품질 평가 카드는 미노출.
 */
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { getAiUsage, type AiRange, type AiUsage } from '../../api/aiOps'
import titleOps from '../../assets/mascot/title-ops.webp'
import { USE_MOCK_OPS } from '../../core/config'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { CountUp } from '../../ui/CountUp'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'
import { CurveChart } from '../staff/StatsView'

const RANGES: { k: AiRange; label: string; hint: string; last: string }[] = [
  { k: 'day', label: '일', hint: '일별 (최근 14일)', last: '오늘' },
  { k: 'month', label: '월', hint: '월별 (최근 12개월)', last: '이번 달' },
  { k: 'year', label: '연도', hint: '연도별', last: '올해' },
]
const money = (c: number) => `$${c >= 100 ? Math.round(c) : c.toFixed(1)}`

export function AiOpsView() {
  const { user } = useAuth()
  const [range, setRange] = useState<AiRange>('day')
  const [usage, setUsage] = useState<AiUsage | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const admin = user?.serviceRole === 'ADMIN'

  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    getAiUsage(user, range).then((r) => {
      if (!alive) return
      if (r.ok) {
        setUsage(r.data)
        setError('')
      } else {
        setUsage(null)
        setError(r.error.message)
      }
    })
    return () => {
      alive = false
    }
  }, [user, admin, range, reload])


  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const cur = RANGES.find((x) => x.k === range)!
  const sum = usage?.sum
  const b = usage?.budget
  const pct = b ? Math.round((b.cost / b.budget) * 100) : 0

  return (
    <main className="main">
      <Topbar title="AI 운영" sub={USE_MOCK_OPS ? '사용량과 비용 · 시연 데이터' : '사용량과 비용'} lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div className="phead">
            <div className="eyebrow">AI OPERATIONS</div>
            <h1>AI 사용량과 비용을 살펴봐요</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              {USE_MOCK_OPS ? (
                <>
                  AI 상담과 모델 호출의 사용량·추정 비용을 확인해요. 현재 수치는 <b>시연 데이터</b>예요.
                </>
              ) : (
                <>
                  AI 상담과 모델 호출의 사용량·추정 비용을 확인해요. 집계는 서버 데이터를 기준으로 해요.
                </>
              )}
            </p>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div className="seg" role="group" aria-label="집계 기간">
              {RANGES.map((x) => {
                const dis = !USE_MOCK_OPS && x.k === 'year'
                return (
                  <button key={x.k} type="button" className={range === x.k ? 'on' : ''} aria-pressed={range === x.k} disabled={dis} title={dis ? '서버는 기간을 최대 1년까지 집계해요' : undefined} onClick={() => setRange(x.k)}>
                    {x.label}
                  </button>
                )
              })}
            </div>
            <span className="hint">{cur.hint}</span>
          </div>

          {error && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>
                {error}{' '}
                <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                  다시 시도
                </button>
              </div>
            </div>
          )}

          <div className="kpis">
            <div className="kpi">
              <div className="l">기간 내 AI 상담</div>
              <div className="v">
                <b>{sum ? <CountUp value={sum.tot} /> : '-'}</b>
                <span>건</span>
              </div>
            </div>
            <div className="kpi">
              <div className="l">AI 해결률</div>
              <div className="v">
                <b>{sum && sum.tot ? <CountUp value={Math.round((sum.ai / sum.tot) * 100)} delay={60} /> : '-'}</b>
                <span>%</span>
              </div>
            </div>
            <div className="kpi">
              <div className="l">추정 비용 (기간 합계)</div>
              <div className="v">
                <b>{sum ? <CountUp value={sum.cost} prefix="$" decimals={1} delay={120} /> : '-'}</b>
              </div>
            </div>
            <div className="kpi">
              <div className="l">{b?.scope === 'period' ? '기간 예산 사용' : `${cur.last} 예산 사용`}</div>
              <div className="v">
                <b>{b ? <CountUp value={pct} delay={180} /> : '-'}</b>
                <span>%</span>
              </div>
              {b && (
                <>
                  <div className={`bar ${pct > 90 ? 'urg' : ''}`} style={{ marginTop: 8 }}>
                    <i style={{ width: `${Math.min(100, pct)}%` }} />
                  </div>
                  <div className="d">
                    ${b.cost.toFixed(1)} / 예산 ${b.budget}
                  </div>
                </>
              )}
              {usage && !b && <div className="small muted" style={{ marginTop: 8 }}>설정된 예산이 없어요</div>}
              {b && <div className="small muted" style={{ marginTop: 8 }}>비용 비교를 위한 기준 금액이에요. 예산을 초과해도 AI 호출을 자동으로 차단하지는 않아요.</div>}
            </div>
          </div>

          <div className="panel">
            <h2>상담 건수와 비용</h2>
            {usage ? (
              <>
                <p className="small muted" style={{ margin: '0 0 6px' }}>
                  축 아래 숫자는 추정 비용(USD)
                  {usage.calls && ` · 모델 호출 ${usage.calls.callCount.toLocaleString()}건(실패 ${usage.calls.failedCount}건) · 평균 응답 ${usage.calls.avgLatencyMs === null ? '-' : `${(usage.calls.avgLatencyMs / 1000).toFixed(1)}초`}`}
                </p>
                <CurveChart
                  aria={`${cur.hint} 상담 건수와 AI 해결 곡선. 마지막 ${usage.labels[usage.labels.length - 1]} 전체 ${usage.tot[usage.tot.length - 1]}건, AI 해결 ${usage.ai[usage.ai.length - 1]}건, 추정 비용 ${money(usage.cost[usage.cost.length - 1])}`}
                  runKey={`${range}|${usage.sum.tot}`}
                  labels={usage.labels}
                  series={[
                    { name: '전체 상담', k: 'ca', dash: '', v: usage.tot },
                    { name: 'AI 해결', k: 'cc', dash: '', v: usage.ai },
                  ]}
                  foot={usage.cost.map(money)}
                  extra={usage.cost.map((c, i) => `추정 비용 ${money(c)} · 담당자·기타 ${usage.tot[i] - usage.ai[i]}건`)}
                  cols={[{ name: '추정 비용', v: usage.cost.map(money), zero: usage.cost.map((c) => c === 0) }]}
                  dimZero
                />
              </>
            ) : (
              <div className="empty" role="status">
                {error ? '불러오지 못했어요.' : '불러오는 중이에요…'}
              </div>
            )}
          </div>

        </div>
      </div>
    </main>
  )
}
