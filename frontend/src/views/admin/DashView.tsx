/**
 * 관리자 대시보드 (/dash). (design/ITssue-Prototype.html viewDash)
 * 처리 현황(건수), 연동·배정 확인 띠, 긴급·높음 미해결 상위 3건을 한 화면에 모은다.
 * 건수와 띠는 전체 문의·운영 현황의 해당 조건으로 이어진다. 검색하면 대시보드 대신 검색 결과만 보인다.
 */
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { getDashSnapshot, searchTickets, type DashSnapshot } from '../../api/dash'
import { countSecurityAlerts, watchSecurity, type SecCounts } from '../../api/security'
import { watchTickets } from '../../api/tickets'
import type { TicketSummary } from '../../api/ticketTypes'
import titleOps from '../../assets/mascot/title-ops.webp'
import { formatElapsed } from '../../core/format'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { CountUp } from '../../ui/CountUp'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'
import { StaffStatus, UrgencyChip } from '../staff/QueueView'

const hm = (iso: string) => {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const Head = () => (
  <div className="dth" aria-hidden="true">
    <span>긴급도</span>
    <span>문의 · 대상 · 접수번호 · 문의자</span>
    <span>상태</span>
    <span>접수 후 경과</span>
    <span>담당</span>
  </div>
)

function Row({ t, onOpen }: { t: TicketSummary; onOpen: () => void }) {
  const cat = t.category ? CATEGORIES[t.category.code as CategoryCode].name : '미분류'
  const who = t.assignee?.name ?? '배정 전'
  return (
    <button
      type="button"
      className="dtr"
      onClick={onOpen}
      aria-label={`${t.summary}. 긴급도 ${t.urgency ?? '-'}. 접수 후 경과 ${formatElapsed(t.createdAt)}. 담당 ${who}, ${t.group?.name ?? '-'}. 접수번호 ${t.receiptNo}${t.jiraKey ? `, Jira ${t.jiraKey}` : ''}. 문의자 ${t.requester.name}`}
    >
      <span className="c-p">
        <UrgencyChip u={t.urgency} />
      </span>
      <span className="c-t">
        <b>{t.summary}</b>
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
      <span className="c-a small muted">
        {who}
        <br />
        {t.group?.name ?? '-'}
      </span>
    </button>
  )
}

export function DashView() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [snap, setSnap] = useState<DashSnapshot | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [hit, setHit] = useState<{ items: TicketSummary[]; total: number } | null>(null)
  const [sec, setSec] = useState<SecCounts | null>(null)
  const [tick, setTick] = useState(0)
  const [reload, setReload] = useState(0)
  const [opened] = useState(() => new Date().toISOString())
  const admin = user?.serviceRole === 'ADMIN'

  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    getDashSnapshot(user).then((r) => {
      if (!alive) return
      if (r.ok) {
        setSnap(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, tick, reload])

  useEffect(() => {
    if (!user || !admin) return
    return watchSecurity(() => {
      countSecurityAlerts(user).then(setSec)
    })
  }, [user, admin])

  const needle = q.trim()
  useEffect(() => {
    if (!user || !admin || !needle) return
    let alive = true
    const timer = setTimeout(() => {
      searchTickets(user, needle).then((r) => alive && r.ok && setHit(r.data))
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [user, admin, needle, tick])

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  const open = (t: TicketSummary) => navigate(`/tickets/${t.id}`)
  const at = snap?.asOf ?? opened
  const ex = snap?.attention
  const kinds = ex
    ? (
        [
          ['Jira 생성', ex.jira],
          ['상태 동기화', ex.sync],
          ['담당자 배정', ex.assign],
        ] as const
      ).filter((k) => k[1])
    : []
  const un = snap?.unresolved

  const pipe = [
    { label: '처리 대기 (RDY)', n: snap?.rdy ?? 0, to: '/tickets?st=RDY', hint: '전체 문의에서 처리 대기 보기', cls: '' },
    { label: '처리 중 (WIP)', n: snap?.wip ?? 0, to: '/tickets?st=WIP', hint: '전체 문의에서 처리 중 보기', cls: '' },
    { label: '해결 확인 대기 (FIN)', n: snap?.fin ?? 0, to: '/tickets?st=FIN', hint: '전체 문의에서 해결 확인 대기 보기', cls: '' },
    { label: '연동·배정 확인', n: ex?.total ?? 0, to: '/ops', hint: '운영 현황 화면으로 가기', cls: ex?.total ? 'al' : 'z' },
  ]

  return (
    <div className="stx">
    <main className="main">
      <Topbar title="대시보드" sub="처리 현황과 먼저 볼 문의를 모았어요" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div className="phead">
            <div className="eyebrow">DASHBOARD</div>
            <h1>대시보드</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              처리 현황과 먼저 볼 문의만 모았어요. 지금 확인할 일은 운영 현황에서, 추이와 분포는 통계에서 확인해요.
            </p>
          </div>

          <div className="dsr">
            <label className="dsb">
              <Icon name="search" />
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="접수번호 · Jira 번호 · 문의자·담당자 이름 · 제목 검색" aria-label="전체 문의 검색" autoComplete="off" />
            </label>
            <span className="small muted dsy">
              <span>마지막 조회 {hm(at)}</span>
              <button type="button" className="btn ghost sm" onClick={() => setReload((x) => x + 1)}>
                <Icon name="refresh" /> 새로고침
              </button>
            </span>
          </div>

          {error && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>
                {error}{' '}
                <button type="button" className="btn ghost sm" onClick={() => setReload((x) => x + 1)}>
                  다시 시도
                </button>
              </div>
            </div>
          )}

          <div className="dres">
            {needle ? (
              <section className="panel" aria-label="검색 결과" aria-live="polite" style={{ padding: '22px 24px' }}>
                <div className="sech">
                  <div>
                    <h3 className="sht">검색 결과</h3>
                    <p className="shs">
                      {hit?.total ?? 0}건{(hit?.total ?? 0) > 10 ? ' · 최근 접수 10건만 보여요' : ''}
                    </p>
                  </div>
                  <button type="button" className="btn ghost sm" onClick={() => setQ('')}>
                    검색 지우기
                  </button>
                </div>
                {hit?.items.length ? (
                  <div className="dtb">
                    <Head />
                    {hit.items.map((t) => (
                      <Row key={t.id} t={t} onOpen={() => open(t)} />
                    ))}
                  </div>
                ) : (
                  <div className="empty">{hit ? '조건에 맞는 문의가 없어요.' : '찾는 중이에요…'}</div>
                )}
              </section>
            ) : (
              <>
                <div className="dattn">
                  {ex && ex.total > 0 && (
                    <section className="hband" aria-label="연동·배정 확인 필요">
                      <div className="hbt">
                        <h2>
                          <span className="pulse" />
                          연동·배정 확인이 필요한 문의 <em>{ex.total}</em>건
                        </h2>
                        <p>{kinds.map((k) => `${k[0]} ${k[1]}건`).join(' · ')}</p>
                      </div>
                      <button type="button" className="btn sm" onClick={() => navigate('/ops')}>
                        운영 현황
                      </button>
                    </section>
                  )}
                  {sec && sec.신규 + sec['확인 중'] > 0 && (
                    <section className="hband sec" aria-label="보안·감사 알림">
                      <div className="hbt">
                        <h2>
                          <span className="pulse" />
                          보안·감사 알림 신규 <em>{sec.신규}</em>건
                        </h2>
                        <p>
                          확인 중 {sec['확인 중']}건 · 미종결 중 심각도 높음 {sec.high}건
                        </p>
                      </div>
                      <button type="button" className="btn sm" onClick={() => navigate('/security')}>
                        보안·감사 알림
                      </button>
                    </section>
                  )}
                </div>

                <div>
                  <div className="hpipe" role="group" aria-label="처리 현황">
                    {pipe.map((k, i) => (
                      <button key={k.label} type="button" className={k.cls} onClick={() => navigate(k.to)} aria-label={`${k.label} ${k.n}건. ${k.hint}`}>
                        <span>{k.label}</span>
                        <b>
                          <i className="n">
                            <CountUp value={k.n} delay={150 + i * 110} duration={1100} />
                          </i>
                          <small>건</small>
                        </b>
                      </button>
                    ))}
                  </div>
                </div>

                <section className="panel urg" aria-label="긴급·높음 미해결" style={{ padding: '22px 24px' }}>
                  <div className="sech">
                    <div>
                      <h3 className="sht">긴급·높음 미해결</h3>
                      <p className="shs">
                        <UrgencyChip u="P1" /> <UrgencyChip u="P2" /> 중 해결 완료(CLS)가 아닌 문의
                      </p>
                    </div>
                    <button type="button" className="btn ghost sm" onClick={() => navigate('/tickets?pri=P12&unres=1')}>
                      전체 문의에서 보기
                    </button>
                  </div>
                  <div className="ustat">
                    <div className="un">
                      <b>{un?.total ?? 0}</b>
                      <span>건</span>
                    </div>
                    <i className="vs" aria-hidden="true" />
                    <div className="uc">
                      <UrgencyChip u="P1" />
                      <b>{un?.p1 ?? 0}</b>
                      <span>건</span>
                    </div>
                    <div className="uc">
                      <UrgencyChip u="P2" />
                      <b>{un?.p2 ?? 0}</b>
                      <span>건</span>
                    </div>
                  </div>
                  {!snap ? (
                    <div className="empty" role="status">
                      불러오는 중이에요…
                    </div>
                  ) : un && un.top.length ? (
                    <>
                      <div className="dtb">
                        <Head />
                        {un.top.map((t) => (
                          <Row key={t.id} t={t} onOpen={() => open(t)} />
                        ))}
                      </div>
                      <p className="small muted" style={{ marginTop: 10 }}>
                        긴급 → 높음 순, 접수가 오래된 순으로 3건만 보여요.
                      </p>
                    </>
                  ) : (
                    <div className="empty">미해결 긴급·높음 문의가 없어요.</div>
                  )}
                </section>

                <div className="panel">
                  <div className="row" style={{ justifyContent: 'space-between', gap: 12 }}>
                    <div>
                      <b>추이·분포·진행도는 통계에서 확인해요</b>
                      <div className="small muted" style={{ marginTop: 2 }}>
                        접수 추이, 팀별·분류별 진행도, 구성원별 현황, 긴급도 분포를 기간별로 볼 수 있어요.
                      </div>
                    </div>
                    <button type="button" className="btn ghost sm" onClick={() => navigate('/stats')}>
                      통계 보기
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
    </div>
  )
}
