/**
 * 보안·감사 알림 (관리자, /security). (design/ITssue-Prototype.html viewSec)
 * 문의가 접수되지 않았어도 ITssue 안에서 감지한 신호를 모아 본다. 사내 보안 관제를 대체하지 않고 티켓과도 따로 관리한다.
 * 민감정보를 가린 내용만 보이고, 원문은 사유를 적어야 볼 수 있으며 열람 기록이 남는다. 상태: 신규 → 확인 중 → 종결(사유 필수).
 * 문의 서버 모드에서는 실제 탐지·처리 이력을 읽는다. 인증정보 원문은 복구하지 않는다.
 */
import { useEffect, useId, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import {
  SEC_TYPES,
  closeSecurityAlert,
  getSecurityAlert,
  listSecurityAlerts,
  startSecurityReview,
  viewSecurityRaw,
  watchSecurity,
  type SecAlert,
  type SecSeverity,
  type SecStatus,
  type SecType,
  type SecPage,
} from '../../api/security'
import titleOps from '../../assets/mascot/title-ops.webp'
import { USE_MOCK_INQUIRY } from '../../core/config'
import { formatDateTime } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { CountUp } from '../../ui/CountUp'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'
import { useToast } from '../../ui/useToast'
import { SortTh } from '../../ui/SortTh'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'

type Col = 'sev' | 'type' | 'status' | 'time' | 'target'
const SEV_RANK: Record<SecSeverity, number> = { 높음: 0, 중간: 1, 낮음: 2 }
const ST_RANK: Record<SecStatus, number> = { 신규: 0, '확인 중': 1, 종결: 2 }
const SORT_VAL: Record<Col, (a: SecAlert) => string | number> = {
  sev: (a) => SEV_RANK[a.severity],
  type: (a) => a.type,
  status: (a) => ST_RANK[a.status],
  time: (a) => Date.parse(a.at),
  target: (a) => a.name,
}

const sevBadge = (s: SecSeverity) => <StateBadge tone={s === '높음' ? 'urg' : s === '중간' ? 'warn' : 'recv'} label={s} />
const stBadge = (s: SecStatus) => <StateBadge tone={s === '신규' ? 'urg' : s === '확인 중' ? 'prog' : 'ok'} label={s} />

function Cell({ cls, label, n, hint }: { cls?: string; label: string; n: number; hint: string }) {
  return (
    <div className={`sgc${cls ? ` ${cls}` : ''}`}>
      <div className="small muted gl">{label}</div>
      <div className="v">
        <b>
          <CountUp value={n} />
        </b>
        <span>건</span>
      </div>
      <div className="small muted">{hint}</div>
    </div>
  )
}

export function SecurityView() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const statusCodes: Record<SecStatus, string> = { '신규': 'NEW', '확인 중': 'IN_REVIEW', '종결': 'CLOSED' }
  const status = (Object.keys(statusCodes) as SecStatus[]).find((s) => statusCodes[s] === params.get('status')) ?? (params.get('status') === 'ALL' ? '' : '신규')
  const setStatus = (value: SecStatus | '') => {
    const next = new URLSearchParams(params)
    if (value) next.set('status', statusCodes[value])
    else next.set('status', 'ALL')
    setParams(next, { replace: true })
  }
  const [type, setType] = useState<SecType | ''>('')
  const [sort, setSort] = useState<{ col: Col; dir: 'asc' | 'desc' } | null>({ col: 'time', dir: 'desc' })
  const [data, setData] = useState<SecPage | null>(null)
  const filterKey = params.toString()
  const [pageState, setPageState] = useState({ filterKey, value: 1 })
  const page = pageState.filterKey === filterKey ? pageState.value : 1
  const setPage = (value: number) => setPageState({ filterKey, value })
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const [openId, setOpenId] = useState<string | null>(null)
  const { say } = useToast()
  const admin = user?.serviceRole === 'ADMIN'

  useEffect(() => watchSecurity(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    listSecurityAlerts(user, { status, type, page }).then((r) => {
      if (!alive) return
      if (r.ok) {
        setData(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, status, type, page, tick])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const c = data?.counts
  const openN = (c?.신규 ?? 0) + (c?.['확인 중'] ?? 0)
  const onSort = (col: Col) => setSort((s) => (s?.col !== col ? { col, dir: 'asc' } : s.dir === 'asc' ? { col, dir: 'desc' } : null))
  const rows = data
    ? sort
        ? [...data.items].sort((a, b) => {
            const x = SORT_VAL[sort.col](a)
            const y = SORT_VAL[sort.col](b)
            return (x < y ? -1 : x > y ? 1 : 0) * (sort.dir === 'desc' ? -1 : 1)
          })
        : data.items
    : []

  return (
    <>
      <main className="main">
        <Topbar title="보안·감사 알림" sub="문의가 접수되지 않았어도 감지된 신호" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">
                SECURITY {USE_MOCK_INQUIRY && <span className="tag gray">시연 데이터</span>}
              </div>
              <h1>보안·감사 알림을 확인해요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                ITssue 내에서 발생한 이벤트만 보여줘요. 사내 보안 관제를 대체하지 않고, 티켓과도 별도로 관리해요.
              </p>
            </div>

            <div className="kpis k2">
              <div className="kpi grp">
                <div className="l">
                  미종결 <b className="gtot">{openN}</b>건
                </div>
                <div className="gcells">
                  <Cell cls={c?.신규 ? 'urg' : ''} label="신규" n={c?.신규 ?? 0} hint="확인 전" />
                  <Cell label="확인 중" n={c?.['확인 중'] ?? 0} hint="정보보안팀이 확인 시작" />
                  <Cell cls={c?.high ? 'urg' : ''} label="심각도 높음" n={c?.high ?? 0} hint="미종결 중 따로 센 수" />
                </div>
              </div>
              <div className="kpi grp">
                <div className="l">종결</div>
                <div className="gcells one">
                  <Cell label="종결된 알림" n={c?.종결 ?? 0} hint={`사유와 함께 · 전체 ${c?.total ?? 0}건 중`} />
                </div>
              </div>
            </div>

            <div className="alert info">
              <Icon name="shield" />
              <div>
                {USE_MOCK_INQUIRY ? <>민감정보를 가린 내용을 보여 드려요. 원문은 <b>사유를 입력</b>하면 볼 수 있고 열람 기록이 남아요.</> : <>검토가 필요한 신호예요. 사고나 위반이 확정된 것은 아니에요. 저장된 문의는 사유를 적어 열람하며, 비밀번호·인증번호 원문은 복구하지 않아요.</>}
              </div>
            </div>

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>{error}</div>
              </div>
            )}

            <div className="row">
              <div className="d2seg" role="group" aria-label="처리 상태">
                {(['', '신규', '확인 중', '종결'] as const).map((s) => (
                  <button key={s} type="button" className={status === s ? 'on' : ''} aria-pressed={status === s} onClick={() => { setStatus(s); setPage(1) }}>
                    {s || '전체'}
                  </button>
                ))}
              </div>
              <SelectBox
                id="sec-type"
                auto
                ariaLabel="유형"
                value={type}
                options={[{ value: '', label: '유형: 전체' }, ...SEC_TYPES.map((t) => ({ value: t, label: t }))]}
                onChange={(v) => { setType(v as SecType | ''); setPage(1) }}
              />
            </div>

            {(data?.totalPages ?? 1) > 1 && <div className="row" aria-label="알림 페이지">
              <button className="btn sec sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</button>
              <span>{page} / {data?.totalPages} 페이지 · 전체 {data?.totalCount}건</span>
              <button className="btn sec sm" disabled={page >= (data?.totalPages ?? 1)} onClick={() => setPage(page + 1)}>다음</button>
            </div>}
            <div className="panel" style={{ padding: '6px 10px' }} aria-live="polite">
              {!data ? (
                <div className="empty" role="status">
                  불러오는 중이에요…
                </div>
              ) : rows.length ? (
                <div className="tw">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <SortTh col="sev" label="심각도" sort={sort} onSort={onSort} />
                        <SortTh col="type" label="유형" sort={sort} onSort={onSort} />
                        <SortTh col="status" label="상태" sort={sort} onSort={onSort} />
                        <SortTh col="time" label="감지 시각" sort={sort} onSort={onSort} />
                        <SortTh col="target" label="대상" sort={sort} onSort={onSort} />
                        <th>
                          <span className="sr">상세</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((a) => (
                        <tr key={a.id} className={a.status === '종결' ? 'sdone' : undefined}>
                          <td>{sevBadge(a.severity)}</td>
                          <td>
                            <button type="button" className="lk" onClick={() => setOpenId(a.id)}>
                              {a.type}
                            </button>
                            <small>{a.mask}</small>
                          </td>
                          <td>{stBadge(a.status)}</td>
                          <td className="mono small">{formatDateTime(a.at)}</td>
                          <td>
                            {a.name}
                            <small className="mono">
                              {a.employeeNo} · {a.dept}
                            </small>
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <button type="button" className="btn ghost sm" onClick={() => setOpenId(a.id)} aria-label={`${a.type} ${a.id} 상세`}>
                              상세
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty">조건에 맞는 알림이 없어요.</div>
              )}
            </div>
          </div>
        </div>
      </main>
      {openId && <SecurityDialog id={openId} onClose={() => setOpenId(null)} onToast={say} />}
    </>
  )
}

function SecurityDialog({ id, onClose, onToast }: { id: string; onClose: () => void; onToast: (m: string) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [a, setA] = useState<SecAlert | null>(null)
  const [raw, setRaw] = useState<string | null>(null)
  const [why, setWhy] = useState('')
  const [whyErr, setWhyErr] = useState('')
  const [ending, setEnding] = useState(false)
  const [endWhy, setEndWhy] = useState('')
  const [endErr, setEndErr] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!user) return
    let alive = true
    getSecurityAlert(user, id).then((r) => {
      if (!alive) return
      if (r.ok) setA(r.data)
      else setErr(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, id])

  if (!user) return null
  if (!a) return <Modal title="보안·감사 알림" onClose={onClose}>{err ? <div className="ferr" role="alert">{err}</div> : <div className="empty" role="status">불러오는 중이에요…</div>}</Modal>

  const showRaw = async () => {
    if (!why.trim()) return setWhyErr('열람 사유를 입력해 주세요.')
    setBusy(true)
    const r = await viewSecurityRaw(user, id, why)
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    setRaw(r.data.raw)
    setA(r.data.alert)
  }
  const start = async () => {
    setBusy(true)
    const r = await startSecurityReview(user, id)
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    setA(r.data)
  }
  const end = async () => {
    if (!endWhy.trim()) return setEndErr('종결 사유를 입력해 주세요.')
    setBusy(true)
    const r = await closeSecurityAlert(user, id, endWhy)
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    onToast('종결했어요.')
    onClose()
  }

  if (ending)
    return (
      <Modal title="알림 종결" onClose={() => setEnding(false)}>
        <div className="field">
          <label htmlFor={`${uid}-e`}>종결 사유 (필수)</label>
          <input id={`${uid}-e`} className={`inp${endErr ? ' err' : ''}`} maxLength={500} aria-describedby={`${uid}-end-count`} value={endWhy} placeholder="예) 정상 문의로 확인" autoComplete="off" aria-invalid={!!endErr} onChange={(e) => { setEndWhy(e.target.value); setEndErr('') }} />
          <div className="wcnt" style={{ justifyContent: 'flex-end' }}>
            <span id={`${uid}-end-count`} className="hint">{endWhy.length}/500</span>
          </div>
          {endErr && (
            <div className="ferr" role="alert">
              {endErr}
            </div>
          )}
        </div>
        {err && (
          <div className="ferr" role="alert">
            {err}
          </div>
        )}
        <div className="acts">
          <button type="button" className="btn sec" onClick={() => setEnding(false)}>
            취소
          </button>
          <button type="button" className="btn pri" disabled={busy} onClick={() => void end()}>
            종결
          </button>
        </div>
      </Modal>
    )

  return (
    <Modal title={`${a.type} · ${a.id}`} onClose={onClose}>
      <div className="row">
        {sevBadge(a.severity)}
        <span className="small muted">
          {formatDateTime(a.at)} · {a.name} ({a.employeeNo})
        </span>
      </div>
      <dl className="dl">
        <dt>감지 규칙</dt>
        <dd>{a.rule}</dd>
        <dt>내용 (마스킹)</dt>
        <dd>{a.mask}</dd>
        {raw !== null && (
          <>
            <dt>{USE_MOCK_INQUIRY ? '원문 (열람 기록 남음)' : '저장된 문의 (비밀값 가림·열람 기록 남음)'}</dt>
            <dd>{raw}</dd>
          </>
        )}
      </dl>
      {raw === null && a.hasOriginal !== false && (
        <div className="field">
          <label htmlFor={`${uid}-w`}>{USE_MOCK_INQUIRY ? '원문 열람 사유 (필수)' : '문의 열람 사유 (필수)'}</label>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <input id={`${uid}-w`} className={`inp${whyErr ? ' err' : ''}`} maxLength={500} aria-describedby={`${uid}-raw-count`} value={why} placeholder="예) 정상 문의 여부 확인" autoComplete="off" aria-invalid={!!whyErr} onChange={(e) => { setWhy(e.target.value); setWhyErr('') }} />
            <button type="button" className="btn sec" disabled={busy} onClick={() => void showRaw()}>
              {USE_MOCK_INQUIRY ? '원문 보기' : '저장된 문의 보기'}
            </button>
          </div>
          <div className="wcnt" style={{ justifyContent: 'flex-end' }}>
            <span id={`${uid}-raw-count`} className="hint">{why.length}/500</span>
          </div>
          {whyErr && (
            <div className="ferr" role="alert">
              {whyErr}
            </div>
          )}
        </div>
      )}
      <div>
        <h4 style={{ marginBottom: 8 }}>처리 이력</h4>
        <ul className="tl">
          {a.log.map((h, i) => (
            <li key={i}>
              <Icon name="clock" />
              <div>
                <b>{h.what}</b>
                <small>
                  {formatDateTime(h.at)} · {h.who}
                </small>
              </div>
            </li>
          ))}
        </ul>
      </div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          닫기
        </button>
        {a.status === '신규' && (
          <button type="button" className="btn pri" disabled={busy} onClick={() => void start()}>
            확인 시작
          </button>
        )}
        {a.status === '확인 중' && (
          <button type="button" className="btn pri" onClick={() => setEnding(true)}>
            종결 (사유 입력)
          </button>
        )}
      </div>
    </Modal>
  )
}
