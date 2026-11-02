/**
 * 관리자 통계 (/stats). (design/ITssue-Prototype.html viewStatsAdmin)
 * 티켓(담당자 처리)과 AI 상담 결과를 구분해서 보여 준다: AI 상담 결과, 담당자 처리 현황, 접수 추이, 팀별·분류별 진행도(구성원·개인 현황), 긴급도 분포.
 * 구역마다 따로 불러오고(불러오는 중 · 실패 · 다시 시도) 한 구역이 실패해도 다른 구역은 그대로 보인다. 담당자 통계(StatsView)의 부품을 함께 쓴다.
 * 값은 접수 목록(TK-05 view=ALL)과 문의 목록(IQ-02)을 읽어 화면에서 센다. 통계 전용 API 는 아직 없어 집계 기준은 제안이다. (요청 R-01)
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { getAdminStatsSource, type AdminStatKey } from '../../api/adminStats'
import type { AiPage } from '../../api/inquiries'
import { watchTickets } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'
import { UrgencyChip } from '../staff/QueueView'
import { CurveChart, MemberDonuts, PERN, PRI_RULE, STATES, Section, TREND_NOTE, UDEF, UL, UNITS, URGS, bucket, countBy, sumOf, useSection, windowOf, type Per, type Unit } from '../staff/StatsView'

type Mode = 'team' | 'cat'
type Counts = AiPage['counts']
type Groups = { name: string; members: string[] }[]

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
        <b>{n}</b>
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

/** 상태별 쌓인 막대 한 줄 (팀·분류·구성원) */
function StackRow({ label, sub, v, mx, sel, onClick }: { label: string; sub?: string; v: Record<'RDY' | 'WIP' | 'FIN' | 'CLS', number>; mx: number; sel?: boolean; onClick: () => void }) {
  const t = sumOf(v)
  return (
    <button type="button" className={`srow${sel ? ' sel' : ''}`} aria-pressed={!!sel} onClick={onClick}>
      <div className="sl">
        <b>{label}</b>
        {sub && <small>{sub}</small>}
      </div>
      <div className="sbar" role="img" aria-label={STATES.map((s) => `${s.short} ${v[s.k]}`).join(', ')}>
        {t ? STATES.map((s) => (v[s.k] ? <div key={s.k} style={{ width: `${(v[s.k] / mx) * 100}%`, background: s.color }} title={`${s.short} ${v[s.k]}`} /> : null)) : <div style={{ width: 3, background: 'var(--line)' }} />}
      </div>
      <div className="sn">
        <b>{t}</b>
        <small>{t ? `완료 ${Math.round((v.CLS / t) * 100)}%` : '-'}</small>
      </div>
    </button>
  )
}

