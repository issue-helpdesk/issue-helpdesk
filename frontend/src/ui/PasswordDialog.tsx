/**
 * 비밀번호 창: "새 비밀번호를 정해 주세요"(임시 비밀번호 직후)와 "내 프로필"(사이드바 프로필에서 연다)을 한 창으로 쓴다.
 *
 * - forced: 임시 비밀번호로 로그인한 상태. 서버가 다른 기능을 모두 막으므로 ✕·Esc·바깥 누르기로 닫을 수 없고 로그아웃만 할 수 있다.
 * - 아니면 내 정보를 읽기 전용으로 보여 주고, [변경]을 누르면 같은 자리에서 비밀번호 변경 입력칸이 펼쳐진다.
 * - 비밀번호를 바꾸면 서버가 모든 로그인을 끊으므로, 변경 완료 안내 뒤에는 로그인 화면으로만 간다. (AU-04)
 * 검사 순서는 현재 비밀번호 입력 → 비밀번호 규칙(위반이 여럿이면 모두) → 확인 입력이다. 현재 비밀번호가 맞는지는 서버가 판단한다.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { checkPassword, PASSWORD_RULE } from '../core/password'
import { ROLE_LABEL } from '../core/roles'
import { useAuth } from '../core/session'
import { Icon } from './Icon'
import { Modal } from './Modal'

type Field = 'cur' | 'nw' | 'cf'

export function PasswordDialog({ forced, onClose }: { forced: boolean; onClose: () => void }) {
  const { user, changePassword, logout } = useAuth()
  const navigate = useNavigate()
  const [edit, setEdit] = useState(false)
  const [cur, setCur] = useState('')
  const [nw, setNw] = useState('')
  const [cf, setCf] = useState('')
  const [errors, setErrors] = useState<Partial<Record<Field, string[]>>>({})
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  // 오류가 생기면 그 칸으로, 입력칸이 펼쳐지면 첫 칸으로 초점을 옮긴다
  const firstError = (['cur', 'nw', 'cf'] as const).find((k) => errors[k])
  useEffect(() => {
    if (firstError) document.getElementById(`pw-${firstError}`)?.focus()
  }, [firstError, errors])
  useEffect(() => {
    if (edit) document.getElementById('pw-cur')?.focus()
  }, [edit])

  if (!user) return null

  /** 로그인 화면으로 돌아간다. 비밀번호를 바꾼 뒤라면 그 안내를 함께 보여 준다. (뒤로가기로 돌아오지 못하게 replace) */
  function leave(changed: boolean) {
    logout(changed ? 'pw-changed' : undefined)
    navigate('/login', { replace: true })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy || !user) return
    const next: Partial<Record<Field, string[]>> = {}
    if (!cur) next.cur = ['현재 비밀번호를 입력해 주세요.']
    else {
      const rules = checkPassword(nw, cur, user.employeeNo)
      if (rules.length) next.nw = rules.map((r) => r.message)
      else if (cf !== nw) next.cf = ['새 비밀번호가 서로 달라요.']
    }
    setErrors(next)
    if (Object.keys(next).length) return

    setBusy(true)
    const r = await changePassword({ currentPassword: cur, newPassword: nw })
    setBusy(false)
    if (r.ok) {
      setDone(true)
      return
    }
    if (r.error.code === 'AUTH_CURRENT_PASSWORD_MISMATCH') setErrors({ cur: ['현재 비밀번호가 맞지 않아요.'] })
    else if (r.error.code === 'AUTH_PASSWORD_POLICY_VIOLATION') setErrors({ nw: (r.error.details ?? []).map((d) => d.message) })
    else setErrors({ cf: [r.error.message] })
  }

  const field = (k: Field, label: string, placeholder: string, value: string, set: (v: string) => void, auto: string) => {
    const errs = errors[k]
    return (
      <div className="field">
        <label htmlFor={`pw-${k}`}>{label}</label>
        <input
          className={`inp${errs ? ' err' : ''}`}
          id={`pw-${k}`}
          type="password"
          autoComplete={auto}
          placeholder={placeholder}
          value={value}
          readOnly={busy}
          onChange={(e) => {
            set(e.target.value)
            if (errs) setErrors((p) => ({ ...p, [k]: undefined }))
          }}
          aria-invalid={!!errs}
          aria-describedby={errs ? `pw-${k}-err` : undefined}
        />
        {errs && (
          <div className="errtx" id={`pw-${k}-err`} role="alert">
            {errs.map((m, i) => (
              <div key={i}>{m}</div>
            ))}
          </div>
        )}
      </div>
    )
  }

  const fields = (
    <>
      {field('cur', '현재 비밀번호', '임시 비밀번호 또는 지금 쓰는 비밀번호', cur, setCur, 'current-password')}
      {field('nw', '새 비밀번호', '새 비밀번호', nw, setNw, 'new-password')}
      <div className="hint" style={{ marginTop: -6 }}>
        {PASSWORD_RULE}
      </div>
      {field('cf', '새 비밀번호 확인', '한 번 더 입력해 주세요', cf, setCf, 'new-password')}
    </>
  )

  if (done) {
    return (
      <Modal key="done" title="비밀번호 변경" variant="form" dismissible={false}>
        <div className="alert ok">
          <Icon name="check" />
          <div>
            <b>비밀번호를 바꿨어요.</b>
            <br />
            보안을 위해 모든 기기에서 로그아웃돼요. 새 비밀번호로 다시 로그인해 주세요.
          </div>
        </div>
        <div className="acts">
          <button type="button" className="btn pri" onClick={() => leave(true)}>
            로그인 화면으로
          </button>
        </div>
      </Modal>
    )
  }

  if (forced) {
    return (
      <Modal key="forced" title="새 비밀번호를 정해 주세요" variant="form" dismissible={false}>
        <p className="muted small" style={{ margin: '-4px 0 0', lineHeight: '21px' }}>
          임시 비밀번호로 로그인했어요. 새 비밀번호를 정한 뒤에 ITssue를 쓸 수 있어요.
        </p>
        <form onSubmit={onSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {fields}
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => leave(false)}>
              로그아웃
            </button>
            <button type="submit" className="btn pri" aria-disabled={busy}>
              비밀번호 변경
            </button>
          </div>
        </form>
      </Modal>
    )
  }

  const days = user.passwordChangedDaysAgo
  return (
    <Modal key="profile" title="내 프로필" variant="form" closeButton onClose={onClose}>
      <div className="pfl">
        <span className="pf">{user.name.slice(-2)}</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{user.name}</div>
          <div className="small muted">
            {user.departmentName} · {ROLE_LABEL[user.serviceRole]}
          </div>
        </div>
      </div>
      <dl className="dl" style={{ margin: 0 }}>
        <dt>사번</dt>
        <dd>{user.employeeNo}</dd>
        <dt>부서</dt>
        <dd>{user.departmentName}</dd>
        <dt>역할</dt>
        <dd>{ROLE_LABEL[user.serviceRole]}</dd>
      </dl>
      {edit ? (
        <form className="pws" onSubmit={onSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <b style={{ fontSize: 14 }}>비밀번호 변경</b>
          {fields}
          <div className="acts">
            <button
              type="button"
              className="btn sec"
              onClick={() => {
                setEdit(false)
                setCur('')
                setNw('')
                setCf('')
                setErrors({})
              }}
            >
              취소
            </button>
            <button type="submit" className="btn pri" aria-disabled={busy}>
              변경
            </button>
          </div>
        </form>
      ) : (
        <div className="pws" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
          <div>
            <b style={{ fontSize: 14 }}>비밀번호</b>
            {/* 서버가 주는 값이 문서에 없어 제안으로 둔다 */}
            {days !== undefined && (
              <div className="small muted">
                마지막 변경 후 {days}일 <span className="tag gray">제안</span>
              </div>
            )}
          </div>
          <button type="button" className="btn sec sm" onClick={() => setEdit(true)}>
            변경
          </button>
        </div>
      )}
    </Modal>
  )
}
