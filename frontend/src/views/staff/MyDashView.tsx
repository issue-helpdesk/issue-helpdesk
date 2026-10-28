/**
 * 담당자 내 대시보드 (/my). 내 담당 문의의 상태별 건수, 확인할 Jira 알림, 먼저 볼 문의, 우리 팀 현황을 한 화면에 모은다.
 * 건수 칸과 띠, '모두 보기'는 처리할 문의의 해당 조건으로 이어진다. 검색하면 대시보드 대신 내 담당 문의 중 검색 결과만 보인다.
 * Jira 알림 띠와 우리 팀 현황은 제안이다. (design/ITssue-Prototype.html 의 내 대시보드)
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { getTeamStatus, listTickets, watchTickets, type TeamStatus } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatDateTime, formatElapsed } from '../../core/format'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'
import { StaffStatus, UrgencyChip } from './QueueView'

const hm = () => {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 최근 활동 문구: 마지막으로 상태가 바뀐 때와 내용 */
const lastAct = (t: TicketSummary) => {
  const what = t.workStatus === 'WIP' ? '처리 시작' : t.workStatus === 'FIN' ? '처리 결과 등록' : t.workStatus === 'CLS' ? '해결 확인' : '배정됨'
  return t.workStatus === 'RDY' ? what : `${formatDateTime(t.workStatusConfirmedAt ?? t.createdAt)} 내가 ${what}`
}

const age = (t: TicketSummary) => Date.now() - Date.parse(t.createdAt)
const URG = { P1: 1, P2: 2, P3: 3, P4: 4 } as const

function Row({ t, onOpen }: { t: TicketSummary; onOpen: () => void }) {
  const cat = t.category ? CATEGORIES[t.category.code as CategoryCode].name : '미분류'
  return (
    <button
      type="button"
      className="dtr"
      onClick={onOpen}
      aria-label={`${t.summary}. 긴급도 ${t.urgency ?? '-'}. 접수 후 경과 ${formatElapsed(t.createdAt)}. 접수번호 ${t.receiptNo}${t.jiraKey ? `, Jira ${t.jiraKey}` : ''}. 문의자 ${t.requester.name}`}
    >
      <span className="c-p">
        <UrgencyChip u={t.urgency} />
      </span>
      <span className="c-t">
        <b>{t.summary}</b>
        {t.jiraMention && <span className="newd" role="img" aria-label="새 답변" />}
        <small>
          {cat} · {t.receiptNo}
          {t.jiraKey ? ` · ${t.jiraKey}` : ''} · {t.requester.name}
        </small>
      </span>
      <span className="c-s">
        <StaffStatus t={t} />
      </span>
      <span className="c-e">
        <b>{formatElapsed(t.createdAt)}</b>
      </span>
      <span className="c-a small muted">{lastAct(t)}</span>
    </button>
  )
}

const Head = () => (
  <div className="dth" aria-hidden="true">
    <span>긴급도</span>
    <span>문의 · 대상 · 접수번호 · 문의자</span>
    <span>상태</span>
    <span>접수 후 경과</span>
    <span>최근 활동</span>
  </div>
)

