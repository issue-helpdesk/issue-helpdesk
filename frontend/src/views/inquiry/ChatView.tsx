/**
 * 문의 대화 화면 (/chat/:id).
 *
 * 문의자가 AI와 대화하며 해결하고, 해결되지 않으면 접수 초안을 확인해 담당자에게 연결한다.
 * 접수 이후에는 같은 화면에서 진행 카드(접수 → 담당자 배정 → 처리 중 → 해결 완료)를 보고,
 * 담당자가 처리 결과를 등록하면 해결 여부를 직접 확인한다.
 * 종료된 상담(AI 해결·미확인·미해결 종료)은 읽기 전용이며 "대화 이어가기"로 다시 열 수 있다.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { cancelChatDraft, confirmChatDraft, editDraft, getChat, rejectChat, reopenChat, replyChat, resolveChat, sendChat, timeoutChat, watchChat } from '../../api/chat'
import type { DraftEdit, GuideSource, Inquiry, InquiryStatus, LegacyCase } from '../../api/chatTypes'
import { inquiryState } from '../../api/inquiryState'
import type { ApiResult } from '../../api/types'
import { SERVICEDESK } from '../../core/config'
import { sourceLabel } from '../../core/format'
import { useAuth } from '../../core/session'
import { Composer } from '../../ui/Composer'
import { Modal } from '../../ui/Modal'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { MessageItem, type ChatActions } from './MessageItem'

const NOTE = '비밀번호·인증번호·API 키는 입력하지 마세요. 상담 기록은 처리·운영 목적으로 활용될 수 있어요.'

/** 종료된 상담 상태별 안내 문구 */
const CLOSED_WHY: Partial<Record<InquiryStatus, string>> = {
  AI_RESOLVED: 'AI 안내로 해결된 문의입니다.',
  UNCONFIRMED: '응답이 없어 상담이 종료된 문의입니다. 해결된 것으로 처리하지 않았어요.',
  CLOSED_UNRESOLVED: '담당자 연결 없이 종료된 문의입니다. 해결된 것으로 기록하지 않았어요.',
}

type ModalState = { kind: 'source'; source: GuideSource } | { kind: 'legacy'; legacy: LegacyCase } | { kind: 'reject' } | null

