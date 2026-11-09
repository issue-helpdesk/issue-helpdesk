/**
 * AI 운영 (관리자, /ai). (design/ITssue-Prototype.html viewAI)
 * 기간별 AI 상담 건수·AI 해결률·추정 비용·예산 사용과, 테스트 질문으로 본 답변 품질(Golden Set)을 본다.
 * 사용 현황은 OP-03(명세 있음, 서버 구현 전에는 시연 데이터)이고, 답변 품질 평가는 서버 API 가 없어 항상 시연 데이터이다. (api/aiOps.ts, 요청 R-25·R-26)
 */
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { getAiUsage, listGoldenSet, type AiRange, type AiUsage, type GoldItem, type GoldStatus } from '../../api/aiOps'
import titleOps from '../../assets/mascot/title-ops.webp'
import { USE_MOCK_OPS } from '../../core/config'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { CountUp } from '../../ui/CountUp'
import { Icon } from '../../ui/Icon'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { CurveChart } from '../staff/StatsView'

const RANGES: { k: AiRange; label: string; hint: string; last: string }[] = [
  { k: 'day', label: '일', hint: '일별 (최근 14일)', last: '오늘' },
  { k: 'month', label: '월', hint: '월별 (최근 12개월)', last: '이번 달' },
  { k: 'year', label: '연도', hint: '연도별', last: '올해' },
]
const GOLD_AREA_TONE: Record<string, string> = { '가이드·답변': 'info', '외부 전송 제한': 'urg', '근거 부족': 'warn', '권한 안내': 'need', '긴급도 판단': 'prog', '과거 사례': 'recv', 분류: 'asg', 민감정보: 're' }
const GOLD_FILTERS = ['전체', '보완 필요', '검토 필요', '통과'] as const
const money = (c: number) => `$${c >= 100 ? Math.round(c) : c.toFixed(1)}`

export function AiOpsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [range, setRange] = useState<AiRange>('day')
  const [usage, setUsage] = useState<AiUsage | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [gold, setGold] = useState<GoldItem[] | null>(null)
  const [gf, setGf] = useState<(typeof GOLD_FILTERS)[number]>('전체')
  const [open, setOpen] = useState<string | null>(null)
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
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    listGoldenSet(user).then((r) => alive && r.ok && setGold(r.data))
    return () => {
      alive = false
    }
  }, [user, admin])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const cur = RANGES.find((x) => x.k === range)!
  const sum = usage?.sum
  const b = usage?.budget
  const pct = b ? Math.round((b.cost / b.budget) * 100) : 0
  const pass = gold?.filter((g) => g.st === '통과').length ?? 0
  const count = (s: GoldStatus) => gold?.filter((g) => g.st === s).length ?? 0
  const list = gold?.filter((g) => gf === '전체' || g.st === gf) ?? []

  return (
    <main className="main">
      <Topbar title="AI 운영" sub={USE_MOCK_OPS ? '비용과 품질 · 시연 데이터' : '비용과 품질'} lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div className="phead">
            <div className="eyebrow">AI OPERATIONS</div>
            <h1>AI 비용과 답변 품질을 살펴봐요</h1>
          </div>
          <div>
            <p className="muted">
              {USE_MOCK_OPS ? (
                <>
                  이 화면의 수치는 모두 <b>시연 데이터</b>예요. 실제 모델 호출은 없고, 상담이 AI 해결로 끝나면 오늘 건수가 늘어요.
                </>
              ) : (
                <>
                  AI 상담과 모델 호출 집계는 서버 값이에요. 답변 품질 평가(Golden Set)는 <b>시연 데이터</b>예요.
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
            </div>
          </div>

          <div className="panel">
            <h3>상담 건수와 비용</h3>
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

          <div className="panel">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <h3>
                답변 품질 평가 (Golden Set) <span className="tag gray">시연 데이터</span> <span className="tag gray">Could</span>
              </h3>
              <span className="small muted">
                기대와 일치 {pass} / {gold?.length ?? 0} · 보완 필요 {count('보완 필요')} · 검토 필요 {count('검토 필요')}
              </span>
            </div>
            <div className="row" style={{ margin: '12px 0' }}>
              {GOLD_FILTERS.map((f) => (
                <button key={f} type="button" className={`chip${gf === f ? ' on' : ''}`} aria-pressed={gf === f} onClick={() => setGf(f)}>
                  {f === '통과' ? '기대와 일치' : f}
                </button>
              ))}
            </div>
            <p className="small muted" style={{ margin: '0 0 4px' }}>
              테스트 질문에 AI가 실제로 답한 결과를 기대한 결과와 비교해요. <b>기대와 일치</b>는 같다는 뜻, <b>보완 필요</b>는 다르거나 근거가 틀린 경우, <b>검토 필요</b>는 일부만 맞아 사람이 확인해야 하는 경우예요.
            </p>
            <div className="ghd">
              <span>영역</span>
              <span>테스트 질문</span>
              <span className="c">결과</span>
              <span />
            </div>
            {list.map((g) => {
              const o = open === g.id
              return (
                <div key={g.id} className={`gold${o ? ' open' : ''}`}>
                  <button type="button" className="grow grw" aria-expanded={o} onClick={() => setOpen(o ? null : g.id)}>
                    <span className={`tag ga ga-${GOLD_AREA_TONE[g.area] ?? 'recv'}`}>{g.area}</span>
                    <b>{g.q}</b>
                    <span className="gst">
                      <StateBadge tone={g.st === '통과' ? 'ok' : g.st === '검토 필요' ? 'warn' : 'urg'} label={g.st === '통과' ? '기대와 일치' : g.st} />
                    </span>
                    <span className="chv" aria-hidden="true">
                      <Icon name="chevron" />
                    </span>
                  </button>
                  {o && (
                    <div className="gb">
                      <dl className="dl">
                        <dt>기대 결과</dt>
                        <dd>{g.exp}</dd>
                        <dt>실제 결과</dt>
                        <dd>{g.act}</dd>
                        {g.fix && (
                          <>
                            <dt>보완할 점</dt>
                            <dd>
                              <b>{g.fix}</b>
                            </dd>
                            <dt>담당</dt>
                            <dd>{g.owner}</dd>
                          </>
                        )}
                      </dl>
                      {g.fix && (
                        <div className="row">
                          <button type="button" className="btn sec sm" onClick={() => navigate(g.docCode ? `/guides?doc=${g.docCode}` : '/guides')}>
                            해당 가이드로 이동{g.docCode ? ` · ${g.docCode}` : ''}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </main>
  )
}
