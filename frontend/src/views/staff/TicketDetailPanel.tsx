/**
 * 접수 상세 패널. 처리할 문의 오른쪽에 붙는다. (design/ITssue-Prototype.html 의 티켓 상세, 담당자 보기)
 *
 * 처리 상태는 문의 상태 · ITSM 연동 · 배정 · 티켓 업무 · 상태 변경 순서의 체크리스트로 보여 준다.
 * 끝난 줄은 회색 한 줄이고, 지금 단계만 카드로 올라온다. 담당자는 패널에서도 상태 변경과 처리 결과를 요청할 수 있고, ITSM 반영 확인 뒤 확정한다. ITSM 댓글·멘션은 알림만 전달하고 내용은 ITSM 에서 읽는다.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CATEGORIES, STAFF_STATUS } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { markTicketRead, refreshUnread } from '../../api/notifications'
import { urgencyReasonText } from '../../api/urgencyReason'
import { friendlyAssignReason } from '../../api/assignReason'
import { getAssignmentLogs, getTicket, getTicketHistory, refreshTickets, syncTicket } from '../../api/tickets'
import type { AssignmentLog, StatusHistory, TicketDetail } from '../../api/ticketTypes'
import { USE_MOCK_TICKET } from '../../core/config'
import { formatDateTime } from '../../core/format'
import { useAuth } from '../../core/session'
import { AssessmentHistory } from './AssessmentHistory'
import { Icon } from '../../ui/Icon'
import { CheckDialog } from '../admin/CheckDialog'
import { ReassignDialog } from '../admin/ReassignDialog'
import { recheckTransition, retryJiraCreate } from '../../api/ops'
import { useToast } from '../../ui/useToast'
import { UrgencyChip } from './QueueView'
import { TicketWorkActions } from './TicketWorkActions'
import { visiblePoll } from '../../core/poll'
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
      <StRow lv="done" label="ITSM 연동" val="완료" />
    ) : t.jiraSyncStatus === 'VERIFYING' ? (
      <StRow lv="live" tone="warn" label="ITSM 연동" val={<Sbd tone="warn">생성 여부 확인 중</Sbd>} sub="생성 결과를 확인하는 중" />
    ) : t.jiraSyncStatus === 'NEEDS_ADMIN' ? (
      <StRow lv="live" tone="urg" label="ITSM 연동" val={<Sbd tone="urg">ITSM 생성 확인 필요</Sbd>} sub="ITSM 생성에 실패했어요" />
    ) : (
      <StRow lv="live" tone="recv" label="ITSM 연동" val={<Sbd tone="recv">대기</Sbd>} sub="ITSM 티켓을 만드는 중" />
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
        val={<Sbd tone="warn">ITSM 반영 확인 중</Sbd>}
        sub={`${t.requestedWorkStatus ? STAFF_STATUS[t.requestedWorkStatus].label : '새 상태'}(으)로 바꾸는 요청을 ITSM에 보냈어요. 확인되면 상태가 바뀝니다.`}
      />
    ) : t.transitionStatus === 'NEEDS_ADMIN' ? (
      <StRow lv="live" tone="urg" label="상태 변경" val={<Sbd tone="urg">ITSM 동기화 확인 필요</Sbd>} sub="ITSM 반영 결과를 확인하지 못했어요. 운영자가 확인하고 있어요." />
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

/** 배정 이력 한 줄의 제목: 누구에게 어떤 일이 있었는지 */
function assignTitle(a: AssignmentLog): string {
  const who = a.assignee ? `${a.assignee.name}` : ''
  const grp = a.group ? a.group.name : ''
  switch (a.event) {
    case 'RECOMMEND':
      return `담당 그룹 추천${grp ? ` · ${grp}` : ''}`
    case 'ASSIGN':
      return `담당자 배정${who ? ` · ${who}` : ''}${grp ? ` (${grp})` : ''}`
    case 'REASSIGN':
      return `담당자 재배정${who ? ` · ${who}` : ''}${grp ? ` (${grp})` : ''}`
    case 'FAIL':
      return '담당자 배정 실패'
  }
}

