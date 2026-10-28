/**
 * 담당자 통계 (/stats). 기간과 조회 대상(내 통계 / 팀 통계)을 골라 상태별 현황, 접수 추이, 긴급도 분포, 팀원별 진행도를 본다.
 * 구역마다 따로 불러오고(불러오는 중 · 실패 · 다시 시도), 한 구역이 실패해도 다른 구역은 그대로 보인다.
 * 값은 접수 목록(TK-05)을 읽어 화면에서 센다. 통계 전용 API 는 아직 없어 집계 기준은 제안이다.
 * 상태별 현황은 선택 기간에 접수된 티켓의 현재 상태이고, 처리 성과나 평가 순위가 아니다. (design/ITssue-Prototype.html 의 담당자 통계)
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CATEGORIES, URGENCY_LABEL } from '../../api/catalog'
import type { CategoryCode, Urgency, WorkStatus } from '../../api/chatTypes'
import { getStatsSource, watchTickets } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'
import { UrgencyChip } from './QueueView'

type Per = 'd' | 'm' | 'y'
type Unit = 'd' | 'w' | 'mo'
type Key = 'sum' | 'trend' | 'pri' | 'mem'
const PERN: Record<Per, string> = { d: '오늘', m: '최근 30일', y: '최근 1년' }
const PERD: Record<Per, number> = { d: 1, m: 30, y: 366 }
const UL: Record<Unit, string> = { d: '일별', w: '주별', mo: '월별' }
const UNITS: Record<Per, Unit[]> = { d: [], m: ['d', 'w'], y: ['w', 'mo'] }
const UDEF: Record<Per, Unit> = { d: 'd', m: 'd', y: 'mo' }

const STATES: { k: WorkStatus; short: string; label: string; color: string }[] = [
  { k: 'RDY', short: '처리 대기', label: '처리 대기 (RDY)', color: 'var(--g-w)' },
  { k: 'WIP', short: '처리 중', label: '처리 중 (WIP)', color: 'var(--g-p)' },
  { k: 'FIN', short: '해결 확인 대기', label: '해결 확인 대기 (FIN)', color: 'var(--g-n)' },
  { k: 'CLS', short: '해결 완료', label: '해결 완료 (CLS)', color: 'var(--g-c)' },
]
const QS: Record<WorkStatus, string> = { RDY: '?tab=open&sub=RDY', WIP: '?tab=open&sub=WIP', FIN: '?tab=fin', CLS: '?tab=cls' }
const URGS: Urgency[] = ['P1', 'P2', 'P3', 'P4']
const URG_RULE: Record<Urgency, string> = { P1: '업무가 멈췄거나 많은 사람에게 영향을 줘요', P2: '업무에 큰 지장이 있어요', P3: '불편하지만 우회할 수 있어요', P4: '문의·요청이에요' }
const CATC: Record<CategoryCode, string> = { ACC: '#0EA5E9', ACS: '#8A64F2', NET: '#5B7CF0', SW: '#14B8A6', HW: '#D9A21B', SYS: '#E0457F', SEC: '#D92D20' }
const DAY = 86_400_000

const hm = () => {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const startOfDay = (t: number) => {
  const d = new Date(t)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}
const md = (t: number) => `${new Date(t).getMonth() + 1}.${new Date(t).getDate()}`
const countBy = (l: TicketSummary[]) => Object.fromEntries(STATES.map((s) => [s.k, l.filter((t) => t.workStatus === s.k).length])) as Record<WorkStatus, number>
const sumOf = (v: Record<WorkStatus, number>) => STATES.reduce((a, s) => a + v[s.k], 0)

/* ------------------------------------------------------------------ 구역별 불러오기 */
interface Sec {
  st: 'loading' | 'ok' | 'err'
  dep: string
  items: TicketSummary[]
  names: string[]
  at: string
  ts: number
  /** 몇 번째로 읽었는지 (그래프 애니메이션을 다시 돌리는 열쇠) */
  id: number
}

