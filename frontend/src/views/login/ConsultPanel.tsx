/**
 * 로그인 전 상담 패널 (제안 기능 · 팀 확정 전).
 *
 * 로그인 화면 오른쪽에서 계정·로그인 범위의 공개 Guide 안내만 한다.
 * Ticket은 만들지 않으며, 비밀번호·인증번호 입력을 요청하지 않는다. (PRD 4.1, SRS PRE-01)
 */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { askPreLogin } from '../../api/consult'
import type { ConsultReply } from '../../api/types'
import { SHOW_PROPOSAL_TAGS } from '../../core/config'
import { sourceLabel } from '../../core/format'
import { MASK_NOTICE, maskSensitive } from '../../core/mask'
import { Icon } from '../../ui/Icon'
import { Avatar } from '../../ui/Logo'
import { RichText } from '../../ui/RichText'

/** 대화창에 보이는 메시지: 사용자 / AI 답변 / 답변을 기다리는 중(점 세 개) */
type Msg = { id: number; role: 'user'; text: string } | { id: number; role: 'ai'; reply: ConsultReply } | { id: number; role: 'typing' }

/** 빠르게 고를 수 있는 질문 */
const CHIPS = ['계정이 잠겼어요', '비밀번호를 재설정하고 싶어요', 'SSO·MFA 인증이 안 돼요']
const NOTE = '비밀번호·인증번호·API 키는 입력하지 마세요.'

/** 처음 화면에 보여 줄 인사 대화 */
const INTRO: Msg[] = [
  { id: 1, role: 'user', text: '로그인이 계속 안 돼요.' },
  {
    id: 2,
    role: 'ai',
    reply: {
      sources: [],
      paragraphs: [
        '로그인 전에는 **계정 잠금, 비밀번호, SSO·MFA** 안내만 도와드려요. 어떤 증상인지 아래에서 고르거나 직접 적어 주세요. 접수는 로그인 후에 할 수 있어요.',
      ],
    },
  },
]

export function ConsultPanel({ onForgot }: { onForgot?: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>(INTRO)
  const [text, setText] = useState('')
  // 답변을 기다리는 동안은 입력과 중복 전송을 막는다
  const [busy, setBusy] = useState(false)
  const nextId = useRef(10)
  const thread = useRef<HTMLDivElement>(null)

  // 새 메시지가 생기면 대화창을 맨 아래로 내린다
  useEffect(() => {
    const el = thread.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs])

  /** 질문을 보내고 답변을 받아 대화에 추가한다. */
  async function ask(raw: string) {
    const masked = maskSensitive(raw.trim())
    const t = masked.text
    if (!t || busy) return
    const uid = nextId.current++
    const tid = nextId.current++
    setText('')
    setBusy(true)
    // 사용자 메시지와 "처리 중" 표시를 먼저 보여 준다
    setMsgs((m) => [...m, { id: uid, role: 'user', text: t }, { id: tid, role: 'typing' }])

    const r = await askPreLogin(t)
    // 실패하면 서버 오류 문구를 답변처럼 보여 준다
    const base: ConsultReply = r.ok ? r.data : { paragraphs: [r.error.message], sources: [] }
    // 비밀번호·인증번호로 보이는 값을 가렸다면 답변 맨 위에서 알린다
    const reply: ConsultReply = masked.hit ? { ...base, paragraphs: [MASK_NOTICE, ...base.paragraphs] } : base

    // "처리 중" 표시를 지우고 실제 답변으로 바꾼다
    setMsgs((m) => [...m.filter((x) => x.id !== tid), { id: nextId.current++, role: 'ai', reply }])
    setBusy(false)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter 로 전송하되, 한글 조합 중에는 보내지 않는다 (디자인 가이드). Shift+Enter 는 줄바꿈
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void ask(text)
    }
  }

  return (
    <section className="lpop" aria-label="로그인 전 상담">
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <Avatar size={36} />
        <div>
          <b>로그인이 안 되시나요?</b>
          <div className="small muted">
            로그인 전에도 계정·로그인 문의는 답해 드려요{SHOW_PROPOSAL_TAGS && <> <span className="tag gray">제안</span></>}
          </div>
        </div>
      </div>

      <div className="th" ref={thread} role="log" aria-live="polite">
        {msgs.map((m) => {
          if (m.role === 'user') return <div className="msg u" key={m.id}>{m.text}</div>
          if (m.role === 'typing')
            return (
              <div className="msg a" key={m.id}>
                <Avatar size={32} />
                <div className="body">
                  <span className="dots"><i /><i /><i /></span> <span className="muted small">처리 중</span>
                </div>
              </div>
            )
          return (
            <div className="msg a" key={m.id}>
              <Avatar size={32} />
              <div className="body">
                {m.reply.paragraphs.map((p, i) => (
                  <p key={i}><RichText text={p} /></p>
                ))}
                {/* 근거로 쓴 Guide 출처 (SRS ANSWER-01) */}
                {m.reply.sources.map((s) => (
                  <button className="src" type="button" title="출처 Guide" key={`${s.docCode}-${s.section}`}>
                    <Icon name="file" size={16} />
                    {sourceLabel(s)}
                  </button>
                ))}
                {/* 바로가기 (예: 비밀번호 초기화 창 열기) */}
                {m.reply.ctas?.map((c) => (
                  <p key={c.action}>
                    <button className="btn sec sm" type="button" onClick={() => c.action === 'forgot' && onForgot?.()}>
                      {c.label}
                    </button>
                  </p>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      <div className="replies">
        {CHIPS.map((c) => (
          <button key={c} className="chip" type="button" disabled={busy} onClick={() => void ask(c)}>
            {c}
          </button>
        ))}
      </div>

      <div className="composer">
        <textarea
          rows={1}
          value={text}
          placeholder="로그인 문제를 적어 주세요"
          aria-label="로그인 전 상담 입력"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />
        <button className="btn ico pri" type="button" aria-label="보내기" disabled={busy || !text.trim()} onClick={() => void ask(text)}>
          <Icon name="send" />
        </button>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>
        {NOTE} 로그인 전에는 Ticket을 만들지 않아요.
      </div>
    </section>
  )
}
