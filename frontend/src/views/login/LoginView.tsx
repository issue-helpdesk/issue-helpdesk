/**
 * 로그인 화면.
 *
 * 왼쪽: 사번 로그인 / SSO 로그인 탭과 시연용 바로 로그인. 오른쪽: 로그인 전 상담 패널.
 * 로그인에 성공하면 역할별 첫 화면(core/roles.ts)으로 이동한다.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { MOCK_PASSWORD, MOCK_QUICK_LOGINS, MOCK_TEMP_PASSWORD } from '../../api/mock/accounts'
import type { ApiResult, LoginData } from '../../api/types'
import { USE_MOCK_AUTH } from '../../core/config'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Logo } from '../../ui/Logo'
import { Mascot } from '../../ui/Mascot'
import { ThemeSwitch } from '../../ui/ThemeSwitch'
import { ConsultPanel } from './ConsultPanel'
import { ForgotModal } from './ForgotModal'

type Tab = 'id' | 'sso'

/** 로그인 화면 오른쪽 아래의 주황 번짐 배경 (장식이라 스크린리더에는 숨긴다) */
function LoginBackground() {
  return (
    <svg className="bgsvg" width="100%" height="100%" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <linearGradient id="lbA" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FFC9A0" stopOpacity="0" />
          <stop offset="1" stopColor="#FF8FB8" stopOpacity=".35" />
        </linearGradient>
        <linearGradient id="lbB" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFD9BC" stopOpacity=".2" />
          <stop offset="1" stopColor="#FFB0CF" stopOpacity=".7" />
        </linearGradient>
        <radialGradient id="lbC" cx=".5" cy="1" r=".9">
          <stop offset="0" stopColor="#FF8FB8" stopOpacity=".55" />
          <stop offset="1" stopColor="#FF8FB8" stopOpacity="0" />
        </radialGradient>
      </defs>
      <polygon points="760,0 1440,0 1440,520 1120,900 560,900" fill="url(#lbA)" />
      <ellipse cx="1010" cy="930" rx="520" ry="340" fill="url(#lbB)" opacity=".85" />
      <ellipse cx="1330" cy="900" rx="380" ry="260" fill="url(#lbB)" />
      <ellipse cx="900" cy="960" rx="760" ry="300" fill="url(#lbC)" />
    </svg>
  )
}