/** 구역 하나를 읽는다. 조건(dep)이 바뀌거나 '새로고침'을 누르면 불러오는 중이 되고, 접수가 바뀌면 조용히 다시 읽는다 */
function useSection(key: Key, dep: string, tick: number) {
  const { user } = useAuth()
  const [s, setS] = useState<Sec>({ st: 'loading', dep, items: [], names: [], at: '', ts: 0, id: 0 })
  const [nonce, setNonce] = useState(0)
  if (s.dep !== dep) setS({ st: 'loading', dep, items: [], names: [], at: '', ts: 0, id: s.id })
  useEffect(() => {
    if (!user) return
    let alive = true
    getStatsSource(user, key).then((r) => {
      if (!alive) return
      setS((p) => (p.dep !== dep ? p : r.ok ? { st: 'ok', dep, items: r.data.items, names: r.data.names, at: hm(), ts: Date.now(), id: p.id + 1 } : { ...p, st: 'err' }))
    })
    return () => {
      alive = false
    }
  }, [user, key, dep, nonce, tick])
  const reload = () => {
    setS((p) => ({ ...p, st: 'loading' }))
    setNonce((n) => n + 1)
  }
  return { ...s, reload }
}

/** 선택 기간(접수일 기준)과 조회 대상으로 거른다 */
const windowOf = (s: Sec, per: Per, team: boolean, userId: number) => {
  const from = per === 'd' ? startOfDay(s.ts) : s.ts - PERD[per] * DAY
  return s.items.filter((t) => Date.parse(t.createdAt) >= from && (team || t.assignee?.id === userId))
}

function Section({ title, sec, note, children }: { title: string; sec: Sec & { reload: () => void }; note?: string; children: ReactNode }) {
  const head = (
    <div className="row sh">
      <h3>{title}</h3>
      <span className="small muted asof">{sec.st === 'ok' ? `집계 기준 ${sec.at}` : ''}</span>
      {sec.st !== 'loading' && (
        <button type="button" className="btn ghost sm" onClick={sec.reload}>
          {sec.st === 'err' ? (
            '다시 시도'
          ) : (
            <>
              <Icon name="refresh" /> 새로고침
            </>
          )}
        </button>
      )}
    </div>
  )
  if (sec.st === 'loading')
    return (
      <section className="panel sec" aria-busy="true" aria-label={title}>
        {head}
        <div className="skel" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <p className="small muted" role="status">
          불러오는 중이에요
        </p>
      </section>
    )
  if (sec.st === 'err')
    return (
      <section className="panel sec" aria-label={title}>
        {head}
        <div className="alert err" role="alert">
          <Icon name="alert" />
          <div>
            <b>이 구역을 불러오지 못했어요.</b>
            <br />
            다른 구역은 그대로 볼 수 있어요. 잠시 후 다시 시도해 주세요.
          </div>
        </div>
      </section>
    )
  return (
    <section className="panel sec" aria-label={title}>
      {head}
      {note && <p className="small muted secnote">{note}</p>}
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------ 곡선 그래프 */
interface Series {
  name: string
  k: 'ca' | 'cb'
  dash: string
  v: number[]
}

/** 꺾이지 않는 부드러운 곡선 (단조 3차 보간): 값 사이에서 튀어 오르지 않는다 */
function monoPath(pts: [number, number][]) {
  const n = pts.length
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  if (n < 2) return `M${xs[0]} ${ys[0]}`
  const d: number[] = []
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]))
  const m = [d[0]]
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2)
  m.push(d[n - 2])
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = m[i + 1] = 0
    } else {
      const al = m[i] / d[i]
      const be = m[i + 1] / d[i]
      const h = al * al + be * be
      if (h > 9) {
        const t = 3 / Math.sqrt(h)
        m[i] = t * al * d[i]
        m[i + 1] = t * be * d[i]
      }
    }
  }
  let p = `M${xs[0].toFixed(1)} ${ys[0].toFixed(1)}`
  for (let i = 0; i < n - 1; i++) {
    const dx = (xs[i + 1] - xs[i]) / 3
    p += ` C${(xs[i] + dx).toFixed(1)} ${(ys[i] + m[i] * dx).toFixed(1)} ${(xs[i + 1] - dx).toFixed(1)} ${(ys[i + 1] - m[i + 1] * dx).toFixed(1)} ${xs[i + 1].toFixed(1)} ${ys[i + 1].toFixed(1)}`
  }
  return p
}

