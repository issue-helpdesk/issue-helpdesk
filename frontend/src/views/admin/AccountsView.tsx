/**
 * 관리자 계정 관리 (/accounts). ITssue 서비스 이용 권한을 확인하고 바꾼다. (design/ITssue-Prototype.html viewAccounts)
 * 사번·이름 검색, 부서·역할·상태 걸러 보기, 계정 추가·정보 수정, 이용 제한·해제, 임시 비밀번호 발급.
 * 서버(US-01~05) 규칙: 관리자만, 사번·이메일 중복 불가, 역할·상태를 바꿀 때는 사유 필수, 내 계정의 역할·상태는 바꿀 수 없다.
 * 시안과 서버가 다른 곳(검색 범위, 부서·역할·상태 정렬, 이력 패널)은 api/users.ts 와 PR 본문에 적어 두었다.
 */
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { accountHistory, createUser, issueTempPassword, listDepartments, listUsers, recordAccountHistory, updateUser } from '../../api/users'
import type { Page } from '../../api/inquiries'
import type { AccountStatus, ApiFail, ServiceRole } from '../../api/types'
import type { AccountHistoryItem, Department, HistKind, UserSummary } from '../../api/userTypes'
import titleAcct from '../../assets/mascot/title-acct.webp'
import { formatDateTime } from '../../core/format'
import { HOME_BY_ROLE, ROLE_LABEL } from '../../core/roles'
import { useAuth } from '../../core/session'
import { FilterPill } from '../../ui/FilterPill'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { Pager } from '../../ui/Pager'
import { SortTh } from '../../ui/SortTh'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'

const PAGE_SIZE = 20
const ROLES: ServiceRole[] = ['EMPLOYEE', 'AGENT', 'ADMIN']

const STATUS_LABEL: Record<AccountStatus, string> = { ACTIVE: '정상', LOCKED: '잠김', INACTIVE: '이용 제한' }
const STATUS_TONE: Record<AccountStatus, string> = { ACTIVE: 'ok', LOCKED: 'warn', INACTIVE: 'urg' }
const TABS: { value: '' | AccountStatus; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'ACTIVE', label: '정상' },
  { value: 'LOCKED', label: '잠김' },
  { value: 'INACTIVE', label: '이용 제한' },
]

/** 정렬 열 → API sort 필드 (부서·역할·상태는 서버가 아직 받지 않는 시안용 임시 값, api/mock/users.ts 참고) */
const SORT_KEY = { employeeNo: 'employeeNo', name: 'name', dept: 'department', role: 'serviceRole', status: 'accountStatus' } as const
type SortCol = keyof typeof SORT_KEY

/** 이력 종류별 색: 이용 제한=빨강, 잠금·제한 해제=초록, 계정 수정=파랑, 계정 추가=청록, 그 밖은 회색 */
const HIST_TONE: Partial<Record<HistKind, string>> = { '이용 제한': 'urg', '잠금 해제': 'ok', '제한 해제': 'ok', '계정 수정': 'prog', '계정 추가': 're' }

/** 서버가 알려 준 입력 오류를 칸별 문구로 바꾼다 (해요체) */
const FIELD_TEXT: Record<string, string> = {
  employeeNo: '사번을 입력해 주세요.',
  name: '이름을 입력해 주세요.',
  email: '이메일을 입력해 주세요.',
  reason: '사유를 입력해 주세요.',
}
function fieldErrors(e: ApiFail['error']): Record<string, string> {
  const out: Record<string, string> = {}
  if (e.code === 'USER_EMPLOYEE_NO_DUPLICATE') out.employeeNo = '이미 등록된 사번이에요.'
  else if (e.code === 'USER_EMAIL_DUPLICATE') out.email = '이미 등록된 이메일이에요.'
  else if (e.code === 'USER_STATUS_REASON_REQUIRED') out.reason = '사유를 입력해 주세요.'
  for (const d of e.details ?? []) {
    if (!d.field || out[d.field]) continue
    if (d.reason === 'REQUIRED') out[d.field] = FIELD_TEXT[d.field] ?? '값을 입력해 주세요.'
    else if (d.reason === 'INVALID_FORMAT' && d.field === 'email') out.email = '이메일 형식이 올바르지 않아요.'
    else if (d.reason === 'DUPLICATE') out[d.field] = d.field === 'email' ? '이미 등록된 이메일이에요.' : '이미 등록된 값이에요.'
    else if (d.reason === 'NOT_FOUND' && d.field === 'departmentId') out.departmentId = '없는 부서예요. 목록을 새로 불러와 주세요.'
    else out[d.field] = d.message
  }
  return out
}
/** 칸에 붙일 수 없는 오류의 문구 */
function generalError(e: ApiFail['error']): string {
  if (e.code === 'FORBIDDEN') return '관리자만 할 수 있어요.'
  if (e.code === 'USER_NOT_FOUND') return '사용자를 찾을 수 없어요. 목록을 새로 불러온 뒤 다시 시도해 주세요.'
  if (e.code === 'USER_SELF_CHANGE_NOT_ALLOWED') return '내 계정의 권한과 상태는 바꿀 수 없어요.'
  return e.message
}

