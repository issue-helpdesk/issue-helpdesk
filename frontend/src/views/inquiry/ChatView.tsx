/**
 * 문의 대화 화면 (/chat/:id).
 *
 * 문의자가 AI와 대화하며 해결하고, 해결되지 않으면 접수 초안을 확인해 담당자에게 연결한다.
 * 접수 이후에는 같은 화면에서 진행 카드(접수 → 담당자 배정 → 처리 중 → 해결 완료)를 보고,
 * 담당자가 처리 결과를 등록하면 해결 여부를 직접 확인한다.
 * 끝난 문의는 입력창을 잠그고 상태만 안내한다. 미확인·미해결·미접수 종료 문의는 열 때 이어가기 창이 뜨고(✕로 닫은 뒤에는
 * 잠긴 입력창을 누르면 다시 뜬다), AI 해결과 해결 완료 문의는 이어갈 수 없다.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { cancelChatDraft, isStaleInquiry, confirmChatDraft, editDraft, getChat, idleBackChat, idleDeleteChat, idleWarnChat, leaveChat, reopenChat, replyChat, resolveChat, resumeChat, sendChat, watchChat } from '../../api/chat'
import { IDLE_TEXT, type DraftEdit, type GuideSource, type Inquiry, type LegacyCase } from '../../api/chatTypes'
import { inquiryState } from '../../api/inquiryState'
import type { ApiResult } from '../../api/types'
import { SERVICEDESK, USE_MOCK } from '../../core/config'
import { sourceFull } from '../../core/format'
import { useAuth } from '../../core/session'
import { Composer } from '../../ui/Composer'
import { EmptyState } from '../../ui/EmptyState'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { StateBadge } from '../../ui/StateBadge'
import { Pav } from '../../ui/Pav'
import { Topbar } from '../../ui/Topbar'
import { MessageItem, type ChatActions } from './MessageItem'
import { latestPose, poseLabel, poseOf } from './pose'
import { ENTRY_POPUP, endedMessage, entryKindOf, type EntryKind } from './resume'

const NOTE = '비밀번호·인증번호·API 키는 입력하지 마세요. 상담 기록은 처리·운영 목적으로 활용될 수 있어요.'
const NO_MESSAGES: ReadonlySet<number> = new Set()

/** 버튼으로만 고르는 단계의 입력창 자리표시자와 안내 (docs/09: 입력창을 끄는 단계). 자리표시자와 겹치는 안내는 줄여 쓴다. */
const PICK = '위의 버튼을 선택해 주세요.'
const LOCK = {
  answered: { ph: PICK, why: '해결 여부는 위 버튼으로 선택해 주세요. ' },
  offer: { ph: PICK, why: '담당자 연결 여부는 위 버튼으로 선택해 주세요. ' },
  draft: { ph: PICK, why: '티켓 내용을 확인한 후 버튼으로 선택해 주세요. ' },
  fin: { ph: PICK, why: '해결 여부는 위 버튼으로 선택해 주세요. ' },
} as const

type ModalState = { kind: 'source'; source: GuideSource } | { kind: 'legacy'; legacy: LegacyCase } | { kind: 'reject' } | null

