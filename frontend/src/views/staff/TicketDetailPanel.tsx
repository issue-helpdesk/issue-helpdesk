/**
 * 접수 상세 패널. 처리할 문의 오른쪽에 붙는다. (design/ITssue-Prototype.html 의 티켓 상세, 담당자 보기)
 *
 * 처리 상태는 문의 상태 · Jira 연동 · 배정 · 티켓 업무 · 상태 변경 순서의 체크리스트로 보여 준다.
 * 끝난 줄은 회색 한 줄이고, 지금 단계만 카드로 올라온다. 상태 변경(처리 시작·처리 결과 등록)은 TK-07(202)로 요청하며,
 * 현재는 Jira 에서 바꾸는 것이 기본이라 이 화면의 변경은 제안이다. Jira 댓글·멘션은 알림만 전달하고 내용은 Jira 에서 읽는다.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CATEGORIES, STAFF_STATUS } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { changeTicketStatus, getTicket, getTicketHistory, getTicketMessages, sendTicketMessage } from '../../api/tickets'
import type { MessageKind, SlackPreview, StatusHistory, TicketDetail, TicketMessage } from '../../api/ticketTypes'
import { formatDateTime } from '../../core/format'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { UrgencyChip } from './QueueView'
import { TicketStepper } from '../inquiry/TicketCard'

type Tone = 'ok' | 'prog' | 'need' | 'asg' | 'urg' | 'warn' | 'recv'

/** 상태 한 줄. done=끝남(회색), idle=아직 시작 전, live=지금 단계(카드) */
function StRow({ lv, tone = 'recv', label, val, sub }: { lv: 'done' | 'idle' | 'live'; tone?: Tone; label: string; val: ReactNode; sub?: string }) {
  if (lv === 'done')
    return (
      <div className="sx done">
        <span className="mk">
          <Icon name="check" />
        </span>
        <span className="l">{label}</span>
        <span className="v">{val}</span>
      </div>
    )
  if (lv === 'idle')
    return (
      <div className="sx idle">
        <span className="mk" />
        <span className="l">{label}</span>
        <span className="v">{val}</span>
      </div>
    )
  return (
    <div className={`sx live tn-${tone}`}>
      <span className="mk">
        {tone === 'urg' || tone === 'warn' ? (
          <Icon name="alert" />
        ) : (
          <svg className="i" viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="10" cy="10" r="4.2" style={{ fill: 'currentColor', stroke: 'none' }} />
          </svg>
        )}
      </span>
      <span className="l">{label}</span>
      <span className="vb">{val}</span>
      {sub && <span className="sxs">{sub}</span>}
    </div>
  )
}

const Sbd = ({ tone, children }: { tone: Tone; children: ReactNode }) => (
  <span className={`sbd tn-${tone}`}>
    <i />
    {children}
  </span>
)