export function MyDashView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [mine, setMine] = useState<TicketSummary[] | null>(null)
  const [team, setTeam] = useState<TeamStatus | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [synced, setSynced] = useState(hm())
  const [tick, setTick] = useState(0)
  const [reload, setReload] = useState(0)

  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    if (!user) return
    let alive = true
    listTickets(user, { view: 'ASSIGNED', assigneeId: user.id, size: 100 }).then((r) => {
      if (!alive) return
      if (r.ok) {
        setMine(r.data.items)
        setError('')
        setSynced(hm())
      } else setError(r.error.message)
    })
    getTeamStatus(user).then((r) => {
      if (alive && r.ok) setTeam(r.data)
    })
    return () => {
      alive = false
    }
  }, [user, tick, reload])

  const list = useMemo(() => mine ?? [], [mine])
  const n = (s: string) => list.filter((t) => t.workStatus === s).length
  const oldest = (s: string) => {
    const l = list.filter((t) => t.workStatus === s)
    return l.length ? `가장 오래된 건 ${formatElapsed(l.reduce((a, b) => (Date.parse(a.createdAt) < Date.parse(b.createdAt) ? a : b)).createdAt)}` : '해당하는 문의가 없어요'
  }
  const jn = list.filter((t) => t.jiraMention).length
  const todo = useMemo(
    () =>
      list
        .filter((t) => t.workStatus === 'RDY' || t.workStatus === 'WIP')
        .sort((a, b) => URG[a.urgency ?? 'P4'] - URG[b.urgency ?? 'P4'] || Number(!!b.jiraMention) - Number(!!a.jiraMention) || age(b) - age(a)),
    [list],
  )
  const needle = q.trim().toLowerCase()
  const hit = needle ? list.filter((t) => [t.jiraKey, t.receiptNo, t.requester.name, t.summary].some((v) => String(v ?? '').toLowerCase().includes(needle))).sort((a, b) => age(a) - age(b)) : []

  if (!user) return null
  const go = (qs: string) => navigate(`/queue${qs}`)
  const open = (t: TicketSummary) => navigate(`/queue/${t.id}`)
  const tile = (color: string, label: string, count: number, qs: string, hint: string) => (
    <button type="button" className="sbtn" onClick={() => go(qs)} aria-label={`${label} ${count}건. ${hint}`}>
      <span className="l">
        <i className="dt" style={{ background: color }} />
        {label}
      </span>
      <span className="v">
        <b>{count}</b>
        <small>건</small>
      </span>
      <span className="small muted">{hint}</span>
    </button>
  )

  return (
    <main className="main">
      <Topbar title="내 대시보드" sub={`${user.departmentName} · ${user.name} 담당자`} lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div>
            <div className="eyebrow">MY WORK</div>
            <h1>내 담당 문의</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              내 담당 문의의 진행 상황을 확인하고 처리해요. 댓글·멘션은 Jira에서 확인해 주세요.
            </p>
          </div>

          <div className="dsr">
            <label className="dsb">
              <Icon name="search" />
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="접수번호 · Jira 번호 · 문의자·담당자 이름 · 제목 검색" aria-label="내 담당 문의 검색" autoComplete="off" />
            </label>
            <span className="small muted dsy">
              <span>마지막 조회 {synced}</span>
              <button type="button" className="btn ghost sm" onClick={() => setReload((x) => x + 1)}>
                <Icon name="refresh" /> 새로고침
              </button>
            </span>
          </div>

          {error && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>{error}</div>
            </div>
          )}

          <div className="dres">
            {needle ? (
              <section className="panel" aria-label="검색 결과" aria-live="polite" style={{ padding: '22px 24px' }}>
                <div className="sech">
                  <div>
                    <h3 className="sht">검색 결과</h3>
                    <p className="shs">
                      {hit.length}건{hit.length > 10 ? ' · 최근 접수 10건만 보여요' : ''}
                    </p>
                  </div>
                  <button type="button" className="btn ghost sm" onClick={() => setQ('')}>
                    검색 지우기
                  </button>
                </div>
                {hit.length ? (
                  <div className="dtb">
                    <Head />
                    {hit.slice(0, 10).map((t) => (
                      <Row key={t.id} t={t} onOpen={() => open(t)} />
                    ))}
                  </div>
                ) : (
                  <div className="empty">조건에 맞는 내 담당 문의가 없어요.</div>
                )}
              </section>
            ) : (
              <>
                <div className="dgrid c4">
                  {tile('var(--g-w)', '처리 대기 (RDY)', n('RDY'), '?tab=open&sub=RDY', oldest('RDY'))}
                  {tile('var(--g-p)', '처리 중 (WIP)', n('WIP'), '?tab=open&sub=WIP', oldest('WIP'))}
                  {tile('var(--g-n)', '해결 확인 대기 (FIN)', n('FIN'), '?tab=fin', '문의자 확인을 기다려요')}
                  {tile('var(--g-c)', '해결 완료 (CLS)', n('CLS'), '?tab=cls', '해결 완료된 문의 보기')}
                </div>

                <section className={`wband${jn ? ' need wlink' : ''}`} aria-label="확인할 Jira 알림">
                  <div>
                    <b>
                      {jn > 0 && <i className="wd" aria-hidden="true" />}확인할 Jira 알림 {jn}건
                    </b>{' '}
                    <span className="tag gray">제안</span>
                    <div className="small wsub" style={{ marginTop: 2 }}>
                      {jn ? 'Jira 댓글·멘션이 도착했어요. Jira에서 내용을 확인해 주세요.' : '확인할 Jira 알림이 없어요'}
                    </div>
                  </div>
                  <span className="wr">
                    <span className="small wnote">
                      Jira 댓글·멘션이 도착하면 이곳에 표시돼요 <span className="tag gray">시연 데이터</span>
                    </span>
                    {jn > 0 && <Icon name="chevron" className="wch" />}
                  </span>
                  {jn > 0 && <button type="button" className="wover" onClick={() => go('?new=1')} aria-label={`확인할 Jira 알림 ${jn}건. 알림이 온 문의만 보기`} />}
                </section>

                <section className="panel" aria-label="먼저 볼 문의" style={{ padding: '22px 24px' }}>
                  <div className="sech">
                    <div>
                      <h3 className="sht">먼저 볼 문의</h3>
                      <p className="shs">긴급도 높은 순 → 새 댓글 먼저 → 오래된 순</p>
                    </div>
                    <button type="button" className="btn ghost sm" onClick={() => go('?tab=open')}>
                      처리할 문의 {todo.length}건 모두 보기
                    </button>
                  </div>
                  {mine === null ? (
                    <div className="empty" role="status">
                      불러오는 중이에요…
                    </div>
                  ) : todo.length ? (
                    <div className="dtb">
                      <Head />
                      {todo.slice(0, 3).map((t) => (
                        <Row key={t.id} t={t} onOpen={() => open(t)} />
                      ))}
                    </div>
                  ) : (
                    <div className="empty">지금 처리할 문의가 없어요.</div>
                  )}
                </section>

                <section className="panel" aria-label="우리 팀 현황" style={{ padding: '22px 24px' }}>
                  <div className="sech">
                    <div>
                      <h3 className="sht">
                        우리 팀 현황 <span className="tag gray">제안</span>
                      </h3>
                      <p className="shs">{team?.groupName ?? user.departmentName}</p>
                    </div>
                    <button type="button" className="btn ghost sm" onClick={() => navigate('/stats?scope=team')}>
                      팀원별 보기
                    </button>
                  </div>
                  {team && (
                    <div className="tgrid">
                      <div className="tcell">
                        <span className="tl">근무</span>
                        <span className="tv">
                          <b>{team.members - team.off}</b>
                          <small>명</small>
                        </span>
                        <span className="ts">
                          전체 {team.members}명 · 부재 {team.off}명
                        </span>
                      </div>
                      <div className="tcell">
                        <span className="tl">처리 대기 (RDY)</span>
                        <span className="tv">
                          <b>{team.rdy}</b>
                          <small>건</small>
                        </span>
                      </div>
                      <div className="tcell">
                        <span className="tl">처리 중 (WIP)</span>
                        <span className="tv">
                          <b>{team.wip}</b>
                          <small>건</small>
                        </span>
                      </div>
                      <div className={`tcell${team.unassigned ? ' warn' : ''}`}>
                        <span className="tl">배정 전</span>
                        <span className="tv">
                          <b>{team.unassigned}</b>
                          <small>건</small>
                        </span>
                        {team.unassigned > 0 && <span className="ts">담당자가 아직 정해지지 않았어요</span>}
                      </div>
                    </div>
                  )}
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
