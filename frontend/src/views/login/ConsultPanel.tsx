/**
 * 로그인 전 도움말 패널.
 *
 * 질문 버튼을 선택하면 공개용 고정 답변을 보여 준다. 내부 가이드와 연결하지 않는다.
 * Ticket은 만들지 않으며, 비밀번호·인증번호 입력을 요청하지 않는다. (PRD 4.1, SRS PRE-01)
 */
import { useEffect, useRef, useState } from 'react'
import { askPreLogin, PRE_LOGIN_QUESTIONS } from '../../api/consult'
import type { ConsultReply } from '../../api/types'
import { Pav } from '../../ui/Pav'
import { RichText } from '../../ui/RichText'

/** 대화창에 보이는 메시지: 사용자 / AI 답변 / 답변을 기다리는 중(점 세 개) */
type Msg = { id: number; role: 'user'; text: string } | { id: number; role: 'ai'; reply: ConsultReply } | { id: number; role: 'typing' }

/** 빠르게 고를 수 있는 질문 */
const CHIPS = PRE_LOGIN_QUESTIONS

/** 처음 화면에 보여 줄 인사 대화 */
const INTRO: Msg[] = [
  { id: 1, role: 'user', text: '로그인이 계속 안 돼요.' },
  {
    id: 2,
    role: 'ai',
    reply: {
      sources: [],
      paragraphs: [
        '로그인에 문제가 있으신가요? 아래에서 겪고 있는 문제를 선택해 주세요.',
      ],
    },
  },
]

export function ConsultPanel({ onForgot }: { onForgot?: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>(INTRO)
  // 답변을 기다리는 동안은 입력과 중복 전송을 막는다
  const [busy, setBusy] = useState(false)
  const nextId = useRef(10)
  const thread = useRef<HTMLDivElement>(null)

  // 새 메시지가 생기면 대화창을 맨 아래로 부드럽게 내린다 (처음 보여 주는 안내 글은 바로)
  const first = useRef(true)
  useEffect(() => {
    const el = thread.current
    if (!el) return
    const smooth = !first.current && typeof el.scrollTo === 'function' && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    first.current = false
    if (smooth) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    else el.scrollTop = el.scrollHeight
  }, [msgs])

  /** 질문을 보내고 답변을 받아 대화에 추가한다. */
  async function ask(raw: string) {
    const t = raw.trim()
    if (!t || busy) return
    const uid = nextId.current++
    const tid = nextId.current++
    setBusy(true)
    // 사용자 메시지와 "처리 중" 표시를 먼저 보여 준다
    setMsgs((m) => [...m, { id: uid, role: 'user', text: t }, { id: tid, role: 'typing' }])

    const r = await askPreLogin(t)
    // 고정 답변을 기존 대화 형식으로 보여 준다
    const base: ConsultReply = r.ok ? r.data : { paragraphs: [r.error.message], sources: [] }

    // "처리 중" 표시를 지우고 실제 답변으로 바꾼다
    setMsgs((m) => [...m.filter((x) => x.id !== tid), { id: nextId.current++, role: 'ai', reply: base }])
    setBusy(false)
  }

  return (
    <section className="lpop" aria-label="로그인 전 상담">
      {/* 제목 줄은 대화 위에 떠 있고, 대화가 그 아래로 지나가며 비쳐 보인다 */}
      <div className="row lph" style={{ flexWrap: 'nowrap' }}>
        <Pav size={40} />
        <div>
          <b>로그인 도움말</b>
          <div className="small muted">
            계정과 비밀번호 문제를 확인해 보세요
          </div>
        </div>
      </div>

      <div className="th" ref={thread} role="log" aria-live="polite">
        {msgs.map((m) => {
          // 처음 안내 글(id<10)은 그대로 두고, 대화 중 새로 생긴 말풍선만 모션으로 나타난다
          const fresh = m.id >= 10
          if (m.role === 'user') return <div className={`msg u${fresh ? ' rise-u' : ''}`} key={m.id}>{m.text}</div>
          if (m.role === 'typing')
            return (
              <div className={`msg a${fresh ? ' rise' : ''}`} key={m.id}>
                <Pav />
                <div className="body">
                  <span className="dots"><i /><i /><i /></span> <span className="muted small">처리 중</span>
                </div>
              </div>
            )
          return (
            <div className={`msg a${fresh ? ' rise' : ''}`} key={m.id}>
              <Pav />
              <div className="body">
                {m.reply.paragraphs.map((p, i) => (
                  <p key={i}><RichText text={p} /></p>
                ))}
                {/* 바로가기 (예: 비밀번호를 잊으셨나요? 안내 창 열기) */}
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

    </section>
  )
}