export function ChatView() {
  const { id: idParam = '' } = useParams()
  const id = Number(idParam)
  const { user } = useAuth()
  const employeeNo = user?.employeeNo
  // 어느 문의를 불러왔는지 함께 기억해, 다른 문의로 옮겼을 때 이전 내용이 잠깐 보이지 않게 한다
  const [loaded, setLoaded] = useState<{ id: number; data: Inquiry | null } | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [modal, setModal] = useState<ModalState>(null)
  const [reason, setReason] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  // 문의를 불러오고, 이후 바뀔 때마다(답변 도착, 담당자 진행) 다시 받는다
  useEffect(() => {
    if (!employeeNo || !id) return
    let alive = true // 화면이 사라진 뒤에는 상태를 바꾸지 않기 위한 표시
    getChat(id, employeeNo).then((r) => {
      if (alive) setLoaded({ id, data: r.ok ? r.data : null })
    })
    const stop = watchChat(id, employeeNo, (r) => {
      if (alive && r.ok) setLoaded({ id, data: r.data })
    })
    return () => {
      alive = false
      stop()
    }
  }, [id, employeeNo])

  const inquiry = loaded?.id === id ? loaded.data : undefined // undefined=불러오는 중, null=없음
  const count = inquiry?.messages.length ?? 0

  // 새 메시지가 생기면 맨 아래로 내린다
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [count, inquiry?.ticket?.workStatus, inquiry?.ticket?.assignStatus])

  /** 동작을 보내고 돌아온 문의로 화면을 바꾼다. 실패하면 안내 문구를 보여 준다. */
  const apply = useCallback(
    async (job: Promise<ApiResult<Inquiry>>): Promise<boolean> => {
      setBusy(true)
      setError('')
      const r = await job
      setBusy(false)
      if (!r.ok) {
        setError(r.error.message)
        return false
      }
      setLoaded({ id, data: r.data })
      return true
    },
    [id],
  )

  const actions: ChatActions | null = useMemo(() => {
    if (!employeeNo) return null
    return {
      reply: (req) => void apply(replyChat(id, employeeNo, req)),
      timeout: (messageId) => void apply(timeoutChat(id, employeeNo, messageId)),
      confirmDraft: () => void apply(confirmChatDraft(id, employeeNo)),
      saveDraft: (edit: DraftEdit) => apply(editDraft(id, employeeNo, edit)),
      cancelDraft: () => void apply(cancelChatDraft(id, employeeNo)),
      resolve: () => void apply(resolveChat(id, employeeNo)),
      reject: () => {
        setReason('')
        setModal({ kind: 'reject' })
      },
      showSource: (source) => setModal({ kind: 'source', source }),
      showLegacy: (legacy) => setModal({ kind: 'legacy', legacy }),
      servicedesk: SERVICEDESK,
    }
  }, [apply, id, employeeNo])

  if (!user || !actions) return null

  if (inquiry === undefined) {
    return (
      <main className="main">
        <Topbar title="문의 대화" />
        <div className="scroll" />
      </main>
    )
  }
  if (inquiry === null) {
    return (
      <main className="main">
        <Topbar title="문의 대화" />
        <div className="scroll">
          <div className="page">
            <div className="panel">
              <div className="empty">문의를 찾을 수 없어요. 문의 내역에서 다시 선택해 주세요.</div>
            </div>
          </div>
        </div>
      </main>
    )
  }

  const state = inquiryState(inquiry)
  const closed = inquiry.step === 'closed'
  // 답변을 준비하는 동안에는 새 메시지를 받지 않는다
  const typing = inquiry.messages.some((m) => m.typing)
  const placeholder = inquiry.ticket ? '담당자에게 추가 내용 남기기' : inquiry.step === 'draft' ? '수정할 내용을 적거나 초안에서 고쳐 주세요' : '메시지를 입력하세요'
  const t = inquiry.ticket

  async function send() {
    const v = text.trim()
    if (!v || busy || !employeeNo) return
    setText('')
    const ok = await apply(sendChat(id, employeeNo, v))
    if (!ok) setText(v) // 실패하면 쓴 내용을 되돌려 놓는다
  }

  async function submitReject() {
    if (!reason.trim() || !employeeNo) return
    if (await apply(rejectChat(id, employeeNo, reason))) setModal(null)
  }

  return (
    <main className="main">
      <Topbar
        title={inquiry.title}
        sub={t ? `${t.receiptNo}${t.jiraKey ? ` · ${t.jiraKey}` : ''}` : undefined}
        right={<StateBadge tone={state.tone} label={state.label} />}
      />

      <div className="scroll" ref={scrollRef}>
        <div className="thread" role="log" aria-live="polite" aria-label="문의 대화">
          {inquiry.messages.map((m) => (
            <MessageItem key={m.id} inquiry={inquiry} message={m} busy={busy} actions={actions} />
          ))}
        </div>
      </div>

      <div className="composer-wrap">
        {error && (
          <div className="alert err" role="alert" style={{ maxWidth: 760, margin: '0 auto 10px' }}>
            <div>{error}</div>
          </div>
        )}
        {closed ? (
          <div className="composer" style={{ justifyContent: 'space-between', padding: '12px 16px 12px 20px' }}>
            <span className="muted">{CLOSED_WHY[inquiry.status] ?? '종료된 문의입니다.'}</span>
            <button type="button" className="btn pri sm" disabled={busy} onClick={() => void apply(reopenChat(id, employeeNo!))}>
              대화 이어가기
            </button>
          </div>
        ) : (
          <>
            <Composer value={text} onChange={setText} onSend={send} placeholder={placeholder} disabled={busy || typing} />
            <div className="notice">{NOTE}</div>
          </>
        )}
      </div>

      {modal?.kind === 'source' && (
        <Modal title={sourceLabel(modal.source)} onClose={() => setModal(null)}>
          <p className="small muted">출처 미리보기 (시연)</p>
          <div className="card w">
            <b>{modal.source.section}</b>
            <p style={{ marginTop: 6, lineHeight: '24px' }}>{modal.source.excerpt}</p>
          </div>
          <div className="acts">
            <button type="button" className="btn pri" onClick={() => setModal(null)}>
              닫기
            </button>
          </div>
        </Modal>
      )}

      {modal?.kind === 'legacy' && (
        <Modal title={`과거 처리 사례 · ${modal.legacy.no}`} onClose={() => setModal(null)}>
          <p className="small muted">도입 이전 처리 이력 (읽기 전용, 시연용 가상 데이터)</p>
          <div className="card w">
            <b>{modal.legacy.title}</b>
            <dl className="dl" style={{ marginTop: 8 }}>
              <dt>증상</dt>
              <dd>{modal.legacy.symptom}</dd>
              <dt>해결 방법</dt>
              <dd>{modal.legacy.solution}</dd>
              <dt>활용 원칙</dt>
              <dd>현재 Guide·정책과 충돌하지 않을 때만 참고하고, 충돌하면 Guide를 우선해요.</dd>
            </dl>
          </div>
          <div className="acts">
            <button type="button" className="btn pri" onClick={() => setModal(null)}>
              닫기
            </button>
          </div>
        </Modal>
      )}

      {modal?.kind === 'reject' && (
        <Modal title="아직 해결되지 않았어요" onClose={() => setModal(null)}>
          <p className="small muted">남은 증상을 알려 주시면 담당자가 다시 확인해요.</p>
          <div className="field">
            <label htmlFor="m-reason">남은 증상</label>
            <textarea className="ta" id="m-reason" value={reason} placeholder="예) 안내대로 했지만 같은 오류가 나요" onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setModal(null)}>
              취소
            </button>
            <button type="button" className="btn pri" disabled={!reason.trim() || busy} onClick={submitReject}>
              다시 확인 요청
            </button>
          </div>
        </Modal>
      )}
    </main>
  )
}