type Dialog =
  | { kind: 'restrict' | 'release'; u: UserSummary }
  | { kind: 'pw'; u: UserSummary }
  | { kind: 'add' }
  | { kind: 'edit'; u: UserSummary }
  | { kind: 'tmp'; name: string; employeeNo: string; pw: string; mode: 'create' | 'reissue' }

export function AccountsView() {
  const { user } = useAuth()
  const [q, setQ] = useState('')
  const [dept, setDept] = useState('')
  const [role, setRole] = useState<ServiceRole | ''>('')
  const [tab, setTab] = useState<'' | AccountStatus>('')
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' } | null>(null)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<UserSummary> | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [counts, setCounts] = useState<Record<AccountStatus, number> | null>(null)
  const [depts, setDepts] = useState<Department[]>([])
  const [hist, setHist] = useState<AccountHistoryItem[]>(() => accountHistory())
  const [dialog, setDialog] = useState<Dialog | null>(null)

  useEffect(() => {
    if (!user || user.serviceRole !== 'ADMIN') return
    let alive = true
    listUsers(user, {
      page,
      size: PAGE_SIZE,
      sort: sort ? `${SORT_KEY[sort.col]},${sort.dir}` : 'name,asc',
      q: q.trim() || undefined,
      departmentId: dept ? Number(dept) : undefined,
      serviceRole: role ? [role] : undefined,
      accountStatus: tab ? [tab] : undefined,
    }).then((r) => {
      if (!alive) return
      if (r.ok) {
        setData(r.data)
        setError('')
      } else setError(generalError(r.error))
    })
    return () => {
      alive = false
    }
  }, [user, page, sort, q, dept, role, tab, reload])

  // 상태 칸의 건수: 서버 목록 응답에 상태별 건수가 없어서 상태마다 1건씩 요청해 총건수만 읽는다
  useEffect(() => {
    if (!user || user.serviceRole !== 'ADMIN') return
    let alive = true
    const states: AccountStatus[] = ['ACTIVE', 'LOCKED', 'INACTIVE']
    Promise.all(states.map((s) => listUsers(user, { size: 1, accountStatus: [s] }))).then((rs) => {
      if (!alive || rs.some((r) => !r.ok)) return
      const c = { ACTIVE: 0, LOCKED: 0, INACTIVE: 0 }
      rs.forEach((r, i) => r.ok && (c[states[i]] = r.data.totalCount))
      setCounts(c)
    })
    return () => {
      alive = false
    }
  }, [user, reload])

  useEffect(() => {
    let alive = true
    listDepartments().then((r) => alive && r.ok && setDepts(r.data))
    return () => {
      alive = false
    }
  }, [])

  const items = useMemo(() => data?.items ?? [], [data])
  // 부서 목록 API 가 아직 없으면 지금 목록에서 본 부서로 대신한다
  const deptOptions = useMemo(() => {
    // 서버는 상위 조직(사업부)도 함께 주므로, 사용자가 속한 가장 아래 부서만 고르게 한다 (RF-05: 트리는 프론트가 구성)
    if (depts.length) return depts.filter((d) => !depts.some((x) => x.parentId === d.id)).map((d) => ({ id: d.id, name: d.name }))
    const seen = new Map<number, string>()
    items.forEach((u) => u.department && seen.set(u.department.id, u.department.name))
    return [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, 'ko'))
  }, [depts, items])

  if (user && user.serviceRole !== 'ADMIN') return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const onSort = (col: SortCol) => {
    setSort((s) => (s && s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' }))
    setPage(1)
  }
  const done = () => {
    setDialog(null)
    setHist(accountHistory())
    setReload((n) => n + 1)
  }
  const total = counts ? counts.ACTIVE + counts.LOCKED + counts.INACTIVE : null

  return (
    <main className="main">
      <Topbar title="계정 관리" sub="ITssue 서비스 이용 권한" lead={<img className="tti" src={titleAcct} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div>
            <div className="eyebrow">ACCOUNTS</div>
            <h1>서비스 이용 권한을 관리해요</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              ITssue 서비스 이용 권한을 확인하고 바꿀 수 있어요.
            </p>
          </div>

          <div className="alert info">
            <Icon name="shield" />
            <div>
              여기서 관리하는 것은 <b>ITssue 이용 권한</b>이에요. 사내 시스템의 실제 접근권한 승인은 별도 절차이고, ITssue 접수가 이를 대신하지 않아요. 회원가입 기능은 없고, 신규 입사자는 관리자가 계정을 만들어 제공해요.
            </div>
          </div>

          <div className="d2f">
            <label className={`srch${q.trim() ? ' f' : ''}`}>
              <Icon name="search" size={18} />
              <input
                value={q}
                placeholder="이름·사번·부서 검색"
                aria-label="계정 검색"
                autoComplete="off"
                onChange={(e) => {
                  setQ(e.target.value)
                  setPage(1)
                }}
              />
              {q && (
                <button type="button" className="x" aria-label="검색어 지우기" onClick={() => { setQ(''); setPage(1) }}>
                  ✕
                </button>
              )}
            </label>
            <FilterPill label="부서" value={dept} options={deptOptions.map((d) => ({ value: String(d.id), label: d.name }))} onChange={(v) => { setDept(v); setPage(1) }} />
            <FilterPill label="역할" value={role} options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} onChange={(v) => { setRole(v as ServiceRole | ''); setPage(1) }} />
            <button type="button" className="btn pri fr" onClick={() => setDialog({ kind: 'add' })}>
              <Icon name="plus" />
              계정 추가
            </button>
          </div>

          <div className="d2seg" role="group" aria-label="상태">
            {TABS.map((t) => (
              <button key={t.value} type="button" className={tab === t.value ? 'on' : ''} aria-pressed={tab === t.value} onClick={() => { setTab(t.value); setPage(1) }}>
                {t.label} {counts && <em>{t.value ? counts[t.value] : total}</em>}
              </button>
            ))}
          </div>

          <div className="panel" style={{ padding: '6px 10px' }} aria-live="polite">
            {error ? (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                    다시 시도
                  </button>
                </div>
              </div>
            ) : data === null ? (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            ) : items.length ? (
              <>
                <div className="tw">
                  <table className="tbl atbl">
                    <colgroup>
                      <col style={{ width: '10%' }} />
                      <col style={{ width: '12%' }} />
                      <col style={{ width: '15%' }} />
                      <col style={{ width: '9%' }} />
                      <col style={{ width: '10%' }} />
                      <col style={{ width: '15%' }} />
                      <col style={{ width: '14%' }} />
                      <col style={{ width: '15%' }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <SortTh col="employeeNo" label="사번" sort={sort} onSort={onSort} />
                        <SortTh col="name" label="이름" sort={sort} onSort={onSort} />
                        <SortTh col="dept" label="부서" sort={sort} onSort={onSort} />
                        <SortTh col="role" label="역할" sort={sort} onSort={onSort} />
                        <SortTh col="status" label="상태" sort={sort} onSort={onSort} />
                        <th>이용 제한·해제</th>
                        <th>비밀번호</th>
                        <th>계정 정보</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((u) => (
                        <tr key={u.id}>
                          <td className="mono small">{u.employeeNo}</td>
                          <td>
                            <b>{u.name}</b>
                          </td>
                          <td>{u.department?.name ?? '-'}</td>
                          <td>{ROLE_LABEL[u.serviceRole]}</td>
                          <td>
                            <StateBadge tone={STATUS_TONE[u.accountStatus]} label={STATUS_LABEL[u.accountStatus]} />
                          </td>
                          <td>
                            {u.accountStatus === 'ACTIVE' && u.id !== user.id && (
                              <button type="button" className="btn ghost sm dng" onClick={() => setDialog({ kind: 'restrict', u })}>
                                이용 제한
                              </button>
                            )}
                            {u.accountStatus === 'INACTIVE' && (
                              <button type="button" className="btn ghost sm okc" onClick={() => setDialog({ kind: 'release', u })}>
                                제한 해제
                              </button>
                            )}
                            {u.accountStatus === 'LOCKED' && (
                              <button type="button" className="btn ghost sm wrc" onClick={() => setDialog({ kind: 'release', u })}>
                                잠금 해제
                              </button>
                            )}
                          </td>
                          <td>
                            <button type="button" className="btn ghost sm" onClick={() => setDialog({ kind: 'pw', u })}>
                              임시 비밀번호 발급
                            </button>
                          </td>
                          <td>
                            <button type="button" className="btn ghost sm" onClick={() => setDialog({ kind: 'edit', u })}>
                              수정
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager page={data.page} size={data.size} total={data.totalCount} onPage={setPage} />
              </>
            ) : (
              <div className="empty">조건에 맞는 계정이 없어요.</div>
            )}
          </div>

          <div className="panel">
            <h3>
              이용 제한·해제 이력 <span className="small muted" style={{ fontWeight: 400 }}>이 화면에서 처리한 최근 {Math.min(hist.length, 12)}건</span>
            </h3>
            {hist.length ? (
              <ul className="hlist">
                {hist.slice(0, 12).map((h) => (
                  <li key={h.id}>
                    <span className={`hd ${HIST_TONE[h.what] ?? 'gray'}`} />
                    <div>
                      <b>{h.target}</b> <StateBadge tone={HIST_TONE[h.what] ?? 'recv'} label={h.what} />
                      <small>
                        {h.why} · {h.who} · {formatDateTime(h.at)}
                      </small>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="empty">아직 이력이 없어요.</div>
            )}
          </div>
        </div>
      </div>

      {dialog && (dialog.kind === 'restrict' || dialog.kind === 'release') && <StatusDialog kind={dialog.kind} u={dialog.u} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === 'pw' && <PasswordIssueDialog u={dialog.u} onClose={() => setDialog(null)} onIssued={(pw) => { done(); setDialog({ kind: 'tmp', name: dialog.u.name, employeeNo: dialog.u.employeeNo, pw, mode: 'reissue' }) }} />}
      {dialog?.kind === 'add' && <AddDialog depts={deptOptions} onClose={() => setDialog(null)} onCreated={(u, pw) => { done(); setDialog({ kind: 'tmp', name: u.name, employeeNo: u.employeeNo, pw, mode: 'create' }) }} />}
      {dialog?.kind === 'edit' && <EditDialog u={dialog.u} depts={deptOptions} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === 'tmp' && <TempPasswordDialog name={dialog.name} employeeNo={dialog.employeeNo} pw={dialog.pw} mode={dialog.mode} onClose={() => setDialog(null)} />}
    </main>
  )
}

/* ------------------------------------------------------------------ 창 공통 */
function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: (a: { id: string; 'aria-invalid': boolean; 'aria-describedby'?: string }) => ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-invalid': !!error, 'aria-describedby': error ? `${id}-e` : undefined })}
      {error && (
        <div className="ferr" id={`${id}-e`} role="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ 이용 제한 · 제한 해제 · 잠금 해제 */
function StatusDialog({ kind, u, onClose, onDone }: { kind: 'restrict' | 'release'; u: UserSummary; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [why, setWhy] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const locked = u.accountStatus === 'LOCKED'
  const submit = async () => {
    if (!user) return
    if (!why.trim()) return setErr('사유를 입력해 주세요.')
    setBusy(true)
    const r = await updateUser(user, u.id, { accountStatus: kind === 'restrict' ? 'INACTIVE' : 'ACTIVE', reason: why.trim() })
    setBusy(false)
    if (!r.ok) return setErr(fieldErrors(r.error).reason ?? generalError(r.error))
    recordAccountHistory({ who: user.name, target: `${u.employeeNo} · ${u.name}`, what: kind === 'restrict' ? '이용 제한' : locked ? '잠금 해제' : '제한 해제', why: why.trim() })
    onDone()
  }
  return (
    <Modal title={kind === 'release' ? '제한·잠금 해제' : '이용 제한'} onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {u.name} ({u.employeeNo}) · {kind === 'restrict' ? '이 계정은 로그인할 수 없게 돼요.' : locked ? '잠금을 풀면 바로 로그인할 수 있어요.' : '제한을 풀면 다시 로그인할 수 있어요.'}
      </p>
      <Field id={`${uid}-w`} label="사유 (필수)" error={err}>
        {(a) => <input {...a} className={`inp${err ? ' err' : ''}`} value={why} autoComplete="off" onChange={(e) => { setWhy(e.target.value); setErr('') }} />}
      </Field>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          확인
        </button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ 임시 비밀번호 발급 */
function PasswordIssueDialog({ u, onClose, onIssued }: { u: UserSummary; onClose: () => void; onIssued: (pw: string) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [why, setWhy] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!user) return
    setBusy(true)
    const r = await issueTempPassword(user, u.id, why.trim() || undefined)
    setBusy(false)
    if (!r.ok) return setErr(generalError(r.error))
    recordAccountHistory({ who: user.name, target: `${u.employeeNo} · ${u.name}`, what: '임시 비밀번호 재발급', why: why.trim() ? `${why.trim()}${u.accountStatus === 'LOCKED' ? ' · 잠금 해제' : ''}` : u.accountStatus === 'LOCKED' ? '잠금 해제' : '-' })
    onIssued(r.data.temporaryPassword)
  }
  return (
    <Modal title="임시 비밀번호 재발급" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {u.name} ({u.employeeNo})님에게 임시 비밀번호를 새로 발급해요. 지금 쓰는 비밀번호는 쓸 수 없고 모든 로그인이 끊겨요. 잠긴 계정이면 잠금도 풀려요.
        <br />
        발급하면 임시 비밀번호가 <b>한 번만</b> 보여요. 안전한 방법으로 전달해 주세요.
      </p>
      <Field id={`${uid}-w`} label="발급 사유 (선택)" error={err}>
        {(a) => <input {...a} className="inp" value={why} placeholder="예) 비밀번호를 잊어 서비스데스크로 요청" autoComplete="off" onChange={(e) => setWhy(e.target.value)} />}
      </Field>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          발급
        </button>
      </div>
    </Modal>
  )
}

function TempPasswordDialog({ name, employeeNo, pw, mode, onClose }: { name: string; employeeNo: string; pw: string; mode: 'create' | 'reissue'; onClose: () => void }) {
  return (
    <Modal title={mode === 'create' ? '임시 비밀번호를 발급했어요' : '임시 비밀번호를 다시 발급했어요'} dismissible={false}>
      <p style={{ margin: 0, lineHeight: '24px' }}>
        {name} ({employeeNo})님에게 아래 임시 비밀번호를 <b>안전한 방법으로 전달</b>해 주세요. 이 창을 닫으면 다시 볼 수 없어요.
      </p>
      <div className="tmpbox mono" aria-label="임시 비밀번호">
        {pw}
      </div>
      <p className="hint" style={{ margin: 0 }}>
        {mode === 'create' ? '첫 로그인에서 새 비밀번호를 정해야 해요.' : '지금 쓰던 비밀번호는 쓸 수 없고 모든 로그인이 끊겼어요. 잠긴 계정이었다면 잠금도 풀렸어요. 로그인하면 새 비밀번호를 정해야 해요.'}
      </p>
      <div className="acts">
        <button type="button" className="btn pri" onClick={onClose}>
          확인
        </button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ 계정 추가 */
function AddDialog({ depts, onClose, onCreated }: { depts: { id: number; name: string }[]; onClose: () => void; onCreated: (u: UserSummary, pw: string) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [f, setF] = useState({ employeeNo: '', name: '', email: '', departmentId: '', position: '', serviceRole: 'EMPLOYEE' as ServiceRole })
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [general, setGeneral] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (v: string) => {
    setF((x) => ({ ...x, [k]: v }))
    setErrs((e) => ({ ...e, [k]: '' }))
  }
  const submit = async () => {
    if (!user) return
    const e: Record<string, string> = {}
    if (!f.employeeNo.trim()) e.employeeNo = FIELD_TEXT.employeeNo
    if (!f.name.trim()) e.name = FIELD_TEXT.name
    if (!f.email.trim()) e.email = FIELD_TEXT.email
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) e.email = '이메일 형식이 올바르지 않아요.'
    if (Object.keys(e).length) return setErrs(e)
    setBusy(true)
    const r = await createUser(user, {
      employeeNo: f.employeeNo.trim().toUpperCase(),
      name: f.name.trim(),
      email: f.email.trim(),
      departmentId: f.departmentId ? Number(f.departmentId) : null,
      position: f.position.trim() || null,
      serviceRole: f.serviceRole,
    })
    setBusy(false)
    if (!r.ok) {
      const fe = fieldErrors(r.error)
      if (Object.keys(fe).length) setErrs(fe)
      else setGeneral(generalError(r.error))
      return
    }
    recordAccountHistory({ who: user.name, target: `${r.data.user.employeeNo} · ${r.data.user.name}`, what: '계정 추가', why: `신규 등록 (${ROLE_LABEL[f.serviceRole]}) · 임시 비밀번호 발급` })
    onCreated(r.data.user, r.data.temporaryPassword)
  }
  return (
    <Modal title="계정 추가" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        회원가입 기능은 없어요. 계정을 만들면 임시 비밀번호가 발급돼요. 이 비밀번호는 만든 직후 한 번만 볼 수 있고, 사용자는 첫 로그인에서 새 비밀번호를 정해요.
      </p>
      <Field id={`${uid}-i`} label="사번" error={errs.employeeNo}>
        {(a) => <input {...a} className={`inp${errs.employeeNo ? ' err' : ''}`} value={f.employeeNo} autoComplete="off" onChange={(e) => set('employeeNo')(e.target.value)} />}
      </Field>
      <Field id={`${uid}-n`} label="이름" error={errs.name}>
        {(a) => <input {...a} className={`inp${errs.name ? ' err' : ''}`} value={f.name} autoComplete="off" onChange={(e) => set('name')(e.target.value)} />}
      </Field>
      <Field id={`${uid}-e`} label="이메일" error={errs.email}>
        {(a) => <input {...a} className={`inp${errs.email ? ' err' : ''}`} type="email" value={f.email} placeholder="예) name@itssue.example" autoComplete="off" onChange={(e) => set('email')(e.target.value)} />}
      </Field>
      <Field id={`${uid}-d`} label="부서" error={errs.departmentId}>
        {(a) => (
          <select {...a} className="sel" value={f.departmentId} onChange={(e) => set('departmentId')(e.target.value)}>
            <option value="">선택 안 함</option>
            {depts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field id={`${uid}-p`} label="직급 (선택)" error={errs.position}>
        {(a) => <input {...a} className="inp" value={f.position} placeholder="예) 팀원" autoComplete="off" onChange={(e) => set('position')(e.target.value)} />}
      </Field>
      <Field id={`${uid}-r`} label="역할">
        {(a) => (
          <select {...a} className="sel" value={f.serviceRole} onChange={(e) => set('serviceRole')(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        )}
      </Field>
      {general && (
        <div className="ferr" role="alert">
          {general}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          추가
        </button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ 계정 정보 수정 */
function EditDialog({ u, depts, onClose, onDone }: { u: UserSummary; depts: { id: number; name: string }[]; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth()
  const uid = useId()
  const [f, setF] = useState({ name: u.name, email: u.email, departmentId: u.department ? String(u.department.id) : '', serviceRole: u.serviceRole as ServiceRole, reason: '' })
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [general, setGeneral] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (v: string) => {
    setF((x) => ({ ...x, [k]: v }))
    setErrs((e) => ({ ...e, [k]: '' }))
  }
  const submit = async () => {
    if (!user) return
    const roleChanged = f.serviceRole !== u.serviceRole
    const e: Record<string, string> = {}
    if (!f.name.trim()) e.name = FIELD_TEXT.name
    if (!f.email.trim()) e.email = FIELD_TEXT.email
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) e.email = '이메일 형식이 올바르지 않아요.'
    if (roleChanged && !f.reason.trim()) e.reason = '역할을 바꿀 때는 사유를 입력해 주세요.'
    if (Object.keys(e).length) return setErrs(e)
    // 바뀐 것만 보낸다
    const body: Parameters<typeof updateUser>[2] = {}
    if (f.name.trim() !== u.name) body.name = f.name.trim()
    if (f.email.trim() !== u.email) body.email = f.email.trim()
    if ((f.departmentId ? Number(f.departmentId) : null) !== (u.department?.id ?? null)) body.departmentId = f.departmentId ? Number(f.departmentId) : null
    if (roleChanged) {
      body.serviceRole = f.serviceRole
      body.reason = f.reason.trim()
    }
    if (!Object.keys(body).length) return onClose()
    setBusy(true)
    const r = await updateUser(user, u.id, body)
    setBusy(false)
    if (!r.ok) {
      const fe = fieldErrors(r.error)
      if (Object.keys(fe).length) setErrs(fe)
      else setGeneral(generalError(r.error))
      return
    }
    recordAccountHistory({ who: user.name, target: `${u.employeeNo} · ${f.name.trim()}`, what: '계정 수정', why: f.reason.trim() || '정보 수정' })
    onDone()
  }
  return (
    <Modal title="계정 정보 수정" variant="form" onClose={onClose}>
      <div className="pfl">
        <span className="pf">{u.name.slice(-2)}</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{u.name}</div>
          <div className="small muted">
            {u.department?.name ?? '-'} · {ROLE_LABEL[u.serviceRole]}
          </div>
        </div>
      </div>
      <dl className="dl" style={{ margin: 0 }}>
        <dt>사번</dt>
        <dd>{u.employeeNo}</dd>
        <dt>상태</dt>
        <dd>{STATUS_LABEL[u.accountStatus]}</dd>
      </dl>
      <div className="pws" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <b style={{ fontSize: 14 }}>수정할 정보</b>
        <Field id={`${uid}-n`} label="이름" error={errs.name}>
          {(a) => <input {...a} className={`inp${errs.name ? ' err' : ''}`} value={f.name} autoComplete="off" onChange={(e) => set('name')(e.target.value)} />}
        </Field>
        <Field id={`${uid}-e`} label="이메일" error={errs.email}>
          {(a) => <input {...a} className={`inp${errs.email ? ' err' : ''}`} type="email" value={f.email} autoComplete="off" onChange={(e) => set('email')(e.target.value)} />}
        </Field>
        <Field id={`${uid}-d`} label="부서" error={errs.departmentId}>
          {(a) => (
            <select {...a} className="sel" value={f.departmentId} onChange={(e) => set('departmentId')(e.target.value)}>
              <option value="">선택 안 함</option>
              {depts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field id={`${uid}-r`} label="역할">
          {(a) => (
            <select {...a} className="sel" value={f.serviceRole} disabled={u.id === user?.id} onChange={(e) => set('serviceRole')(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field id={`${uid}-w`} label="변경 사유 (역할을 바꿀 때만 필수)" error={errs.reason}>
          {(a) => <input {...a} className={`inp${errs.reason ? ' err' : ''}`} value={f.reason} placeholder="예) 업무 변경으로 담당자 권한 부여" autoComplete="off" onChange={(e) => set('reason')(e.target.value)} />}
        </Field>
      </div>
      {general && (
        <div className="ferr" role="alert">
          {general}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          저장
        </button>
      </div>
    </Modal>
  )
}