export function LoginView() {
  const { user, loading, loginNote, login, loginSso, mockQuickLogin } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('id')
  // 시연(mock)일 때만 입력칸을 미리 채워 둔다
  const [employeeNo, setEmployeeNo] = useState(USE_MOCK_AUTH ? 'EMP-1001' : '')
  const [pwFocus, setPwFocus] = useState(false)
  const [password, setPassword] = useState(USE_MOCK_AUTH ? MOCK_PASSWORD : '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // 어느 버튼으로 요청 중인지(그 버튼에만 "로그인 중"을 보인다)와, 3초 넘게 걸리는지
  const [who, setWho] = useState('')
  const [slow, setSlow] = useState(false)
  // 비밀번호를 잊으셨나요? 안내 창
  const [forgotOpen, setForgotOpen] = useState(false)

  // 요청이 3초 넘게 걸리면 늦어진다고 알린다
  useEffect(() => {
    if (!busy) return
    const t = setTimeout(() => setSlow(true), 3000)
    return () => clearTimeout(t)
  }, [busy])

  // 이미 로그인한 상태로 이 화면에 오면 첫 화면으로 보낸다
  if (!loading && user) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />

  /** 로그인 요청을 실행하고, 성공이면 이동, 실패면 사유를 보여 준다. */
  async function run(p: Promise<ApiResult<LoginData>>, by: string) {
    setBusy(true)
    setWho(by)
    setError('')
    const r = await p
    setBusy(false)
    setSlow(false)
    if (r.ok) navigate(HOME_BY_ROLE[r.data.user.serviceRole], { replace: true })
    else setError(r.error.message)
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy) return // 중복 전송 방지
    if (!employeeNo.trim() || !password) {
      setError('사번과 비밀번호를 입력해 주세요.')
      return
    }
    void run(login({ employeeNo: employeeNo.trim(), password }), 'id')
  }

  const idTab = tab === 'id'

  /** 요청 중인 버튼은 "로그인 중"과 점 세 개로, 나머지는 원래 글자로 보인다 (크기·색은 그대로) */
  const label = (by: string, text: string) =>
    busy && who === by ? (
      <>
        로그인 중 <span className="dots" aria-hidden="true"><i /><i /><i /></span>
      </>
    ) : (
      text
    )
  const slowNote = busy && slow && (
    <p className="slownote" role="status">
      서버 응답이 늦어지고 있어요. 조금만 더 기다려 주세요.
    </p>
  )

  return (
    <div className="login">
      <LoginBackground />
      <div className="lmode">
        <ThemeSwitch />
      </div>
      <div className="lf">
        <div>
          <Logo width={150} kind="word" />
        </div>
        <div className="form">
          <div className="eyebrow">IT HELPDESK</div>
          <h1>IT 문제, 먼저 물어보세요</h1>
          <p className="muted" style={{ margin: '10px 0 22px', lineHeight: '24px' }}>
            AI가 먼저 답하고, 해결되지 않으면 담당자에게 바로 연결해 드려요.
          </p>

          {/* 비밀번호를 바꾼 뒤 / 로그인이 만료돼 돌아왔을 때의 안내. 별도 창 없이 이 한 줄로만 알린다 */}
          {loginNote && (
            <div className="alert info" role="status" style={{ marginBottom: 14 }}>
              <Icon name="shield" />
              <div>
                {loginNote === 'pw-changed' ? (
                  <>
                    <b>비밀번호를 바꿨어요.</b>
                    <br />새 비밀번호로 다시 로그인해 주세요.
                  </>
                ) : (
                  <>
                    <b>로그인이 만료됐어요.</b>
                    <br />보안을 위해 일정 시간이 지나면 다시 로그인해야 해요.
                  </>
                )}
              </div>
            </div>
          )}
          <div className="seg" role="tablist" style={{ marginBottom: 16 }}>
            <button role="tab" type="button" aria-selected={idTab} className={idTab ? 'on' : ''} onClick={() => { setTab('id'); setError('') }}>
              사번 로그인
            </button>
            <button role="tab" type="button" aria-selected={!idTab} className={!idTab ? 'on' : ''} onClick={() => { setTab('sso'); setError('') }}>
              SSO 로그인
            </button>
          </div>

          {idTab ? (
            <form onSubmit={onSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="field">
                <label htmlFor="lg-id">사번</label>
                <input
                  className={`inp${error ? ' err' : ''}`}
                  id="lg-id"
                  name="id"
                  autoComplete="username"
                  placeholder="예) EMP-1001"
                  value={employeeNo}
                  readOnly={busy}
                  onChange={(e) => setEmployeeNo(e.target.value)}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'lg-err' : undefined}
                />
              </div>
              <div className="field">
                <label htmlFor="lg-pw">비밀번호</label>
                <input
                  className={`inp${error ? ' err' : ''}`}
                  id="lg-pw"
                  onFocus={() => setPwFocus(true)}
                  onBlur={() => setPwFocus(false)}
                  name="pw"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  readOnly={busy}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'lg-err' : undefined}
                />
              </div>
              {/* 로그인할 수 없는 사용자가 복구 경로를 바로 찾을 수 있게 비밀번호 칸 아래에 둔다 */}
              <button type="button" className="fgt" onClick={() => setForgotOpen(true)}>
                비밀번호를 잊으셨나요?
              </button>
              {/* 오류는 입력칸 바로 아래에서 연결해 보여 준다 (디자인 가이드) */}
              {error && (
                <div className="errtx" id="lg-err" role="alert">
                  {error}
                </div>
              )}
              <button className="btn pri block" type="submit" aria-disabled={busy} aria-busy={busy && who === 'id'} style={{ minHeight: 48 }}>
                {label('id', '로그인')}
              </button>
              {slowNote}
              <div className="hint">
                {USE_MOCK_AUTH && `시연 계정 비밀번호는 ${MOCK_PASSWORD} 입니다. `}계정 5회 실패 시 잠기고 10분 후 해제됩니다.
                {USE_MOCK_AUTH && (
                  <>
                    <br />
                    임시 비밀번호 상태 시연: EMP-1010 / {MOCK_TEMP_PASSWORD}
                  </>
                )}
              </div>
            </form>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="alert info">
                <Icon name="shield" />
                <div>사내 SSO와 MFA로 인증하는 화면이에요. 이 화면에서는 인증을 연결하지 않았어요.</div>
              </div>
              {error && (
                <div className="errtx" role="alert">
                  {error}
                </div>
              )}
              <button className="btn pri block" type="button" aria-disabled={busy} aria-busy={busy && who === 'sso'} style={{ minHeight: 48 }} onClick={() => !busy && void run(loginSso(), 'sso')}>
                {label('sso', USE_MOCK_AUTH ? 'SSO로 계속하기 (시연)' : 'SSO로 계속하기')}
              </button>
              {slowNote}
            </div>
          )}

          {/* 시연(mock)일 때만 보이는 바로 로그인 버튼. 실제 API 에서는 나타나지 않는다 */}
          {USE_MOCK_AUTH && (
            <div className="roles">
              <small>시연용 바로 로그인</small>
              {MOCK_QUICK_LOGINS.map((q) => (
                <button key={q.id} type="button" className="btn sec sm" aria-disabled={busy} aria-busy={busy && who === q.id} onClick={() => !busy && void run(mockQuickLogin(q.id), q.id)}>
                  {label(q.id, q.label)}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="hint">ICT 가상 기업 프로토타입</div>
      </div>
      <div className="rt">
        <div className="lwrap">
          {/* 상담 창 위로 엿보는 잇슈. 비밀번호 칸에 있는 동안 눈을 감는다 */}
          <Mascot peek shy={pwFocus} />
          <ConsultPanel onForgot={() => setForgotOpen(true)} />
        </div>
      </div>
      {forgotOpen && <ForgotModal onClose={() => setForgotOpen(false)} />}
    </div>
  )
}
