/**
 * 관리자 통계 (/stats). (design/ITssue-Prototype.html viewStatsAdmin)
 * 티켓(담당자 처리)과 AI 상담 결과를 구분해서 보여 준다: AI 상담 결과, 담당자 처리 현황, 접수 추이, 팀별 진행도(팀원별 카드), 긴급도 분포.
 * 구역마다 따로 불러오고(불러오는 중 · 실패 · 다시 시도) 한 구역이 실패해도 다른 구역은 그대로 보인다. 담당자 통계(StatsView)의 부품을 함께 쓴다.
 * 값은 서버 운영 집계(OP-01)와 문의 목록(IQ-02)이다. 서버 집계는 선택 기간(접수한 날 기준)의 티켓을 센다. 모의 모드는 접수 목록으로 같은 모양의 값을 만든다.
 * 분류별 진행도와 개인별 분류 분포는 서버 집계에 분류별 상태 건수가 없어 두지 않는다. (요청 R-01)
 */
import { useCallback, useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { getAdminStatsSource, type AdminStatKey, type StatCounts, type StatsOverview } from '../../api/adminStats'
import type { AiPage } from '../../api/inquiries'
import { watchTickets } from '../../api/tickets'
import titleOps from '../../assets/mascot/title-ops.webp'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Collapse } from '../../ui/Collapse'
import { CountUp } from '../../ui/CountUp'
import { Icon } from '../../ui/Icon'
import { StatSr, useStatTip } from '../../ui/StatTip'
import { Topbar } from '../../ui/Topbar'
import { UrgencyChip } from '../staff/QueueView'
import { CurveChart, PERN, PRI_RULE, STATES, Section, TREND_NOTE, UDEF, UL, UNITS, URGS, sumOf, useSection, type Per, type Unit } from '../staff/StatsView'
import { MemberCards } from './MemberCards'
import { loadOverview } from './statsOverview'

type Counts = AiPage['counts']

const ZERO: StatCounts = { RDY: 0, WIP: 0, FIN: 0, CLS: 0 }

function Kpi({ label, n, to, dot, cls, hint, sug, aria }: { label: string; n: number; to?: string; dot?: string; cls?: string; hint?: string; sug?: boolean; aria?: string }) {
  const navigate = useNavigate()
  const body = (
    <>
      <div className="l">
        {dot && <i className="dt" style={{ background: dot }} />}
        {label}
        {sug && (
          <>
            {' '}
            <span className="tag gray">제안</span>
          </>
        )}
      </div>
      <div className="v">
        <b>
          <CountUp value={n} />
        </b>
        <span>건</span>
      </div>
      {hint && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {hint}
        </div>
      )}
    </>
  )
  return to ? (
    <button type="button" className={`kpi kl${cls ? ` ${cls}` : ''}`} onClick={() => navigate(to)} aria-label={aria ?? `${label} ${n}건`}>
      {body}
      <Icon name="chevron" className="go" />
    </button>
  ) : (
    <div className={`kpi${cls ? ` ${cls}` : ''}`}>{body}</div>
  )
}

/** 상태별 쌓인 막대 한 줄 (팀). 마우스를 올리면 상태별 건수가 보인다 */
function StackRow({ label, sub, v, mx, sel, onClick, tip }: { label: string; sub?: string; v: StatCounts; mx: number; sel?: boolean; onClick: () => void; tip: ReturnType<typeof useStatTip> }) {
  const t = sumOf(v)
  return (
    <button type="button" className={`srow${sel ? ' sel' : ''}`} aria-pressed={!!sel} onClick={onClick} {...tip.bind(label, v)}>
      <div className="sl">
        <b>{label}</b>
        {sub && <small>{sub}</small>}
      </div>
      <div className="sbar" role="img" aria-label={STATES.map((s) => `${s.short} ${v[s.k]}`).join(', ')}>
        {t ? STATES.map((s) => (v[s.k] ? <div key={s.k} style={{ width: `${(v[s.k] / mx) * 100}%`, background: s.color }} /> : null)) : <div style={{ width: 3, background: 'var(--line)' }} />}
      </div>
      <div className="sn">
        <b>{t}</b>
        <small>{t ? `완료 ${Math.round((v.CLS / t) * 100)}%` : '-'}</small>
      </div>
      <StatSr v={v} />
    </button>
  )
}