export function TicketDetailPanel({ id, tick, slide = true, onSlideEnd, onClose }: { id: number; tick: number; slide?: boolean; onSlideEnd?: () => void; onClose: () => void }) {
  const { user } = useAuth()
  const [t, setT] = useState<TicketDetail | null>(null)
  const pending = t?.transitionStatus === 'PENDING'
  const mutationVersion = useRef(0)
  const [reload, setReload] = useState(0)
  const [hist, setHist] = useState<StatusHistory[]>([])
  // 담당자 배정 이력(재배정 포함). 못 읽으면(권한 등) 조용히 비워 두고 상태 이력만 보인다
  const [assigns, setAssigns] = useState<AssignmentLog[]>([])
  // 담당자 재배정 (관리자)
  const [reassign, setReassign] = useState<false | 'assign' | 'reassign'>(false)
  // ITSM 확인·재시도 (연동 실패·상태 동기화 확인 필요). 어느 화면에서 열어도 같은 단추와 창을 쓴다
  const [check, setCheck] = useState(false)
  const [checkBusy, setCheckBusy] = useState(false)
  const [checkErr, setCheckErr] = useState('')
  const { say } = useToast()
  const [error, setError] = useState('')
  // 열릴 때 밀려 들어오고, 닫을 때 밀려 나간 뒤에 실제로 닫는다 (움직임 줄이기 설정이면 바로 닫는다)
  const [slid, setSlid] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // 열면 닫기 버튼으로 초점을 옮기고, 닫으면 연 곳으로 돌려 보낸다
  const closeBtn = useRef<HTMLButtonElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    // 패널이 화면 오른쪽 밖에서 밀려 들어오는 중이라, 그냥 초점을 옮기면 브라우저가 그 버튼을 보이게 하려고 앱 전체를 옆으로 밀어 버린다(화면이 튄다)
    closeBtn.current?.focus({ preventScroll: true })
  }, [])
  const finish = () => {
    const el = opener.current
    onClose()
    if (el && el !== document.body) setTimeout(() => el.isConnected && el.focus({ preventScroll: true }), 0)
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
    const version = mutationVersion.current
    const current = () => alive && version === mutationVersion.current
    // 반영 중에는 worker가 확정한 DB 값만 읽는다. 그 외에는 Jira 대조 후 상세를 읽는다.
    const read = async () => {
      if (!USE_MOCK_TICKET && !pending) await syncTicket(user, id)
      if (!current()) return
      return getTicket(user, id)
    }
    read().then((r) => {
      if (!current() || !r) return
      if (r.ok) {
        setT(r.data)
        setError('')
        getTicketHistory(user, id).then((history) => {
          if (current() && history.ok) setHist(history.data.items)
        })
        // 이 접수의 내 알림(담당자 배정 등)은 열었으니 읽음으로 바꾸고 사이드바 개수를 다시 읽는다 (NT-04)
        markTicketRead(id).then((x) => x.ok && x.data.updatedCount > 0 && refreshUnread())
      } else setError(r.error.message)
    })
    // 서버는 문의자에게 배정 이력을 주지 않고 404 로 답한다 (담당 그룹·관리자만). 문의자는 아예 요청하지 않는다
    if (user.serviceRole !== 'EMPLOYEE') {
      getAssignmentLogs(user, id).then((r) => {
        if (current() && r.ok) setAssigns(r.data.items)
      })
    }
    return () => {
      alive = false
    }
  }, [user, id, tick, reload, pending])

  // 반영 중에는 상세를 더 자주 읽는다. 탭이 숨겨지거나 패널이 닫히면 중단한다.
  useEffect(() => {
    if (t?.transitionStatus !== 'PENDING') return
    return visiblePoll(() => setReload((n) => n + 1), 3000)
  }, [t?.transitionStatus])

  const transitionStatus = t?.transitionStatus
  const previousTransition = useRef(transitionStatus)
  useEffect(() => {
    const wasPending = previousTransition.current === 'PENDING'
    previousTransition.current = transitionStatus
    if (wasPending && transitionStatus && transitionStatus !== 'PENDING') {
      refreshTickets()
      refreshUnread()
    }
  }, [transitionStatus])

  if (!user) return null
  const mine = !!t && t.assignee?.id === user.id
  const requester = user.serviceRole === 'EMPLOYEE' // 문의자는 진행 단계만 보고, 상태를 바꾸지 못한다
  const admin = user.serviceRole === 'ADMIN' // 관리자는 연동 확인·재배정을 한다
  // 처리 이력 = 상태 이력 + 담당자 배정 이력(추천·배정·재배정·실패)을 시간순으로 합친다. 화면에는 최근 것이 위에 온다
  const timeline = [
    ...hist.map((h) => ({ kind: 's' as const, at: h.changedAt, h })),
    ...assigns.map((a) => ({ kind: 'a' as const, at: a.createdAt, a })),
  ].sort((x, y) => Date.parse(y.at) - Date.parse(x.at) || (x.kind === y.kind ? 0 : x.kind === 'a' ? 1 : -1))

  const info = t && (
    <dl className="dl">
      <dt>접수번호</dt>
      <dd className="mono">{t.receiptNo}</dd>
      <dt>ITSM 티켓</dt>
      {/* 코드용 글꼴(mono)에는 한글이 없어서 "생성 전"은 일반 글꼴로 둔다 */}
      <dd className={t.jiraKey ? 'mono' : undefined}>{t.jiraKey ?? '생성 전'}</dd>
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
      {/* 긴급도는 담당자·관리자가 처리 순서를 정하는 내부 기준이라 문의자에게는 보이지 않는다 */}
      {!requester && (
        <>
          <dt>긴급도</dt>
          <dd>
            <UrgencyChip u={t.urgency} />
            {t.urgencyReason && <div className="small muted">{urgencyReasonText(t.urgencyReason)}</div>}
          </dd>
        </>
      )}
      <dt>담당 그룹</dt>
      <dd>{t.group?.name ?? '-'}</dd>
      <dt>담당자</dt>
      <dd>
        {t.assignee?.name ?? '배정 전'}
        {t.assignee && t.assignStatus === 'PENDING' && <small className="muted" style={{ display: 'block' }}>ITSM 반영 대기 중</small>}
      </dd>
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
          <dt>{t.workStatus === 'FIN' || t.workStatus === 'CLS' ? '처리 결과' : '이전 처리 결과'}</dt>
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
                  <TicketWorkActions
                    key={`${id}:${t.workStatus}`}
                    ticket={t}
                    user={user}
                    onRequested={(updated) => {
                      mutationVersion.current += 1
                      setT(updated)
                      refreshTickets()
                      setReload((n) => n + 1)
                    }}
                  />
                  {pending && (
                    <div className="small muted" style={{ marginTop: 8 }} role="status">
                      ITSM 반영을 확인하는 중이에요. 확인되면 상태가 바뀌어요.
                    </div>
                  )}
                  {mine && t.workStatus === 'FIN' && (
                    <div className="alert info">
                      <Icon name="clock" />
                      <div>문의자의 해결 확인을 기다리고 있어요. 미응답만으로 종료하지 않아요.</div>
                    </div>
                  )}
                  {/* 확인이 필요한 건은 이 건에서 바로 할 수 있는 일을 단추로 둔다 (운영 현황으로 보내지 않는다) */}
                  {admin && t.workStatus !== 'CLS' && (t.jiraSyncStatus === 'NEEDS_ADMIN' || t.jiraSyncStatus === 'VERIFYING' || t.transitionStatus === 'NEEDS_ADMIN') && (
                    <button type="button" className="btn pri block" style={{ marginBottom: 8 }} onClick={() => { setCheckErr(''); setCheck(true) }}>
                      ITSM 확인·재시도
                    </button>
                  )}
                  {admin && (t.workStatus === 'RDY' || t.workStatus === 'WIP') && (
                    <button type="button" className={`btn ${t.assignStatus === 'NEEDS_ADMIN' && !t.assignee ? 'pri' : 'sec'} block`} onClick={() => setReassign(t.assignee ? 'reassign' : 'assign')}>
                      {t.assignee ? '담당자 재배정' : '담당자 지정'}
                    </button>
                  )}
                  {!mine && !admin && <div className="small muted">다른 담당자가 맡은 접수예요. 상태는 맡은 담당자만 바꿀 수 있어요.</div>}
                </div>
              )}
              {/* AI 판단 이력: 관리자만, 서버(IQ-10)에서 읽는다 */}
              <AssessmentHistory inquiryId={t.inquiryId} />
              <div>
                <h4>처리 이력</h4>
                <ul className="tl">
                  {timeline.length === 0 && <li className="muted small">아직 이력이 없어요.</li>}
                  {timeline.map((e) => {
                    if (e.kind === 'a') {
                      const x = e.a
                      return (
                        <li key={`a${x.id}`}>
                          <Icon name="user" />
                          <div>
                            <b>{assignTitle(x)}</b>
                            <small>
                              {formatDateTime(x.createdAt)} · {x.actor?.name ?? '시스템'}
                            </small>
                            {x.reason && (
                              <p className="tln">
                                <em>{x.event === 'REASSIGN' ? '재배정 사유' : x.event === 'FAIL' ? '실패 사유' : '근거'}</em>
                                {friendlyAssignReason(x.reason, t?.workStatus)}
                              </p>
                            )}
                          </div>
                        </li>
                      )
                    }
                    const h = e.h
                    return (
                    <li key={h.id}>
                      <Icon name="clock" />
                      <div>
                        <b>{h.fromStatus ? `${STAFF_STATUS[h.fromStatus].label} → ${STAFF_STATUS[h.toStatus].label}` : `접수 · ${STAFF_STATUS[h.toStatus].label}`}</b>
                        <small>
                          {formatDateTime(h.changedAt)} · {h.actor?.name ?? 'ITSM'}
                        </small>
                        {/* 완료할 때마다의 처리 결과, 미해결로 되돌릴 때의 남은 증상 */}
                        {h.toStatus === 'FIN' && h.resolutionNote && (
                          <p className="tln">
                            <em>처리 결과</em>
                            {h.resolutionNote}
                          </p>
                        )}
                        {h.fromStatus === 'FIN' && h.toStatus === 'WIP' && h.reason && (
                          <p className="tln">
                            <em>남은 증상</em>
                            {h.reason}
                          </p>
                        )}
                      </div>
                    </li>
                    )
                  })}
                </ul>
              </div>
            </>
          )}
        </div>

        {check && t && (
          <CheckDialog
            t={t}
            busy={checkBusy}
            err={checkErr}
            onClose={() => setCheck(false)}
            onGo={async (kind, reason) => {
              setCheckBusy(true)
              setCheckErr('')
              const r = kind === 'trn' ? await recheckTransition(user, id, reason) : await retryJiraCreate(user, id, reason)
              setCheckBusy(false)
              if (!r.ok) return setCheckErr(r.error.message)
              setCheck(false)
              say(r.data.outcome === 'REGISTERED' ? '재처리를 등록했어요. 실행기가 처리하면 상태가 바뀌어요.' : '재처리를 등록했어요. 잠시 뒤 반영돼요.')
              refreshTickets()
              setReload((n) => n + 1)
            }}
          />
        )}
        {reassign && t && (
          <ReassignDialog
            t={t}
            mode={reassign}
            onClose={() => setReassign(false)}
            onDone={(registered) => {
              setReassign(false)
              getAssignmentLogs(user, id).then((r) => r.ok && setAssigns(r.data.items))
              say(registered ? '재배정을 등록했어요. 실행기가 ITSM에 반영하면 담당자가 바뀌어요.' : '재배정했어요. 진행 상태는 그대로 유지돼요.')
            }}
          />
        )}
      </aside>
    </>
  )
}
