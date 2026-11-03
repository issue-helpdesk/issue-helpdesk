/**
 * 새 문의를 보낸 직후 화면 (/chat/new). 서버가 AI 답변을 만드는 동안(몇 초~1분 이상) 입력창에 머물지 않고
 * 대화 화면으로 바로 넘어와서, 보낸 글과 "답변을 찾고 있어요" 표시를 보여 준다. 답이 오면 그 문의의 대화 화면(/chat/:id)으로 바꾼다.
 * 오래 걸리면 단계별 문구와 안내를 더하고, 실패하면 쓴 글을 지키면서 다시 시도·다시 쓰기를 고르게 한다.
 */
import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { beginChat, clearPending, getPending } from '../../api/chat'
import { useAuth } from '../../core/session'
import { Composer } from '../../ui/Composer'
import { Icon } from '../../ui/Icon'
import { Pav } from '../../ui/Pav'
import { Topbar } from '../../ui/Topbar'
import { stageLabel } from './pendingStages'

export function PendingChatView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const prefill = (useLocation().state as { prefill?: string } | null)?.prefill
  const [run, setRun] = useState(0)
  const [sec, setSec] = useState(0)
  const [error, setError] = useState('')
  const pending = getPending()
  const text = pending?.text ?? prefill ?? ''
  const live = useRef(true)

  // 답이 오면 그 문의의 대화 화면으로 (뒤로 가기로 이 화면에 돌아오지 않도록 바꿔 끼운다)
  useEffect(() => {
    live.current = true
    const p = getPending()
    if (!p) return
    p.promise.then((r) => {
      if (!live.current) return
      if (r.ok) {
        clearPending()
        navigate(`/chat/${r.data.id}`, { replace: true, state: { fresh: true } })
      } else setError(r.error.message)
    })
    return () => {
      live.current = false
    }
  }, [navigate, run])

  // 기다린 시간을 센다
  useEffect(() => {
    if (error) return
    const t = setInterval(() => setSec((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [error, run])

  if (!user) return null
  // 새로고침 등으로 보낸 글이 사라졌으면 새 문의 화면으로
  if (!pending) return <Navigate to="/new" replace />

  const retry = () => {
    setError('')
    setSec(0)
    beginChat(user, text)
    setRun((n) => n + 1)
  }
  const rewrite = () => {
    clearPending()
    navigate('/new', { replace: true, state: { prefill: text } })
  }

  return (
    <main className="main">
      <Topbar title="새 문의" sub="답변을 준비하고 있어요" lead={<Pav pose="base" size={44} />} />
      <div className="scroll">
        <div className="thread" role="log" aria-live="polite" aria-label="문의 대화">
          <div className="msg u rise-u">{text}</div>
          {error ? (
            <div className="msg a">
              <Pav pose="base" />
              <div className="body" role="alert">
                <p style={{ margin: 0 }}>{error}</p>
                <div className="row" style={{ marginTop: 10 }}>
                  <button type="button" className="btn pri sm" onClick={retry}>
                    <Icon name="refresh" /> 다시 시도
                  </button>
                  <button type="button" className="btn sec sm" onClick={rewrite}>
                    질문 다시 쓰기
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="msg a rise">
              <Pav pose="base" />
              <div className="body" role="status">
                <span className="dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>{' '}
                <span className="muted small">{stageLabel(sec)}</span>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="composer-wrap">
        <div className="cmpw">
          <Composer value="" onChange={() => {}} onSend={() => {}} placeholder="답변을 준비하는 동안은 새 글을 쓸 수 없어요." disabled locked={false} />
        </div>
        <div className="notice">비밀번호·인증번호·API 키는 입력하지 마세요. 상담 기록은 처리·운영 목적으로 활용될 수 있어요.</div>
      </div>
    </main>
  )
}