const Legend = () => (
  <div className="lgd" style={{ margin: '12px 0 0' }}>
    {STATES.map((s) => (
      <span key={s.k}>
        <i style={{ background: s.color }} />
        {s.short}
      </span>
    ))}
  </div>
)

export function AdminStatsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [per, setPer] = useState<Per>('m')
  const [unit, setUnit] = useState<Unit>(UDEF.m)
  const [sel, setSel] = useState<string | null>(null)
  const [member, setMember] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  // watchTickets 는 구독하자마자 한 번 알리므로 처음 알림은 건너뛴다
  useEffect(() => {
    let first = true
    return watchTickets(() => {
      if (first) first = false
      else setTick((n) => n + 1)
    })
  }, [])

  const admin = user?.serviceRole === 'ADMIN'
  const unitNow = UNITS[per].includes(unit) ? unit : UDEF[per]
  const loadAi = useCallback((u: NonNullable<typeof user>) => getAdminStatsSource(u, 'ai' as AdminStatKey, per), [per])
  // 요약·진행도·긴급도는 기간만 바뀌면 다시 읽고, 추이는 집계 단위까지 바뀌면 다시 읽는다 (단위를 바꿔도 다른 구역은 그대로)
  const loadMain = useCallback((u: NonNullable<typeof user>) => loadOverview(u, per, 'd'), [per])
  const loadTrend = useCallback((u: NonNullable<typeof user>) => loadOverview(u, per, unitNow), [per, unitNow])

  const ai = useSection('ai', per, tick, loadAi)
  const main = useSection('ov', per, tick, loadMain)
  const trend = useSection('ovt', `${per}|${unitNow}`, tick, loadTrend)
  const tip = useStatTip()

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const counts = ai.extra as Counts | undefined
  const ov = main.extra as StatsOverview | undefined
  const tr = trend.extra as StatsOverview | undefined
  const v = ov?.states ?? ZERO
  const none = ov?.none ?? 0
  const total = sumOf(v)
  const b = per === 'd' ? null : (tr?.trend ?? null)
  const urgN = URGS.map((p) => ov?.urgency[p] ?? 0)
  const urgMx = Math.max(1, ...urgN)
  const q = `per=${per}`
  const pickPer = (p: Per) => {
    setPer(p)
    setUnit(UDEF[p])
    setSel(null)
    setMember(null)
  }

  const groups = ov?.groups ?? []
  const rowMx = Math.max(1, ...groups.map((g) => sumOf(g.v)))

  const nested = () => {
    const g = groups.find((x) => x.name === sel)
    if (!g) return null
    return (
      <div className="nest">
        <div className="nh">
          <b>{g.name} · 구성원별 진행도</b>
          <span className="small muted">집계 기준 {main.at}</span>
          <button type="button" className="btn ghost sm" onClick={main.reload}>
            <Icon name="refresh" /> 새로고침
          </button>
        </div>
        <MemberCards members={g.members} open={member} onOpen={setMember} onList={(name) => navigate(`/tickets?staff=${encodeURIComponent(name)}&${q}`)} />
        <div className="hint" style={{ marginTop: 6 }}>
          카드에 마우스를 올리면 상태별 건수를, 누르면 카드가 넓어지며 자세히 보여요. 업무량 확인용이며 평가 순위가 아니에요.
        </div>
      </div>
    )
  }

  return (
    <div className="stx">
      <main className="main">
        <Topbar title="통계" sub="티켓과 AI 해결을 구분해서 보여줘요" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">STATISTICS</div>
              <h1>통계</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                기간을 고르고 추이·분포·진행도를 살펴봐요. 지금 확인할 일은 대시보드에서 봐요.
              </p>
            </div>

            <div className="sbar2">
              <div className="sg">
                <span className="small muted" id="pl">
                  조회 기간
                </span>
                <div className="seg" role="group" aria-labelledby="pl">
                  {(['d', 'm', 'y'] as Per[]).map((p) => (
                    <button key={p} type="button" className={per === p ? 'on' : ''} aria-pressed={per === p} onClick={() => pickPer(p)}>
                      {PERN[p]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="sg unit">
                <span className="small muted" id="ul">
                  집계 단위
                </span>
                <div className="seg" role="group" aria-labelledby="ul">
                  {(['d', 'w', 'mo'] as Unit[]).map((u) => {
                    const dis = !UNITS[per].includes(u)
                    return (
                      <button key={u} type="button" className={unitNow === u && !dis ? 'on' : ''} aria-pressed={unitNow === u && !dis} disabled={dis} onClick={() => setUnit(u)}>
                        {UL[u]}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>

            <Section title="AI 상담 결과" kind="ai" sec={ai} note="티켓이 만들어지지 않은 문의 · 문의를 시작한 날 기준이에요.">
              <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))' }}>
                <Kpi label="AI 해결" n={counts?.ok ?? 0} to={`/tickets?mode=ai&aik=ok&${q}`} aria={`AI 해결 ${counts?.ok ?? 0}건. AI 해결 목록 보기`} hint="AI 답변으로 해결된 문의" />
                <Kpi label="해결 확인 대기 (AI 답변 후)" n={counts?.pend ?? 0} sug to={`/tickets?mode=ai&aik=pend&${q}`} aria={`해결 확인 대기 ${counts?.pend ?? 0}건. 해당 목록 보기`} hint="미확인 · 해결·미해결을 아직 고르지 않았어요" />
                <Kpi label="미연결 종료" n={counts?.unr ?? 0} sug to={`/tickets?mode=ai&aik=unr&${q}`} aria={`미연결 종료 ${counts?.unr ?? 0}건. 해당 목록 보기`} hint="해결되지 않고 끝난 문의 (접수하지 않고 끝낸 문의 포함)" />
              </div>
              <p className="small muted secnote">담당자 처리(티켓)와는 따로 세요. AI 해결과 해결 완료(CLS)는 합치지 않아요.</p>
            </Section>

            <Section title="담당자 처리 (티켓)" kind="tk" sec={main} note="티켓이 만들어진 접수 · 접수한 날 기준이에요.">
              <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))' }}>
                <Kpi label="담당자 처리 접수" n={ov?.total ?? 0} to={`/tickets?${q}`} aria={`담당자 처리 접수 ${ov?.total ?? 0}건. 전체 문의 목록 보기`} hint="선택 기간에 접수된 티켓" />
              </div>
              <div className="small" style={{ fontWeight: 700, margin: '14px 0 2px' }}>
                접수 후 현재 상태
              </div>
              <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))' }}>
                <Kpi label="배정 전" n={none} dot="var(--s-urg-dot)" cls="urg" sug to={`/tickets?st=none&${q}`} aria={`배정 전 ${none}건. 해당 문의 목록 보기`} hint="담당자가 아직 정해지지 않았어요" />
                {STATES.map((s) => (
                  <Kpi key={s.k} label={s.label} n={v[s.k]} dot={s.color} to={`/tickets?st=${s.k}&${q}`} aria={`${s.label} ${v[s.k]}건. 해당 문의 목록 보기`} hint={s.k === 'FIN' ? '담당자 처리 후' : undefined} />
                ))}
              </div>
              <p className="small muted secnote">
                해결 완료 비율은 {total ? `${Math.round((v.CLS / total) * 100)}% (${v.CLS} / ${total}건)` : '계산할 건수가 없어요'}이에요. 선택 기간에 접수된 티켓 중 배정 전을 뺀 건수 대비 현재 해결 완료(CLS) 건수이고, 처리 성과를 뜻하지 않아요.
              </p>
              <p className="small muted secnote">삭제된 일반 이탈 문의와 숨긴 보안 문의는 이 통계에 넣지 않아요. 보안 건은 보안·감사 알림에서 확인해요.</p>
            </Section>

            <Section title="접수 추이" sec={trend}>
              {b ? (
                <>
                  <CurveChart
                    aria={`${PERN[per]} ${unitNow === 'w' ? '주별' : unitNow === 'mo' ? '월별' : '일별'} 접수 추이 곡선 그래프. 마지막 값 ${[['담당자 처리 접수', b.recv], ['해결 완료 (접수일 기준)', b.done]].map(([nm, vs]) => `${nm} ${(vs as number[])[b.labels.length - 1]}건`).join(', ')}`}
                    runKey={`${trend.dep}|${trend.id}`}
                    labels={b.labels}
                    series={[
                      { name: '담당자 처리 접수', k: 'ca', dash: '', v: b.recv },
                      { name: '해결 완료 (접수일 기준)', k: 'cb', dash: '1 6', v: b.done },
                    ]}
                  />
                  <p className="small muted secnote">{TREND_NOTE}</p>
                  <p className="small muted secnote">AI 해결의 일별·주별 추이는 서버에 기간별 집계가 없어 그리지 않아요. 오늘 기준 건수는 위 AI 상담 결과에서 볼 수 있어요.</p>
                </>
              ) : (
                <>
                  <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' }}>
                    <div className="kpi">
                      <div className="l">오늘 접수 (담당자 처리)</div>
                      <div className="v">
                        <b>
                          <CountUp value={tr?.total ?? 0} />
                        </b>
                        <span>건</span>
                      </div>
                    </div>
                    <div className="kpi">
                      <div className="l">오늘 AI 해결 (티켓 없음)</div>
                      <div className="v">
                        <b>
                          <CountUp value={counts?.all ?? 0} />
                        </b>
                        <span>건</span>
                      </div>
                    </div>
                  </div>
                  <p className="small muted secnote">오늘은 하루치라서 추이 그래프는 보여주지 않아요. 기간을 ‘최근 30일’ 이상으로 바꾸면 추이를 볼 수 있어요.</p>
                </>
              )}
            </Section>

            <Section title="팀별 진행도" sec={main} note="서버 집계 기준: 선택 기간에 접수된 티켓의 현재 상태예요. 배정 전 문의는 팀 막대에 넣지 않았어요.">
              <Legend />
              <div className="srows">
                {groups.map((g) => (
                  <div key={g.id}>
                    <StackRow
                      label={g.name}
                      sub={`${g.members.length}명`}
                      v={g.v}
                      mx={rowMx}
                      sel={g.name === sel}
                      tip={tip}
                      onClick={() => {
                        setSel(g.name === sel ? null : g.name)
                        setMember(null)
                      }}
                    />
                    <Collapse open={g.name === sel}>{g.name === sel && nested()}</Collapse>
                  </div>
                ))}
              </div>
              <div className="hint" style={{ marginTop: 8 }}>
                막대에 마우스를 올리면 처리 대기·처리 중·해결 확인 대기·해결 완료 건수를 볼 수 있어요. 팀을 누르면 그 아래에 팀원별 카드를 보여요.
              </div>
            </Section>

            <Section title="긴급도 분포 (P1~P4)" sec={main} note="선택 기간에 접수된 티켓 전체 기준이에요(배정 전 포함). 줄을 누르면 해당 긴급도 문의 목록으로 가요.">
              <div className="pdist">
                {URGS.map((p, i) => (
                  <button key={p} type="button" className="pd" onClick={() => navigate(`/tickets?pri=${p}&${q}`)} aria-label={`${p} ${urgN[i]}건. 이 긴급도의 문의 목록 보기`}>
                    <span className="pl">
                      <UrgencyChip u={p} />
                    </span>
                    <span className="bar" aria-hidden="true">
                      <i className={`pb-${p.toLowerCase()}`} style={{ width: `${Math.max(urgN[i] ? 3 : 0, (urgN[i] / urgMx) * 100)}%` }} />
                    </span>
                    <b>
                      {urgN[i]}
                      <small>건</small>
                    </b>
                    <Icon name="chevron" className="go" />
                    <span className="small muted pr">{PRI_RULE[p]}</span>
                  </button>
                ))}
              </div>
            </Section>
          </div>
        </div>
      </main>
      {tip.node}
    </div>
  )
}