function statusRows(t: TicketDetail): ReactNode {
  const who = t.assignee?.name ?? ''
  const jira =
    t.jiraSyncStatus === 'SYNCED' ? (
      <StRow lv="done" label="Jira 연동" val="완료" />
    ) : t.jiraSyncStatus === 'VERIFYING' ? (
      <StRow lv="live" tone="warn" label="Jira 연동" val={<Sbd tone="warn">생성 여부 확인 중</Sbd>} sub="생성 결과를 확인하는 중" />
    ) : t.jiraSyncStatus === 'NEEDS_ADMIN' ? (
      <StRow lv="live" tone="urg" label="Jira 연동" val={<Sbd tone="urg">Jira 생성 확인 필요</Sbd>} sub="Jira 생성에 실패했어요" />
    ) : (
      <StRow lv="live" tone="recv" label="Jira 연동" val={<Sbd tone="recv">대기</Sbd>} sub="Jira 티켓을 만드는 중" />
    )
  const asg =
    t.assignStatus === 'ASSIGNED' ? (
      <StRow lv="done" label="배정" val="완료" />
    ) : t.assignStatus === 'NEEDS_ADMIN' ? (
      <StRow lv="live" tone="urg" label="배정" val={<Sbd tone="urg">담당자 배정 확인 필요</Sbd>} sub="개인 배정을 확인해야 해요" />
    ) : t.jiraSyncStatus === 'SYNCED' ? (
      <StRow lv="live" tone="asg" label="배정" val={<Sbd tone="asg">연결 중</Sbd>} sub="담당 그룹에서 담당자를 정하는 중" />
    ) : (
      <StRow lv="idle" label="배정" val="대기" />
    )
  const w = t.workStatus
  const work =
    w === 'CLS' ? (
      <StRow lv="done" label="티켓 업무" val="해결 완료" />
    ) : w === 'FIN' ? (
      <StRow lv="live" tone="need" label="티켓 업무" val={<Sbd tone="need">해결 확인 대기</Sbd>} sub="문의자 확인을 기다리는 중" />
    ) : w === 'WIP' ? (
      <StRow lv="live" tone="prog" label="티켓 업무" val={<Sbd tone="prog">처리 중</Sbd>} sub={`${who} 담당`} />
    ) : w === 'RDY' ? (
      <StRow lv="live" tone="recv" label="티켓 업무" val={<Sbd tone="recv">처리 대기</Sbd>} sub={`${who} 담당자가 시작하기를 기다리는 중`} />
    ) : (
      <StRow lv="idle" label="티켓 업무" val="시작 전" />
    )
  const trn =
    t.transitionStatus === 'PENDING' ? (
      <StRow
        lv="live"
        tone="warn"
        label="상태 변경"
        val={<Sbd tone="warn">Jira 반영 확인 중</Sbd>}
        sub={`${t.requestedWorkStatus ? STAFF_STATUS[t.requestedWorkStatus].label : '새 상태'}(으)로 바꾸는 요청을 Jira에 보냈어요. 확인되면 상태가 바뀝니다.`}
      />
    ) : t.transitionStatus === 'NEEDS_ADMIN' ? (
      <StRow lv="live" tone="urg" label="상태 변경" val={<Sbd tone="urg">Jira 동기화 확인 필요</Sbd>} sub="Jira 반영 결과를 확인하지 못했어요. 운영자가 확인하고 있어요." />
    ) : null
  return (
    <div className="stlist" aria-label="처리 상태">
      <StRow lv="done" label="문의 상태" val="접수 완료" />
      {jira}
      {asg}
      {work}
      {trn}
    </div>
  )
}