/** 글자 너비 어림 (한글 12, 그 밖 7.6) */
const LW = (tx: string) => Math.round([...tx].reduce((a, c) => a + (c.charCodeAt(0) > 255 ? 12 : 7.6), 0) + 14)
const shortName = (n: string) => n.split(' ')[0]

function CurveChart({ labels, series, runKey }: { labels: string[]; series: Series[]; runKey: string }) {
  const [table, setTable] = useState(false)
  const [hv, setHv] = useState<{ i: number; cx: number; cy: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const uid = `cv${useId().replace(/:/g, '')}`
  const n = labels.length
  const W = 860
  const H = 220
  const pl = 34
  const pr = Math.max(46, ...series.map((s) => LW(`${shortName(s.name)} ${s.v[n - 1]}`))) + 16
  const pt = 14
  const pb = 26
  const iw = W - pl - pr
  const ih = H - pt - pb
  const top = Math.max(1, ...series.flatMap((s) => s.v))
  const step = top <= 8 ? 2 : top <= 16 ? 4 : (() => { const mag = Math.pow(10, Math.floor(Math.log10(top / 4))); return [1, 2, 5, 10].map((m) => m * mag).find((x) => x >= top / 4) ?? mag })()
  const mx = Math.ceil(top / step) * step
  const X = (i: number) => pl + (n === 1 ? iw / 2 : (i * iw) / (n - 1))
  const Y = (v: number) => pt + ih - (v / mx) * ih
  const every = Math.max(1, Math.ceil(n / Math.max(3, Math.floor((W - 80) / (labels[0].length > 6 ? 96 : 44)))))
  const pts = series.map((s) => s.v.map((v, i): [number, number] => [X(i), Y(v)]))
  const ticks: number[] = []
  for (let v = 0; v <= mx + 0.001; v += step) ticks.push(v)

  // 선 끝 이름표가 겹치지 않게 위아래로 벌린다
  const ys = series.map((_, k) => pts[k][n - 1][1])
  const tops: number[] = []
  {
    let prev = -1e9
    ys.map((y, k) => [y, k] as const)
      .sort((p, q) => p[0] - q[0])
      .forEach(([y, k]) => {
        let t = y - 10
        if (t < prev + 23) t = prev + 23
        prev = t
        tops[k] = t
      })
  }

  const idxAt = (e: PointerEvent) => {
    const r = svgRef.current!.getBoundingClientRect()
    const x = ((e.clientX - r.left) * W) / r.width
    let b = 0
    let bd = 1e9
    for (let i = 0; i < n; i++) {
      const d = Math.abs(X(i) - x)
      if (d < bd) {
        bd = d
        b = i
      }
    }
    return b
  }
  const showAt = (i: number, cx?: number, cy?: number) => {
    const r = svgRef.current!.getBoundingClientRect()
    const k = r.width / W
    setHv({ i, cx: cx ?? r.left + X(i) * k, cy: cy ?? r.top + pt * k })
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') {
      showAt(Math.max(0, (hv?.i ?? n - 1) - 1))
      e.preventDefault()
    } else if (e.key === 'ArrowRight') {
      showAt(Math.min(n - 1, (hv?.i ?? n - 1) + 1))
      e.preventDefault()
    } else if (e.key === 'Escape') setHv(null)
  }

  return (
    <div className="hvw">
      <div className="lgd" style={{ margin: '0 0 6px' }}>
        {series.map((s) => (
          <span key={s.name}>
            <svg width="24" height="10" aria-hidden="true" style={{ marginRight: 6, verticalAlign: -1 }}>
              <line x1="2" x2="22" y1="5" y2="5" stroke={`var(--${s.k})`} strokeWidth="3" strokeLinecap="round" strokeDasharray={s.dash || undefined} />
            </svg>
            {s.name}
          </span>
        ))}
      </div>
      <div className="hvbar">
        <span className="small muted">그래프에 마우스를 올리거나 표로 바꿔서 값을 읽을 수 있어요</span>
        <div className="seg" role="group" aria-label="보기 방식">
          <button type="button" className={table ? '' : 'on'} aria-pressed={!table} onClick={() => setTable(false)}>
            그래프
          </button>
          <button type="button" className={table ? 'on' : ''} aria-pressed={table} onClick={() => setTable(true)}>
            표
          </button>
        </div>
      </div>
      {table ? (
        <div className="tw">
          <table className="tbl hvt">
            <caption className="sr">접수 추이 수치 표</caption>
            <thead>
              <tr>
                <th scope="col">기간</th>
                {series.map((s) => (
                  <th key={s.name} scope="col">
                    {s.name}(건)
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((l, i) => (
                <tr key={l}>
                  <th scope="row">{l}</th>
                  {series.map((s) => (
                    <td key={s.name} className="num">
                      {s.v[i].toLocaleString()}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="tw">
          <svg
            key={runKey}
            ref={svgRef}
            className="hv"
            tabIndex={0}
            viewBox={`0 0 ${W} ${H}`}
            style={{ width: '100%', height: 'auto', display: 'block', borderRadius: 8 }}
            role="img"
            aria-label={`${labels[0]}부터 ${labels[n - 1]}까지 접수 추이 곡선 그래프. 마지막 값 ${series.map((s) => `${s.name} ${s.v[n - 1]}건`).join(', ')}`}
            onPointerMove={(e) => showAt(idxAt(e), e.clientX, e.clientY)}
            onPointerDown={(e) => showAt(idxAt(e), e.clientX, e.clientY)}
            onPointerLeave={(e) => e.pointerType === 'mouse' && setHv(null)}
            onFocus={() => showAt(n - 1)}
            onBlur={() => setHv(null)}
            onKeyDown={onKey}
          >
            <defs>
              {series.map((s, k) => (
                <g key={s.k}>
                  <linearGradient id={`${uid}s${k}`} x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0" style={{ stopColor: `var(--${s.k}1)` }} />
                    <stop offset="1" style={{ stopColor: `var(--${s.k}2)` }} />
                  </linearGradient>
                  <linearGradient id={`${uid}a${k}`} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0" style={{ stopColor: `var(--${s.k})`, stopOpacity: 'var(--aop)' }} />
                    <stop offset=".85" style={{ stopColor: `var(--${s.k})`, stopOpacity: 0 }} />
                  </linearGradient>
                </g>
              ))}
              <filter id={`${uid}g`} x="-5%" y="-30%" width="110%" height="160%">
                <feGaussianBlur stdDeviation="2" />
              </filter>
            </defs>
            {ticks.map((v) => (
              <g key={v}>
                <line x1={pl} x2={W - pr} y1={Y(v).toFixed(1)} y2={Y(v).toFixed(1)} stroke="var(--line)" strokeWidth="1" />
                <text x={pl - 8} y={(Y(v) + 4).toFixed(1)} textAnchor="end" style={{ fontSize: 12, fill: 'var(--mute)' }}>
                  {Math.round(v)}
                </text>
              </g>
            ))}
            {[...series.keys()].reverse().map((k) => {
              const p = monoPath(pts[k])
              return (
                <g key={series[k].k}>
                  <path d={`${p} L${X(n - 1).toFixed(1)} ${Y(0).toFixed(1)} L${X(0).toFixed(1)} ${Y(0).toFixed(1)} Z`} fill={`url(#${uid}a${k})`} />
                  <path d={p} fill="none" stroke={`url(#${uid}s${k})`} strokeWidth="3" style={{ opacity: 'var(--glow-op)' }} filter={`url(#${uid}g)`} />
                  <path d={p} fill="none" stroke={`url(#${uid}s${k})`} strokeWidth="2" strokeLinecap="round" strokeDasharray={series[k].dash || undefined} />
                </g>
              )
            })}
            {series.map((s, k) => {
              const y = ys[k]
              const off = tops[k] - y
              const lbt = `${shortName(s.name)} ${s.v[n - 1]}`
              const lbw = Math.max(30, LW(lbt))
              return (
                <g key={s.k}>
                  <circle cx={X(n - 1).toFixed(1)} cy={y.toFixed(1)} r="3.6" style={{ fill: `var(--${s.k})` }} stroke="var(--white)" strokeWidth="1.6" />
                  <rect x={(X(n - 1) + 8).toFixed(1)} y={(y + off).toFixed(1)} width={lbw} height="20" rx="10" style={{ fill: 'var(--card)', stroke: `var(--${s.k})` }} strokeOpacity=".55" />
                  <text x={(X(n - 1) + 8 + lbw / 2).toFixed(1)} y={(y + off + 14).toFixed(1)} textAnchor="middle" style={{ fontSize: 12, fontWeight: 700, fill: 'var(--ink)' }}>
                    {lbt}
                  </text>
                </g>
              )
            })}
            {labels.map((l, i) =>
              i % every === 0 || i === n - 1 ? (
                <text key={l} x={X(i).toFixed(1)} y={H - 6} textAnchor="middle" style={{ fontSize: 12, fill: 'var(--mute)' }}>
                  {l}
                </text>
              ) : null,
            )}
            {hv && (
              <g style={{ pointerEvents: 'none' }}>
                <line x1={X(hv.i)} x2={X(hv.i)} y1={pt} y2={pt + ih} stroke="var(--ink2)" strokeOpacity=".4" strokeDasharray="2 3" />
                {series.map((s, k) => (
                  <circle key={s.k} cx={X(hv.i)} cy={pts[k][hv.i][1]} r="4.4" style={{ fill: `var(--${s.k})` }} stroke="var(--white)" strokeWidth="1.8" />
                ))}
              </g>
            )}
          </svg>
        </div>
      )}
      {hv && !table && (
        <div className="hvtip" aria-hidden="true" style={{ left: Math.max(8, hv.cx + 14 + 150 > window.innerWidth - 8 ? hv.cx - 164 : hv.cx + 14), top: Math.max(8, hv.cy - 12) }}>
          <b>{labels[hv.i]}</b>
          {series.map((s) => (
            <div key={s.k}>
              <i style={{ background: `var(--${s.k})` }} />
              {s.name}
              <span>{s.v[hv.i]}건</span>
            </div>
          ))}
        </div>
      )}
      <p className="sr" aria-live="polite">
        {hv && !table ? `${labels[hv.i]} ${series.map((s) => `${s.name} ${s.v[hv.i]}건`).join(', ')}` : ''}
      </p>
    </div>
  )
}

/** 선택 단위로 접수 건수와 해결 완료(접수일 기준) 건수를 묶는다. 오래된 쪽부터 */
function bucket(list: TicketSummary[], per: Per, unit: Unit, ts: number) {
  const today = startOfDay(ts)
  const labels: string[] = []
  const edges: [number, number][] = []
  if (unit === 'mo') {
    const now = new Date(ts)
    for (let k = 11; k >= 0; k--) {
      const a = new Date(now.getFullYear(), now.getMonth() - k, 1)
      const b = new Date(now.getFullYear(), now.getMonth() - k + 1, 1)
      labels.push(`${String(a.getFullYear()).slice(2)}.${String(a.getMonth() + 1).padStart(2, '0')}`)
      edges.push([a.getTime(), b.getTime()])
    }
  } else {
    const days = per === 'y' ? 52 * 7 : PERD[per]
    const stp = unit === 'w' ? 7 : 1
    const n = Math.ceil(days / stp)
    for (let k = n - 1; k >= 0; k--) {
      const hi = today - k * stp * DAY + DAY
      const lo = Math.max(hi - stp * DAY, today - (days - 1) * DAY)
      labels.push(stp === 1 ? md(lo) : `${md(lo)}~${md(hi - DAY)}`)
      edges.push([lo, hi])
    }
  }
  const inB = (t: TicketSummary, e: [number, number]) => Date.parse(t.createdAt) >= e[0] && Date.parse(t.createdAt) < e[1]
  return { labels, recv: edges.map((e) => list.filter((t) => inB(t, e)).length), done: edges.map((e) => list.filter((t) => inB(t, e) && t.workStatus === 'CLS').length) }
}

/* ------------------------------------------------------------------ 도넛 */
function Donut({ parts, center, sub, cls }: { parts: { l: string; v: number; c: string }[]; center: number; sub: string; cls?: string }) {
  const t = parts.reduce((a, p) => a + p.v, 0) || 1
  const R = 48
  const CC = 2 * Math.PI * R
  const shown = parts.filter((p) => p.v)
  const starts = shown.map((_, i) => shown.slice(0, i).reduce((a, p) => a + (p.v / t) * CC, 0))
  return (
    <div className={`donut ${cls ?? ''}`}>
      <svg viewBox="0 0 140 140" width="140" height="140" role="img" aria-label={`${center}${sub}. ${parts.filter((p) => p.v).map((p) => `${p.l} ${p.v}`).join(', ')}`}>
        <circle cx="70" cy="70" r={R} fill="none" stroke="var(--track)" strokeWidth="18" />
        {shown.map((p, i) => {
          const len = (p.v / t) * CC
          return (
            <circle key={p.l} cx="70" cy="70" r={R} fill="none" stroke={p.c} strokeWidth="18" strokeDasharray={`${Math.max(0, len - 2)} ${CC - Math.max(0, len - 2)}`} strokeDashoffset={-starts[i]} transform="rotate(-90 70 70)">
              <title>{`${p.l} ${p.v}`}</title>
            </circle>
          )
        })}
        <text x="70" y="68" textAnchor="middle" style={{ fontSize: 26, fontWeight: 700, fill: 'var(--ink)' }}>
          {center}
        </text>
        <text x="70" y="88" textAnchor="middle" style={{ fontSize: 12, fill: 'var(--mute)' }}>
          {sub}
        </text>
      </svg>
      <ul className="dl2">
        {parts.map((p) => (
          <li key={p.l}>
            <i style={{ background: p.c }} />
            <span>{p.l}</span>
            <b>{p.v}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 팀원 한 명의 개인 현황: 처리 상태와 분류 도넛 */
function MemberDonuts({ name, list }: { name: string; list: TicketSummary[] }) {
  const mine = list.filter((t) => t.assignee?.name === name)
  const v = countBy(mine)
  const total = sumOf(v)
  const cats = (Object.keys(CATEGORIES) as CategoryCode[]).map((c) => ({ l: CATEGORIES[c].name, v: mine.filter((t) => t.category?.code === c).length, c: CATC[c] }))
  return (
    <div className="nest don">
      <div className="mp2">
        <h4>{name} · 개인 현황</h4>
        <div className="g2 mpg">
          <div className="dbox">
            <div className="small muted" style={{ marginBottom: 8 }}>
              처리 상태
            </div>
            <Donut parts={STATES.map((s) => ({ l: s.short, v: v[s.k], c: s.color }))} center={total} sub="건" />
          </div>
          <div className="dbox">
            <div className="small muted" style={{ marginBottom: 8 }}>
              분류
            </div>
            <Donut parts={cats} center={total} sub="건" cls="cat" />
          </div>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ 화면 */
export function StatsView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const team = params.get('scope') === 'team'
  const [per, setPer] = useState<Per>('m')
  const [unit, setUnit] = useState<Unit>(UDEF.m)
  const [member, setMember] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  // watchTickets 는 구독하자마자 한 번 알리므로 처음 알림은 건너뛴다 (구역은 이미 읽는 중이다)
  useEffect(() => {
    let first = true
    return watchTickets(() => {
      if (first) first = false
      else setTick((n) => n + 1)
    })
  }, [])

  const scope = team ? 'team' : 'me'
  const unitNow = UNITS[per].includes(unit) ? unit : UDEF[per]
  const sum = useSection('sum', `${per}|${scope}`, tick)
  const trend = useSection('trend', `${per}|${scope}|${unitNow}`, tick)
  const pri = useSection('pri', `${per}|${scope}`, tick)
  const mem = useSection('mem', `${per}|team`, tick)
  const uid = user?.id ?? 0

  const sumWin = useMemo(() => windowOf(sum, per, team, uid), [sum, per, team, uid])
  const trendWin = useMemo(() => windowOf(trend, per, team, uid), [trend, per, team, uid])
  const priWin = useMemo(() => windowOf(pri, per, team, uid), [pri, per, team, uid])
  const memWin = useMemo(() => windowOf(mem, per, true, uid), [mem, per, uid])

  if (!user) return null
  const groupName = user.departmentName ?? ''
  const v = countBy(sumWin)
  const total = sumOf(v)
  const none = sumWin.filter((t) => !t.workStatus).length
  const b = per === 'd' ? null : bucket(trendWin, per, unitNow, trend.ts)
  const urgN = URGS.map((p) => priWin.filter((t) => t.urgency === p).length)
  const urgMx = Math.max(1, ...urgN)
  const byMember = mem.names.map((n) => ({ n, v: countBy(memWin.filter((t) => t.assignee?.name === n)) }))
  const mx = Math.max(1, ...byMember.map((m) => sumOf(m.v)))
  const pickPer = (p: Per) => {
    setPer(p)
    setUnit(UDEF[p])
    setMember(null)
  }

  return (
    <main className="main">
      <Topbar title="통계" sub={`${user.departmentName} · ${user.name} 담당자`} lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div>
            <div className="eyebrow">STATISTICS</div>
            <h1>통계</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              기간과 조회 대상을 골라 추이와 분포를 살펴봐요. 지금 처리할 일은 내 대시보드에서 확인해요.
            </p>
          </div>

          <div className="sbar2">
            <div className="sg">
              <span className="small muted" id="sl">
                조회 대상
              </span>
              <div className="seg" role="group" aria-labelledby="sl">
                <button type="button" className={!team ? 'on' : ''} aria-pressed={!team} onClick={() => setParams({})}>
                  내 통계
                </button>
                <button type="button" className={team ? 'on' : ''} aria-pressed={team} onClick={() => setParams({ scope: 'team' })}>
                  {groupName} 통계
                </button>
              </div>
            </div>
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

          <Section title="상태별 현황" sec={sum} note="선택 기간에 접수된 티켓의 현재 상태예요. 선택 기간에 처리가 끝난 건수가 아니에요.">
            <div className="sk">
              {STATES.map((s) => (
                <button key={s.k} type="button" className="kpi kl" onClick={() => navigate(`/queue${QS[s.k]}`)} aria-label={`${s.label} ${v[s.k]}건. 해당 문의 목록 보기`}>
                  <div className="l">
                    <i className="dt" style={{ background: s.color }} />
                    {s.label}
                  </div>
                  <div className="v">
                    <b>{v[s.k]}</b>
                    <span>건</span>
                  </div>
                  <Icon name="chevron" className="go" />
                </button>
              ))}
            </div>
            {team && <p className="small muted secnote">배정 전 {none}건은 위 네 상태에 넣지 않고 따로 세요.</p>}
            <p className="small muted secnote">
              해결 완료 비율은 {total ? `${Math.round((v.CLS / total) * 100)}% (${v.CLS} / ${total}건)` : '계산할 건수가 없어요'}이에요. 선택 기간에 접수된 티켓 중 배정 전을 뺀 건수 대비 현재 해결 완료(CLS) 건수이고, 처리 성과를 뜻하지 않아요.
            </p>
          </Section>

          <Section title="접수 추이" sec={trend}>
            {b ? (
              <>
                <CurveChart
                  runKey={`${trend.dep}|${trend.id}`}
                  labels={b.labels}
                  series={[
                    { name: '접수', k: 'ca', dash: '', v: b.recv },
                    { name: '해결 완료 (접수일 기준)', k: 'cb', dash: '1 6', v: b.done },
                  ]}
                />
                <p className="small muted secnote">해결 완료 선은 그날 접수된 티켓 중 지금 해결 완료(CLS)인 건수(접수일 기준)예요. 해결한 날짜 기준이 아니에요.</p>
              </>
            ) : (
              <>
                <div className="sk" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' }}>
                  <div className="kpi">
                    <div className="l">오늘 접수</div>
                    <div className="v">
                      <b>{trendWin.length}</b>
                      <span>건</span>
                    </div>
                  </div>
                </div>
                <p className="small muted secnote">오늘은 하루치라서 추이 그래프는 보여주지 않아요. 기간을 ‘최근 30일’ 이상으로 바꾸면 추이를 볼 수 있어요.</p>
              </>
            )}
          </Section>

          <Section title="긴급도 분포" sec={pri} note="선택 기간에 접수된 티켓 기준이에요.">
            <div className="pdist">
              {URGS.map((p, i) => (
                <button key={p} type="button" className="pd" onClick={() => navigate(`/queue?pri=${p}&per=${per}`)} aria-label={`${p} ${urgN[i]}건. 이 긴급도의 문의 목록 보기`}>
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
                  <span className="small muted pr">
                    {URGENCY_LABEL[p]} · {URG_RULE[p]}
                  </span>
                </button>
              ))}
            </div>
            {team && (
              <p className="small muted secnote" style={{ marginTop: 8 }}>
                건수는 팀 전체예요. 줄을 누르면 내 문의 중 해당 긴급도만 목록으로 보여줘요.
              </p>
            )}
          </Section>

          {team && (
            <Section title="팀원별 진행도" sec={mem} note="선택 기간에 접수된 티켓의 현재 상태 기준이에요.">
              <div className="lgd" style={{ margin: 0 }}>
                {STATES.map((s) => (
                  <span key={s.k}>
                    <i style={{ background: s.color }} />
                    {s.short}
                  </span>
                ))}
              </div>
              <div className="srows">
                {byMember.map(({ n, v: mv }) => {
                  const t = sumOf(mv)
                  const me = n === user.name
                  const sel = member === n
                  return (
                    <div key={n}>
                      <button type="button" className={`srow${sel ? ' sel' : ''}${me ? ' me' : ''}`} aria-pressed={sel} onClick={() => setMember(sel ? null : n)}>
                        <div className="sl">
                          <b>
                            {n}
                            {me && <span className="mebadge">나</span>}
                          </b>
                        </div>
                        <div className="sbar" role="img" aria-label={STATES.map((s) => `${s.short} ${mv[s.k]}`).join(', ')}>
                          {t ? STATES.map((s) => (mv[s.k] ? <div key={s.k} style={{ width: `${(mv[s.k] / mx) * 100}%`, background: s.color }} title={`${s.short} ${mv[s.k]}`} /> : null)) : <div style={{ width: 3, background: 'var(--line)' }} />}
                        </div>
                        <div className="sn">
                          <b>{t}</b>
                          <small>{t ? `완료 ${Math.round((mv.CLS / t) * 100)}%` : '-'}</small>
                        </div>
                      </button>
                      {sel && <MemberDonuts name={n} list={memWin} />}
                    </div>
                  )
                })}
              </div>
              <div className="hint" style={{ marginTop: 8 }}>
                이름을 누르면 아래에 개인 현황(도넛)이 펼쳐져요. 업무량 확인용이며 평가 순위가 아니에요.
              </div>
            </Section>
          )}
        </div>
      </div>
    </main>
  )
}
