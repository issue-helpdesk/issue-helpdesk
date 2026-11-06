/**
 * 접수 상세 패널. 처리할 문의 오른쪽에 붙는다. (design/ITssue-Prototype.html 의 티켓 상세, 담당자 보기)
 *
 * 처리 상태는 문의 상태 · ITSM 연동 · 배정 · 티켓 업무 · 상태 변경 순서의 체크리스트로 보여 준다.
 * 끝난 줄은 회색 한 줄이고, 지금 단계만 카드로 올라온다. 상태 변경과 처리 결과 입력은 ITSM 에서 하고, 이 화면은 ITSM 의 상태를 받아 보여 주기만 한다. ITSM 댓글·멘션은 알림만 전달하고 내용은 ITSM 에서 읽는다.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATEGORIES, STAFF_STATUS } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { markTicketRead, refreshUnread } from '../../api/notifications'
import { isRuleUrgencyReason } from '../../api/urgencyReason'
import { friendlyAssignReason } from '../../api/assignReason'
import { getAssignmentLogs, getTicket, getTicketHistory, syncTicket } from '../../api/tickets'
import type { AssignmentLog, StatusHistory, TicketDetail } from '../../api/ticketTypes'
import { USE_MOCK_TICKET } from '../../core/config'
import { formatDateTime } from '../../core/format'
import { useAuth } from '../../core/session'
import { AssessmentHistory } from './AssessmentHistory'
import { Icon } from '../../ui/Icon'
import { ReassignDialog } from '../admin/ReassignDialog'
import { useToast } from '../../ui/useToast'
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
  const navigate = useNavigate()
  const [t, setT] = useState<TicketDetail | null>(null)
  const [hist, setHist] = useState<StatusHistory[]>([])
  // 담당자 배정 이력(재배정 포함). 못 읽으면(권한 등) 조용히 비워 두고 상태 이력만 보인다
  const [assigns, setAssigns] = useState<AssignmentLog[]>([])
  // 담당자 재배정 (관리자)
  const [reassign, setReassign] = useState(false)
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
    getTicket(user, id).then((r) => {
      if (!alive) return
      if (r.ok) {
        setT(r.data)
        setError('')
        // 이 접수의 내 알림(담당자 배정 등)은 열었으니 읽음으로 바꾸고 사이드바 개수를 다시 읽는다 (NT-04)
        markTicketRead(id).then((x) => x.ok && x.data.updatedCount > 0 && refreshUnread())
      } else setError(r.error.message)
    })
    // 서버 모드: ITSM 의 최신 상태를 읽어 오게 하고(TK-14), 달라졌으면 화면에 반영한다
    if (!USE_MOCK_TICKET) {
      syncTicket(user, id).then((r) => {
        if (alive && r.ok) setT((cur) => (cur ? { ...cur, ...r.data } : cur))
      })
    }
    getTicketHistory(user, id).then((r) => {
      if (alive && r.ok) setHist(r.data.items)
    })
    // 서버는 문의자에게 배정 이력을 주지 않고 404 로 답한다 (담당 그룹·관리자만). 문의자는 아예 요청하지 않는다
    if (user.serviceRole !== 'EMPLOYEE') {
      getAssignmentLogs(user, id).then((r) => {
        if (alive && r.ok) setAssigns(r.data.items)
      })
    }
    return () => {
      alive = false
    }
  }, [user, id, tick])

  if (!user) return null
  const mine = !!t && t.assignee?.id === user.id
  const requester = user.serviceRole === 'EMPLOYEE' // 문의자는 진행 단계만 보고, 상태를 바꾸지 못한다
  const admin = user.serviceRole === 'ADMIN' // 관리자는 상태를 바꾸지 않고, 처리 중인 접수의 담당자를 다시 정한다
  const pending = t?.transitionStatus === 'PENDING'
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
      <dt>긴급도</dt>
      <dd>
        <UrgencyChip u={t.urgency} />
        {/* "세부 유형 NET-04 기본 긴급도" 는 서버 규칙의 내부 사유라 문의자에게는 보이지 않는다 (담당자·관리자는 근거로 본다) */}
        {t.urgencyReason && !(requester && isRuleUrgencyReason(t.urgencyReason)) && <div className="small muted">{t.urgencyReason}</div>}
      </dd>
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
                  {mine && (t.workStatus === 'RDY' || t.workStatus === 'WIP') && (
                    <div className="small muted" style={{ marginTop: 8 }}>
                      처리 상태와 처리 결과는 ITSM에서 입력해요. 이 화면은 ITSM의 상태를 받아 와서 보여 줘요.
                    </div>
                  )}
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
                  {admin && t.needsAdmin && t.workStatus !== 'CLS' && (
                    <button type="button" className="btn pri block" onClick={() => navigate('/ops')}>
                      연동·배정 확인 화면으로
                    </button>
                  )}
                  {admin && (t.workStatus === 'RDY' || t.workStatus === 'WIP') && (
                    <button type="button" className="btn sec block" style={{ marginTop: 8 }} onClick={() => setReassign(true)}>
                      담당자 재배정
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

        {reassign && t && (
          <ReassignDialog
            t={t}
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