export function TicketDetailPanel({ id, tick, slide = true, onSlideEnd, onClose }: { id: number; tick: number; slide?: boolean; onSlideEnd?: () => void; onClose: () => void }) {
  const { user } = useAuth()
  const [t, setT] = useState<TicketDetail | null>(null)
  const [hist, setHist] = useState<StatusHistory[]>([])
  const [msgs, setMsgs] = useState<TicketMessage[]>([])
  const [slack, setSlack] = useState<SlackPreview[]>([])
  // 문의자에게 메시지 (제안)
  const [msgModal, setMsgModal] = useState(false)
  const [msgKind, setMsgKind] = useState<MessageKind>('추가 정보 요청')
  const [msgText, setMsgText] = useState('')
  const [msgErr, setMsgErr] = useState('')
  const [toast, setToast] = useState('')
  const [error, setError] = useState('')
  // 처음 열 때만 Jira 알림 안내를 보여 준다 (열면 알림 표시가 지워진다)
  const [mention, setMention] = useState(false)
  const [modal, setModal] = useState(false)
  const [note, setNote] = useState('')
  const [noteErr, setNoteErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [actErr, setActErr] = useState('')
  // 열릴 때 밀려 들어오고, 닫을 때 밀려 나간 뒤에 실제로 닫는다 (움직임 줄이기 설정이면 바로 닫는다)
  const [slid, setSlid] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // 열면 닫기 버튼으로 초점을 옮기고, 닫으면 연 곳으로 돌려 보낸다
  const closeBtn = useRef<HTMLButtonElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeBtn.current?.focus()
  }, [])
  const finish = () => {
    const el = opener.current
    onClose()
    if (el && el !== document.body) setTimeout(() => el.isConnected && el.focus(), 0)
  }
  const close = () => {
    if (leaving) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) finish()
    else setLeaving(true)
  }
  // 애니메이션 종료 알림이 오지 않는 환경(백그라운드 탭 등)에서도 닫히도록 안전장치를 둔다
  useEffect(() => {
    if (!leaving) return
    const t = setTimeout(finish, 400)
    return () => clearTimeout(t)
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.querySelector('[role="dialog"]')) close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    if (!user) return
    let alive = true
    getTicket(user, id).then((r) => {
      if (!alive) return
      if (r.ok) {
        setT(r.data)
        setError('')
        if (r.data.jiraMention) setMention(true)
      } else setError(r.error.message)
    })
    getTicketHistory(user, id).then((r) => {
      if (alive && r.ok) setHist(r.data.items)
    })
    getTicketMessages(user, id).then((r) => {
      if (!alive || !r.ok) return
      setMsgs(r.data.messages)
      setSlack(r.data.slack)
    })
    return () => {
      alive = false
    }
  }, [user, id, tick])

  if (!user) return null
  const mine = !!t && t.assignee?.id === user.id
  const requester = user.serviceRole === 'EMPLOYEE' // 문의자는 진행 단계만 보고, 상태를 바꾸지 못한다
  const pending = t?.transitionStatus === 'PENDING'

  /** 상태 변경 요청 (TK-07). 응답은 202 이고 Jira 반영이 확인되면 상태가 바뀐다 */
  async function change(workStatus: 'WIP' | 'FIN', resolutionNote?: string) {
    if (!user || !t) return false
    setBusy(true)
    setActErr('')
    const r = await changeTicketStatus(user, t.id, {
      workStatus,
      resolutionNote,
    })
    setBusy(false)
    if (!r.ok) {
      setActErr(r.error.message)
      return false
    }
    setT(r.data)
    return true
  }

  async function submitMessage() {
    if (!user || !t) return
    if (!msgText.trim()) {
      setMsgErr('내용을 입력해 주세요.')
      return
    }
    setBusy(true)
    const res = await sendTicketMessage(user, t.id, { kind: msgKind, text: msgText })
    setBusy(false)
    if (!res.ok) {
      setMsgErr(res.error.message)
      return
    }
    setMsgs((l) => [...l, res.data])
    getTicketMessages(user, t.id).then((x) => x.ok && setSlack(x.data.slack))
    setMsgModal(false)
    setMsgText('')
    setMsgErr('')
    setToast('보냈어요.')
    setTimeout(() => setToast(''), 2500)
  }

  async function submitResult() {
    if (!note.trim()) {
      setNoteErr('처리 결과를 입력해 주세요.')
      return
    }
    if (await change('FIN', note.trim())) {
      setModal(false)
      setNote('')
      setNoteErr('')
    } else setNoteErr('처리 결과를 등록하지 못했어요. 다시 시도해 주세요.')
  }

  const info = t && (
    <dl className="dl">
      <dt>접수번호</dt>
      <dd className="mono">{t.receiptNo}</dd>
      <dt>Jira 티켓</dt>
      <dd className="mono">{t.jiraKey ?? '생성 전'}</dd>
      <dt>문의자</dt>
      <dd>
        {t.requester.name} ({t.requester.employeeNo})
      </dd>
      <dt>분류</dt>
      <dd>{t.category ? `${t.category.code} · ${CATEGORIES[t.category.code as CategoryCode].name}` : '미분류'}</dd>
      {t.inquiryType && (
        <>
          <dt>세부 유형</dt>
          <dd>
            {t.inquiryType.code} · {t.inquiryType.name}
          </dd>
        </>
      )}
      <dt>긴급도</dt>
      <dd>
        <UrgencyChip u={t.urgency} />
        {t.urgencyReason && <div className="small muted">{t.urgencyReason}</div>}
      </dd>
      <dt>담당 그룹</dt>
      <dd>{t.group?.name ?? '-'}</dd>
      <dt>담당자</dt>
      <dd>{t.assignee?.name ?? '배정 전'}</dd>
      {t.summary && (
        <>
          <dt>문의 내용</dt>
          <dd>{t.summary}</dd>
        </>
      )}
      {t.businessImpact && (
        <>
          <dt>업무 영향</dt>
          <dd>{t.businessImpact}</dd>
        </>
      )}
      {t.triedActions && (
        <>
          <dt>시도한 조치</dt>
          <dd>{t.triedActions}</dd>
        </>
      )}
      {t.aiSummary && (
        <>
          <dt>AI 안내</dt>
          <dd>{t.aiSummary}</dd>
        </>
      )}
      {t.resolutionNote && (
        <>
          <dt>처리 결과</dt>
          <dd>{t.resolutionNote}</dd>
        </>
      )}
    </dl>
  )

  return (
    <>
      <div className="dscrim" onClick={close} />
      <aside
        className={`detail${slide && !slid && !leaving ? ' slide' : ''}${leaving ? ' leave' : ''}`}
        role="complementary"
        aria-label="티켓 상세"
        onAnimationEnd={() => {
          if (leaving) finish()
          else {
            setSlid(true)
            onSlideEnd?.()
          }
        }}
      >
        <div className="dh">
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <div style={{ minWidth: 0 }}>
              <div className="mono small muted">{t ? `${t.receiptNo}${t.jiraKey ? ` · ${t.jiraKey}` : ''}` : ''}</div>
              <h3>{t?.summary ?? (error ? '접수를 열 수 없어요' : '불러오는 중이에요…')}</h3>
            </div>
            <span style={{ flex: 1 }} />
            <button type="button" ref={closeBtn} className="btn sec sm ico" aria-label="닫기" onClick={close}>
              <Icon name="x" />
            </button>
          </div>
        </div>
        <div className="db">
          {error && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>{error}</div>
            </div>
          )}
          {t && (
            <>
              {requester ? (
                <>
                  <TicketStepper
                    ticket={{
                      createdAt: t.createdAt,
                      assigneeName: t.assignee?.name ?? null,
                      assignStatus: t.assignStatus,
                      jiraSyncStatus: t.jiraSyncStatus,
                      workStatus: t.workStatus,
                      finishedAt: t.finishedAt,
                      closedAt: t.closedAt,
                    }}
                  />
                  {t.workStatus === 'FIN' && (
                    <div className="alert info">
                      <Icon name="check" />
                      <div>담당자가 처리 결과를 등록했어요. 해결되었는지 확인해 주세요.</div>
                    </div>
                  )}
                </>
              ) : (
                statusRows(t)
              )}
              {info}
              {!requester && (
                <div>
                  {mine && t.workStatus === 'RDY' && (
                    <button type="button" className="btn pri block" disabled={busy || pending} onClick={() => void change('WIP')}>
                      처리 시작 (RDY → WIP)
                    </button>
                  )}
                  {mine && t.workStatus === 'WIP' && (
                    <button type="button" className="btn pri block" disabled={busy || pending} onClick={() => setModal(true)}>
                      처리 결과 등록 (WIP → FIN)
                    </button>
                  )}
                  {mine && (t.workStatus === 'RDY' || t.workStatus === 'WIP') && (
                    <div className="small muted" style={{ marginTop: 8 }}>
                      <span className="tag gray">제안</span> 현재는 Jira에서 상태를 바꾸고 해결 방법을 입력해요. 이 화면에서 바꾸는 기능은 추후 제안이에요.
                    </div>
                  )}
                  {pending && (
                    <div className="small muted" style={{ marginTop: 8 }} role="status">
                      Jira 반영을 확인하는 중이에요. 확인되면 상태가 바뀌어요.
                    </div>
                  )}
                  {actErr && (
                    <div className="errtx" role="alert" style={{ marginTop: 8 }}>
                      {actErr}
                    </div>
                  )}
                  {mine && t.workStatus === 'FIN' && (
                    <div className="alert info">
                      <Icon name="clock" />
                      <div>문의자의 해결 확인을 기다리고 있어요. 미응답만으로 종료(CLS)하지 않아요.</div>
                    </div>
                  )}
                  {mine && t.workStatus && (
                    <button type="button" className="btn sec block" style={{ marginTop: 8 }} onClick={() => setMsgModal(true)}>
                      문의자에게 메시지 <span className="tag gray">제안</span>
                    </button>
                  )}
                  {!mine && <div className="small muted">다른 담당자가 맡은 접수예요. 상태는 맡은 담당자만 바꿀 수 있어요.</div>}
                </div>
              )}
              {(mention || msgs.length > 0) && (
                <div>
                  <h4>
                    메시지 <span className="tag gray">제안</span>
                  </h4>
                  <ul className="tl">
                    {[...msgs].reverse().map((m) => (
                      <li key={m.id}>
                        <Icon name="chat" />
                        <div>
                          <b>
                            {m.from} · {m.kind}
                          </b>
                          {m.text}
                          <small>{formatDateTime(m.at)}</small>
                        </div>
                      </li>
                    ))}
                    {mention && !requester && (
                      <li>
                        <Icon name="bell" />
                        <div>
                          <b>Jira 알림 · 문의자 멘션</b>
                          문의자로부터 해당 티켓 멘션이 왔으니 Jira에서 내용을 확인해 주세요.
                          <small>알림만 전달돼요(메시지 내용은 Jira에서 확인)</small>
                        </div>
                      </li>
                    )}
                  </ul>
                </div>
              )}
              {!requester && slack.length > 0 && (
                <div>
                  <h4>Slack 알림 미리보기</h4>
                  <ul className="tl">
                    {slack.map((x, i) => (
                      <li key={i}>
                        <Icon name="bell" />
                        <div>
                          <b>→ {x.to}</b>
                          {x.text}
                          <small>{formatDateTime(x.at)} · 미리보기 (실제 발송 없음)</small>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <h4>처리 이력</h4>
                <ul className="tl">
                  {hist.length === 0 && <li className="muted small">아직 이력이 없어요.</li>}
                  {[...hist].reverse().map((h) => (
                    <li key={h.id}>
                      <Icon name="clock" />
                      <div>
                        <b>{h.fromStatus ? `${STAFF_STATUS[h.fromStatus].label} → ${STAFF_STATUS[h.toStatus].label}` : `접수 · ${STAFF_STATUS[h.toStatus].label}`}</b>
                        <small>
                          {formatDateTime(h.changedAt)} · {h.actor?.name ?? 'Jira'}
                        </small>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>

        {msgModal && (
          <Modal title="문의자에게 메시지" onClose={() => setMsgModal(false)}>
            <p className="small muted">
              문서상 AI 중개 양방향 소통은 Could 범위라서 이 기능은 <b>제안</b>이에요.
            </p>
            <div className="field">
              <label htmlFor="m-k">종류</label>
              <select className="sel" id="m-k" value={msgKind} onChange={(e) => setMsgKind(e.target.value as MessageKind)}>
                <option>추가 정보 요청</option>
                <option>일반 메시지</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="m-t">내용</label>
              <textarea
                className={`ta${msgErr ? ' err' : ''}`}
                id="m-t"
                value={msgText}
                aria-invalid={!!msgErr}
                aria-describedby={msgErr ? 'm-t-e' : undefined}
                onChange={(e) => {
                  setMsgText(e.target.value)
                  setMsgErr('')
                }}
              />
              {msgErr && (
                <div className="errtx" id="m-t-e" role="alert">
                  {msgErr}
                </div>
              )}
            </div>
            <div className="acts">
              <button type="button" className="btn sec" onClick={() => setMsgModal(false)}>
                취소
              </button>
              <button type="button" className="btn pri" disabled={busy} onClick={() => void submitMessage()}>
                보내기
              </button>
            </div>
          </Modal>
        )}
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
        {modal && (
          <Modal title="처리 결과 등록" onClose={() => setModal(false)}>
            <p className="small muted">문의자에게 보이는 내용이에요. 비밀번호·인증번호는 적지 마세요.</p>
            <div className="field">
              <label htmlFor="m-res">처리 결과</label>
              <textarea
                className={`ta${noteErr ? ' err' : ''}`}
                id="m-res"
                value={note}
                placeholder="어떤 원인을 어떻게 조치했는지 적어 주세요"
                aria-invalid={!!noteErr}
                aria-describedby={noteErr ? 'm-res-e' : undefined}
                onChange={(e) => {
                  setNote(e.target.value)
                  setNoteErr('')
                }}
              />
              {noteErr && (
                <div className="errtx" id="m-res-e" role="alert">
                  {noteErr}
                </div>
              )}
            </div>
            <div className="acts">
              <button type="button" className="btn sec" onClick={() => setModal(false)}>
                취소
              </button>
              <button type="button" className="btn pri" disabled={busy} onClick={() => void submitResult()}>
                등록하고 해결 확인 요청
              </button>
            </div>
          </Modal>
        )}
      </aside>
    </>
  )
}