const Legend = () => (
  <div className="lgd" style={{ margin: 0 }}>
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
  const [mode, setMode] = useState<Mode>('team')
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
  const loader = useCallback((key: AdminStatKey) => (u: NonNullable<typeof user>) => getAdminStatsSource(u, key, per), [per])
  const loadAi = useMemo(() => loader('ai'), [loader])
  const loadSum = useMemo(() => loader('sum'), [loader])
  const loadTrend = useMemo(() => loader('trend'), [loader])
  const loadPri = useMemo(() => loader('pri'), [loader])
  const loadProg = useMemo(() => loader('prog'), [loader])
  const loadMem = useMemo(() => loader('mem'), [loader])

  const ai = useSection('ai', per, tick, loadAi)
  const sum = useSection('sum', per, tick, loadSum)
  const trend = useSection('trend', `${per}|${unitNow}`, tick, loadTrend)
  const prog = useSection('prog', `${per}|${mode}`, tick, loadProg)
  const pri = useSection('pri', per, tick, loadPri)
  const mem = useSection('mem', `${per}|${mode}|${sel ?? ''}`, tick, loadMem)
  const uid = user?.id ?? 0

  const sumWin = useMemo(() => windowOf(sum, per, true, uid), [sum, per, uid])
  const trendWin = useMemo(() => windowOf(trend, per, true, uid), [trend, per, uid])
  const progWin = useMemo(() => windowOf(prog, per, true, uid), [prog, per, uid])
  const priWin = useMemo(() => windowOf(pri, per, true, uid), [pri, per, uid])
  const memWin = useMemo(() => windowOf(mem, per, true, uid), [mem, per, uid])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const counts = ai.extra as Counts | undefined
  const v = countBy(sumWin)
  const none = sumWin.filter((t) => !t.workStatus).length
  const total = sumOf(v)
  const b = per === 'd' ? null : bucket(trendWin, per, unitNow, trend.ts)
  const urgN = URGS.map((p) => priWin.filter((t) => t.urgency === p).length)
  const urgMx = Math.max(1, ...urgN)
  const q = `per=${per}`
  const pickPer = (p: Per) => {
    setPer(p)
    setUnit(UDEF[p])
    setMember(null)
  }
  const pickMode = (m: Mode) => {
    setMode(m)
    setSel(null)
    setMember(null)
  }

  const groups: Groups = (prog.extra as { groups: Groups } | undefined)?.groups ?? []
  const items =
    mode === 'team'
      ? groups.map((g) => ({ k: g.name, label: g.name, sub: `${g.members.length}명`, v: countBy(progWin.filter((t) => t.group?.name === g.name)) }))
      : (Object.keys(CATEGORIES) as CategoryCode[]).map((c) => ({ k: c, label: CATEGORIES[c].name, sub: '', v: countBy(progWin.filter((t) => t.category?.code === c)) }))
  const rowMx = Math.max(1, ...items.map((i) => sumOf(i.v)))

  const nested = () => {
    if (!sel) return null
    const label = mode === 'team' ? sel : CATEGORIES[sel as CategoryCode].name
    const inSel = (t: TicketSummary) => (mode === 'team' ? t.group?.name === sel : t.category?.code === sel)
    if (mem.st === 'loading')
      return (
        <div className="nest" aria-busy="true">
          <div className="skel" aria-hidden="true">
            <i />
            <i />
          </div>
          <p className="small muted" role="status">
            구성원별 진행도를 불러오는 중이에요
          </p>
        </div>
      )
    if (mem.st === 'err')
      return (
        <div className="nest">
          <div className="alert err" role="alert">
            <Icon name="alert" />
            <div>
              <b>구성원별 진행도를 불러오지 못했어요.</b>
            </div>
          </div>
          <button type="button" className="btn ghost sm" onClick={mem.reload}>
            다시 시도
          </button>
        </div>
      )
    const memGroups = (mem.extra as { groups: Groups } | undefined)?.groups ?? []
    const names = mode === 'team' ? (memGroups.find((g) => g.name === sel)?.members ?? []) : [...new Set(mem.items.filter((t) => t.category?.code === sel && t.assignee).map((t) => t.assignee!.name))]
    const win = memWin.filter(inSel)
    const rows = names.map((n) => ({ n, v: countBy(win.filter((t) => t.assignee?.name === n)) }))
    const mx = Math.max(1, ...rows.map((r) => sumOf(r.v)))
    return (
      <div className="nest">
        <div className="nh">
          <b>{label} · 구성원별 진행도</b>
          <span className="small muted">집계 기준 {mem.at}</span>
          <button type="button" className="btn ghost sm" onClick={mem.reload}>
            <Icon name="refresh" /> 새로고침
          </button>
        </div>
        <div className="srows">
          {rows.map((r) => (
            <div key={r.n}>
              <StackRow label={r.n} v={r.v} mx={mx} sel={member === r.n} onClick={() => setMember(member === r.n ? null : r.n)} />
              {member === r.n && <MemberDonuts name={r.n} list={win} />}
            </div>
          ))}
        </div>
        <div className="hint" style={{ marginTop: 6 }}>
          이름을 누르면 아래에 개인 현황(도넛)을 불러와요. 업무량 확인용이며 평가 순위가 아니에요.
        </div>
      </div>
    )
  }

  return (
    <div className="stx">
      <main className="main">
        <Topbar title="통계" sub="티켓과 AI 해결을 구분해서 보여줘요" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page dpage">
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
                <Kpi label="미해결 종료" n={counts?.unr ?? 0} sug to={`/tickets?mode=ai&aik=unr&${q}`} aria={`미해결 종료 ${counts?.unr ?? 0}건. 해당 목록 보기`} hint="해결되지 않고 끝난 문의 (접수하지 않고 끝낸 문의 포함)" />
              </div>
              <p className="small muted secnote">담당자 처리(티켓)와는 따로 세요. AI 해결과 해결 완료(CLS)는 합치지 않아요.</p>
            </Section>

            <Section title="담당자 처리 (티켓)" kind="tk" sec={sum} note="티켓이 만들어진 접수 · 접수한 날 기준이에요.">
              <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))' }}>
                <Kpi label="담당자 처리 접수" n={sumWin.length} to={`/tickets?${q}`} aria={`담당자 처리 접수 ${sumWin.length}건. 전체 문의 목록 보기`} hint="선택 기간에 접수된 티켓" />
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
                        <b>{trendWin.length}</b>
                        <span>건</span>
                      </div>
                    </div>
                    <div className="kpi">
                      <div className="l">오늘 AI 해결 (티켓 없음)</div>
                      <div className="v">
                        <b>{counts?.all ?? 0}</b>
                        <span>건</span>
                      </div>
                    </div>
                  </div>
                  <p className="small muted secnote">오늘은 하루치라서 추이 그래프는 보여주지 않아요. 기간을 ‘최근 30일’ 이상으로 바꾸면 추이를 볼 수 있어요.</p>
                </>
              )}
            </Section>

            <Section title="팀별·분류별 진행도" sec={prog} note="선택 기간에 접수된 티켓의 현재 상태 기준이에요. 배정 전 문의는 막대에 넣지 않았어요.">
              <div className="row" style={{ justifyContent: 'space-between', margin: '8px 0' }}>
                <div className="seg" role="group" aria-label="진행도 기준">
                  <button type="button" className={mode === 'team' ? 'on' : ''} aria-pressed={mode === 'team'} onClick={() => pickMode('team')}>
                    팀별
                  </button>
                  <button type="button" className={mode === 'cat' ? 'on' : ''} aria-pressed={mode === 'cat'} onClick={() => pickMode('cat')}>
                    분류별
                  </button>
                </div>
              </div>
              <Legend />
              <div className="srows">
                {items.map((i) => (
                  <div key={i.k}>
                    <StackRow
                      label={i.label}
                      sub={i.sub}
                      v={i.v}
                      mx={rowMx}
                      sel={i.k === sel}
                      onClick={() => {
                        setSel(i.k === sel ? null : i.k)
                        setMember(null)
                      }}
                    />
                    {i.k === sel && nested()}
                  </div>
                ))}
              </div>
              <div className="hint" style={{ marginTop: 8 }}>
                {mode === 'team' ? '팀' : '분류'}를 누르면 그 아래에 구성원별 진행도를 불러와요.
              </div>
            </Section>

            <Section title="긴급도 분포 (P1~P4)" sec={pri} note="선택 기간에 접수된 티켓 전체 기준이에요(배정 전 포함). 줄을 누르면 해당 긴급도 문의 목록으로 가요.">
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
    </div>
  )
}