export function ChatView() {
  const { id: idParam = '' } = useParams()
  const navigate = useNavigate()
  const fromNew = !!(useLocation().state as { fresh?: boolean } | null)?.fresh // 새 문의에서 막 넘어온 화면
  const id = Number(idParam)
  const { user } = useAuth()
  const employeeNo = user?.employeeNo
  // 어느 문의를 불러왔는지 함께 기억해, 다른 문의로 옮겼을 때 이전 내용이 잠깐 보이지 않게 한다
  // data=null 이면 불러오지 못한 것이다. failed 이면 문의가 없어서가 아니라 연결·서버 문제로 못 읽은 경우다.
  const [loaded, setLoaded] = useState<{ id: number; data: Inquiry | null; failed?: boolean } | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const seen = useRef(false) // 이 화면에서 문의를 한 번이라도 읽었는지
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [modal, setModal] = useState<ModalState>(null)
  const [reason, setReason] = useState('')
  // 이어갈 수 있는 문의를 열면 이어가기 창이 뜬다. 처음 불러온 순간에 정하므로 방금 만든 대화에서는 뜨지 않는다.
  // done=이어가기를 골랐음, popup=창이 열려 있음 (✕로 닫으면 잠긴 입력창을 눌러 다시 연다)
  const [entry, setEntry] = useState<{ id: number; kind: EntryKind | null; popup: boolean; done: boolean } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 문의를 불러오고, 이후 바뀔 때마다(답변 도착, 담당자 진행) 다시 받는다
  useEffect(() => {
    if (!employeeNo || !id) return
    let alive = true // 화면이 사라진 뒤에는 상태를 바꾸지 않기 위한 표시
    seen.current = false
    getChat(id, employeeNo).then((r) => {
      if (!alive) return
      if (r.ok) seen.current = true
      // 문의가 없는 것(404)과 연결·서버 오류를 나눠서 보여 준다
      setLoaded({ id, data: r.ok ? r.data : null, failed: !r.ok && r.error.code !== 'INQUIRY_NOT_FOUND' })
    })
    const stop = watchChat(id, employeeNo, (r) => {
      if (alive && r.ok) setLoaded({ id, data: r.data })
      // 보고 있던 대화가 응답 없음으로 삭제되면 새 문의 화면으로 보낸다 (처음부터 없던 문의면 안내 화면을 그대로 둔다)
      else if (alive && !r.ok && r.error.code === 'INQUIRY_NOT_FOUND' && seen.current) navigate('/new', { replace: true })
    })
    return () => {
      alive = false
      stop()
    }
  }, [id, employeeNo, navigate, reloadKey])

  const inquiry = loaded?.id === id ? loaded.data : undefined // undefined=불러오는 중, null=없음
  const count = inquiry?.messages.length ?? 0

  // 새로 생긴 AI 답변만 한 번 움직인다. 처음 불러온 메시지와 단순한 다시 그리기에서는 움직이지 않는다.
  const [known, setKnown] = useState<{ id: number; ids: Set<number>; fresh: Set<number> } | null>(null)
  if (inquiry) {
    const ids = inquiry.messages.map((m) => m.id)
    if (!known || known.id !== id) setKnown({ id, ids: new Set(ids), fresh: new Set() })
    else if (ids.some((x) => !known.ids.has(x))) setKnown({ id, ids: new Set(ids), fresh: new Set(ids.filter((x) => !known.ids.has(x))) })
  }
  const fresh = known?.id === id ? known.fresh : NO_MESSAGES
  if (inquiry && (!entry || entry.id !== id)) {
    const kind = fromNew ? null : entryKindOf(inquiry)
    setEntry({ id, kind, popup: kind !== null, done: false })
  }
  const gated = entry?.id === id && entry.kind !== null && !entry.done // 이어가기 창을 거치기 전

  // 대화는 맨 아래를 따라간다: 아래에 있던 사용자는 새 메시지·이미지·입력창 높이 변화가 있어도 맨 아래에 머문다.
  // 위로 올려 읽는 중이면 그대로 두고, 내가 글을 보내면 다시 맨 아래로 내린다.
  const stick = useRef(true)
  const ready = !!inquiry
  const lastRole = inquiry?.messages[inquiry.messages.length - 1]?.role
  useEffect(() => {
    stick.current = true // 다른 문의를 열면 맨 아래에서 시작한다
  }, [id])
  useEffect(() => {
    if (lastRole === 'user') stick.current = true
  }, [count, lastRole])
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !ready) return
    const down = () => {
      if (stick.current) el.scrollTop = el.scrollHeight
    }
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(down)
    ro?.observe(el)
    const thread = el.querySelector('.thread')
    if (thread) ro?.observe(thread)
    down()
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro?.disconnect()
    }
  }, [ready, id])
  // 글이 늘거나 진행 카드가 바뀔 때에도 아래를 따라간다
  useEffect(() => {
    const el = scrollRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
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
        // 지난 버튼·중복 요청 같은 409: 안내만 하고 끝내지 않고 최신 문의로 다시 그린다
        if (isStaleInquiry(r.error.code) && employeeNo) {
          const fresh = await getChat(id, employeeNo)
          if (fresh.ok) setLoaded({ id, data: fresh.data })
        }
        return false
      }
      setLoaded({ id, data: r.data })
      return true
    },
    [id, employeeNo],
  )

  const actions: ChatActions | null = useMemo(() => {
    if (!employeeNo) return null
    return {
      reply: (req) => void apply(replyChat(id, employeeNo, req)),
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
    const failed = loaded?.failed
    return (
      <main className="main">
        <Topbar title="문의 대화" />
        <div className="scroll">
          {failed ? (
            <EmptyState
              title="문의를 불러오지 못했어요"
              actions={
                <>
                  <button
                    type="button"
                    className="btn pri"
                    onClick={() => {
                      setLoaded(null)
                      setReloadKey((k) => k + 1)
                    }}
                  >
                    다시 불러오기
                  </button>
                  <button type="button" className="btn sec" onClick={() => navigate('/new')}>
                    새 문의 시작하기
                  </button>
                </>
              }
              note={`계속되면 IT 헬프데스크 ${SERVICEDESK}로 연락해 주세요.`}
            >
              연결이 불안정할 수 있어요. 잠시 뒤 다시 시도해 주세요.
            </EmptyState>
          ) : (
            <EmptyState
              title="문의를 찾을 수 없어요"
              actions={
                <>
                  <button type="button" className="btn pri" onClick={() => navigate('/new')}>
                    새 문의 시작하기
                  </button>
                  <button type="button" className="btn sec" onClick={() => navigate('/list')}>
                    문의 내역 보기
                  </button>
                </>
              }
            >
              삭제되었거나 볼 수 없는 문의예요. 본인이 보낸 문의만 열 수 있어요.
            </EmptyState>
          )}
        </div>
      </main>
    )
  }

  const state = inquiryState(inquiry)
  const closed = inquiry.step === 'closed'
  const endMsg = endedMessage(inquiry) // 끝난 문의: 입력창은 상태만 안내하고 잠근다
  // 답변을 준비하는 동안에는 새 메시지를 받지 않는다
  const typing = inquiry.messages.some((m) => m.typing)
  const t = inquiry.ticket
  // 버튼으로만 고르는 단계: 답변 뒤·연결 제안, 접수 초안 확인, 담당자 처리 완료 뒤 해결 확인
  const wait = t ? (t.workStatus === 'FIN' ? 'fin' : null) : inquiry.step === 'draft' ? 'draft' : inquiry.step === 'answered' ? 'answered' : inquiry.step === 'offer' ? 'offer' : null
  // 삭제 전에 돌아온 상태: 이어서 할지 새로 시작할지 고를 때까지 입력창을 끈다
  const paused = !!inquiry.paused
  const lock = paused ? { ph: '아래에서 이어갈 방법을 골라 주세요', why: '' } : wait ? LOCK[wait] : null
  const placeholder = endMsg ?? (lock ? lock.ph : t ? '담당자에게 추가로 전달할 내용을 입력해 주세요.' : '메시지를 입력하세요')
  // 시연: 응답 없음 삭제 안내 · 삭제 · 돌아옴. 질문·연결 제안·초안 단계에서만 쓴다 (접수된 건·끝난 문의·미확인은 대상이 아니다).
  const demoIdle = USE_MOCK && !!employeeNo && !t && !closed && inquiry.step !== 'answered'
  // 이어가기 뒤 담당자 연결 버튼이 대화 위쪽에 멀리 있으면, 버튼을 맨 아래에 다시 보여 준다 (저장되는 메시지가 아니라 화면 표시)
  const lastMsg = inquiry.messages[inquiry.messages.length - 1]
  const tailMsg = !t && inquiry.step === 'offer' ? [...inquiry.messages].reverse().find((m) => !m.locked && m.replies?.some((r) => r.action === 'connect-yes') && !m.replies.some((r) => r.action === 'resolved')) : undefined
  const showTail = !!tailMsg && tailMsg.id !== lastMsg?.id

  async function send() {
    const v = text.trim()
    if (!v || busy || !employeeNo) return
    setText('')
    const ok = await apply(sendChat(id, employeeNo, v))
    if (!ok) setText(v) // 실패하면 쓴 내용을 되돌려 놓는다
  }

  function submitReject() {
    const ticket = inquiry?.ticket
    if (!ticket || ticket.workStatus !== 'FIN') return
    const reference = [ticket.receiptNo, ticket.jiraKey].filter(Boolean).join(' / ')
    const prefill = `기존 접수 ${reference}: ${ticket.title}\n아직 해결되지 않았어요.${reason.trim() ? '\n남은 증상: ' + reason.trim() : ''}`
    setModal(null)
    navigate('/new', { state: { prefill } })
  }

  return (
    <main className="main">
      <Topbar
        title={inquiry.title}
        sub={t ? `${t.receiptNo}${t.jiraKey ? ` · ${t.jiraKey}` : ''}` : undefined}
        right={<StateBadge tone={state.tone} label={state.label} />}
        lead={
          <span className="tlead">
            <Pav pose={latestPose(inquiry)} size={44} />
          </span>
        }
      />

      <div className="scroll" ref={scrollRef}>
        <div className="thread" role="log" aria-live="polite" aria-label="문의 대화">
          {inquiry.messages.map((m, idx) => {
            const pose = poseOf(inquiry, idx)
            return <MessageItem key={m.id} inquiry={inquiry} message={m} busy={busy} actions={actions} fresh={fresh.has(m.id)} pose={pose} poseText={poseLabel(inquiry, idx, pose)} replyLock={gated} hideReplies={showTail && m.id === tailMsg?.id} />
          })}
          {showTail && tailMsg && (
            <div className="msg a">
              <span style={{ width: 40, flex: 'none' }} aria-hidden="true" />
              <div className="body">
                <div className="replies">
                  {tailMsg.replies?.map((r) => (
                    <button key={r.action} type="button" className={`chip${r.primary ? ' on' : ''}`} disabled={busy || gated} onClick={() => actions.reply({ messageId: tailMsg.id, action: r.action, arg: r.arg })}>
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="composer-wrap">
        {!endMsg && inquiry.idleWarned && (
          <div className="idlebar" role="status">
            <Icon name="bell" />
            <span>{IDLE_TEXT[inquiry.idleWarned]}</span>
          </div>
        )}
        {error && (
          <div className="alert err" role="alert" style={{ maxWidth: 760, margin: '0 auto 10px' }}>
            <div>{error}</div>
          </div>
        )}
        <div className="cmpw">
          <Composer value={text} onChange={setText} onSend={send} placeholder={placeholder} disabled={busy || typing} locked={!!lock || !!endMsg} />
          {gated && <button type="button" className="cmp-hit" aria-label="이어가기 선택 열기" onClick={() => setEntry((e) => (e ? { ...e, popup: true } : e))} />}
        </div>
        {!endMsg && (
          <div className="notice">
            {lock?.why}
            {NOTE}
          </div>
        )}
        {demoIdle && (
          <div className="demoidle" aria-label="응답 없음 시연">
            <span>시연</span>
            <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void apply(idleWarnChat(id, employeeNo!))}>
              응답 없음 안내
            </button>
            <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void apply(idleDeleteChat(id, employeeNo!))}>
              안내 뒤 삭제
            </button>
            <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void apply(idleBackChat(id, employeeNo!))}>
              돌아옴 팝업
            </button>
          </div>
        )}
      </div>

      {modal?.kind === 'source' && (
        <Modal title={sourceFull(modal.source)} onClose={() => setModal(null)}>
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

      {/* 삭제 전에 돌아왔을 때: 채팅 영역 가운데 창에서 고를 때까지 뒤 화면은 어둡고 흐리게 막는다. 새 문의를 시작해도 이전 문의는 지우지 않는다. */}
      {paused && (
        <Modal key="back" title="잠시 자리를 비우셨네요" variant="choice" dismissible={false} lead={<Pav size={84} />}>
          <p>이전 대화를 이어가거나 새 문의를 시작할 수 있어요.</p>
          <div className="acts">
            <button type="button" className="btn pri" disabled={busy} onClick={() => void apply(resumeChat(id, employeeNo!))}>
              이어서 대화하기
            </button>
            <button type="button" className="btn sec" disabled={busy} onClick={() => void apply(leaveChat(id, employeeNo!)).then(() => navigate('/new'))}>
              새 문의 시작하기
            </button>
          </div>
        </Modal>
      )}
      {/* 미확인·미해결·미접수 종료 문의를 열었을 때: 이어서 할지 새로 시작할지 고른다. ✕는 창만 닫는다. */}
      {!paused && gated && entry?.popup && entry.kind && (
        <Modal key="entry" title={ENTRY_POPUP[entry.kind].title} variant="choice" dismissible={false} closeButton onClose={() => setEntry((e) => (e ? { ...e, popup: false } : e))} lead={<Pav size={84} />}>
          <p>{ENTRY_POPUP[entry.kind].body}</p>
          <div className="acts">
            <button
              type="button"
              className="btn pri"
              disabled={busy}
              onClick={async () => {
                // 미확인은 기존 해결·미해결 버튼을 풀기만 하고, 미해결·미접수 종료는 같은 대화의 담당자 연결 제안부터 다시 시작한다
                if (entry.kind !== 'ua' && !(await apply(reopenChat(id, employeeNo!)))) return
                setEntry((e) => (e ? { ...e, popup: false, done: true } : e))
              }}
            >
              이어서 대화하기
            </button>
            <button type="button" className="btn sec" disabled={busy} onClick={() => navigate('/new')}>
              새 문의 시작하기
            </button>
          </div>
        </Modal>
      )}

      {modal?.kind === 'reject' && (
        <Modal title="새 문의로 접수" onClose={() => setModal(null)}>
          <p className="small muted">기존 티켓과 처리 이력은 그대로 보존해요. 새 문의에서 내용을 확인하고 별도로 접수해 주세요.</p>
          <div className="field">
            <label htmlFor="m-reason">남은 증상 (선택)</label>
            <textarea className="ta" id="m-reason" value={reason} placeholder="예) 안내대로 했지만 같은 오류가 나요" onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setModal(null)}>
              취소
            </button>
            <button type="button" className="btn pri" disabled={busy} onClick={submitReject}>
              새 문의 시작하기
            </button>
          </div>
        </Modal>
      )}
    </main>
  )
}
