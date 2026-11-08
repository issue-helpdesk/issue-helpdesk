/**
 * 가이드 관리 (관리자, /guides). (design/ITssue-Prototype.html viewGuides)
 * AI 답변의 근거가 되는 문서를 분류별로 보고, 버전마다 열람 범위·외부 AI 전송 정책·현행 여부를 관리한다.
 * 현행 버전 중 검색 준비가 끝난 것만 AI 답변에 쓰인다. 해결 사례를 묶어 가이드 초안으로 만드는 탭은 제안이다.
 * 문서·버전은 문서 API(DC-01·02·06·07·09), 해결 사례 묶음은 접수 목록(TK-05)을 읽어 화면에서 만든다.
 * 서버에 없는 정책 변경 사유·가이드 초안 만들기는 서버 모드에서 안내만 한다. (api/guides.ts, 요청 R-22~23)
 */
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import {
  FIRST_VERSION,
  GUIDE_TXS,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_MESSAGE,
  TX_RANK,
  formatBytes,
  guideLabel,
  listGuideVersions,
  listGuides,
  nextDocCode,
  nextVersion,
  normalizeVersion,
  readFileVersion,
  sameVersion,
  retryGuideIngest,
  setGuideActive,
  setGuideCurrent,
  setGuideTransfer,
  uploadGuide,
  uploadGuideVersion,
  watchGuides,
  type Guide,
  type GuideScope,
  type GuideTx,
  type GuideVersion,
} from '../../api/guides'
import { breakSentences, getIngestFailures, recordVersions, setFailureListOpen, trackIngest, watchIngest } from '../../api/guideWatch'
import titleOps from '../../assets/mascot/title-ops.webp'
import { USE_MOCK_GUIDE } from '../../core/config'
import { formatDateTime } from '../../core/format'
import { GuideReaderPanel, type ReaderTarget } from '../../ui/GuideReaderPanel'
import { PolicyModal } from '../../ui/PolicyModal'
import { ScopeBadge } from '../../ui/ScopeBadge'
import { visiblePoll } from '../../core/poll'
import { HOME_BY_ROLE } from '../../core/roles'
import { useAuth } from '../../core/session'
import { Collapse } from '../../ui/Collapse'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'
import { useToast } from '../../ui/useToast'
import { StateBadge } from '../../ui/StateBadge'
import { Topbar } from '../../ui/Topbar'
import { CASES_FROM_SERVER, getAllCases, loadCases } from '../../api/caseClusters'
import { CaseGuideTab } from './CaseGuideTab'
import { CaseReviewPanel } from './CaseReviewPanel'
import { useReviewCount } from './useReviewCount'
import { ensureCaseVersions, registeredText, type CaseItem } from '../../api/mock/caseGuides'

const TX_CLS: Record<GuideTx, string> = { 허용: 'ok', '마스킹 후 허용': 'warn', 금지: 'urg' }
type Tab = 'list' | 'case'

export function GuidesView() {
  const { user } = useAuth()
  const [params] = useSearchParams()
  const [guides, setGuides] = useState<Guide[] | null>(null)
  const [vers, setVers] = useState<Record<number, GuideVersion[]>>({})
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('list')
  const [catOpen, setCatOpen] = useState<Record<string, boolean>>({})
  const [openId, setOpenId] = useState<number | null>(null)
  const [tick, setTick] = useState(0)
  const [hideInactive, setHideInactive] = useState(false)
  // 가이드 본문을 오른쪽 패널로 읽는다 (관리자는 버전마다)
  const [reader, setReader] = useState<ReaderTarget | null>(null)
  // 해결 사례 탭의 검토 패널
  const [casePanel, setCasePanel] = useState<string | null>(null)
  // 적재에 실패한 버전 (가이드·분류 옆 점). 추적 기록은 api/guideWatch.ts 가 관리한다
  const failures = useSyncExternalStore(watchIngest, getIngestFailures)
  const failDocs = useMemo(() => new Set(failures.map((f) => f.docId)), [failures])
  const failCats = useMemo(() => new Set(failures.map((f) => f.cat)), [failures])
  const guidesRef = useRef<Guide[] | null>(null)
  const { say, fail } = useToast()
  const [dlg, setDlg] = useState<null | { kind: 'upload' } | { kind: 'ingest'; g: Guide; v: GuideVersion } | { kind: 'active'; g: Guide; to: boolean } | { kind: 'tx'; g: Guide; v: GuideVersion; to: GuideTx } | { kind: 'blocked'; g: Guide; n: number }>(null)
  const admin = user?.serviceRole === 'ADMIN'
  useEffect(() => {
    guidesRef.current = guides
  }, [guides])

  useEffect(() => watchGuides(() => setTick((n) => n + 1)), [])
  // 적재 추적이 결과를 알아내면(성공·실패·멈춤) 바로 다시 읽는다. 그래서 화면 쪽 주기 조회는 느려도 된다
  useEffect(() => watchIngest(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    if (!user || !admin) return
    let alive = true
    listGuides(user).then((r) => {
      if (!alive) return
      if (r.ok) {
        setGuides(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, tick])

  // 다른 화면에서 ?doc=문서번호 로 오면 그 가이드를 펼친다 (AI 운영의 "해당 가이드로 이동")
  const wantDoc = params.get('doc')
  const [shownDoc, setShownDoc] = useState<string | null>(null)
  if (wantDoc && guides && shownDoc !== wantDoc) {
    const g = guides.find((x) => x.docCode === wantDoc)
    setShownDoc(wantDoc)
    if (g) {
      setCatOpen((m) => ({ ...m, [g.cat]: true }))
      setOpenId(g.id)
    }
  }

  // 열린 가이드의 버전을 읽는다 (서버는 열 때 읽고, 바뀌면 다시 읽는다)
  useEffect(() => {
    if (!user || !admin || openId === null) return
    let alive = true
    listGuideVersions(user, openId).then((r) => {
      if (!alive || !r.ok) return
      setVers((m) => ({ ...m, [openId]: r.data }))
      const g = guidesRef.current?.find((x) => x.id === openId)
      if (g) recordVersions({ docId: g.id, docCode: g.docCode, title: g.title, cat: g.cat }, r.data)
    })
    return () => {
      alive = false
    }
  }, [user, admin, openId, tick])

  // 검색 준비(적재)가 진행 중인 버전이 있으면 끝날 때까지 몇 초마다 다시 읽는다
  useEffect(() => {
    if (!Object.values(vers).some((l) => l.some((x) => x.ready === '준비 중'))) return
    return visiblePoll(() => setTick((n) => n + 1), 10_000)
  }, [vers])

  const reviewN = useReviewCount()
  // 해결 사례로 승인해 둔 시연 이력의 버전을 가이드 목록(모의)에 한 번 등록한다
  useEffect(() => {
    if (USE_MOCK_GUIDE) ensureCaseVersions()
  }, [])
  // 해결 사례 → 현행으로 전환: 바로 바꾸지 않고 가이드 목록의 그 문서를 펼쳐 열람 범위를 눈으로 확인한 뒤 거기서 전환하게 한다
  const goLive = (c: CaseItem) => {
    if (!c.registered) return
    setCasePanel(null)
    setReader(null)
    setTab('list')
    setCatOpen((m) => ({ ...m, [c.cat]: true }))
    setOpenId(c.registered.docId)
    say(`${c.registered.docCode} ${c.registered.version}의 열람 범위를 확인하고 현행으로 전환해 주세요.`)
  }

  if (user && !admin) return <Navigate to={HOME_BY_ROLE[user.serviceRole]} replace />
  if (!user) return null

  const shown = guides?.filter((g) => !hideInactive || g.isActive)
  const inactiveN = guides?.filter((g) => !g.isActive).length ?? 0
  const cats = (Object.keys(CATEGORIES) as CategoryCode[]).filter((c) => shown?.some((g) => g.cat === c))
  const allOpen = cats.length > 0 && cats.every((c) => catOpen[c])
  const reload = () => setTick((n) => n + 1)

  const changeTx = (g: Guide, v: GuideVersion, to: GuideTx) => {
    // 더 느슨해지면 사유가 필수, 더 엄격해져도 사유를 남길 수 있게 창을 띄운다 (사유는 선택)
    setDlg({ kind: 'tx', g, v, to })
  }
  const applyTx = async (g: Guide, v: GuideVersion, to: GuideTx, why: string) => {
    const r = await setGuideTransfer(user, g.id, v.id, to, why)
    if (!r.ok) return fail(r.error.message)
    say(`외부 전송 정책을 ${to}${to === '금지' ? '로' : '으로'} 바꿨어요.`)
    reload()
  }
  const retryIngest = async (g: Guide, v: GuideVersion, file?: File) => {
    if (file && file.size > MAX_UPLOAD_BYTES) return fail(MAX_UPLOAD_MESSAGE)
    const r = await retryGuideIngest(user, g.id, v.id, file)
    if (!r.ok) return fail(r.error.message)
    trackIngest({ docId: g.id, versionId: v.id, docCode: g.docCode, title: g.title, cat: g.cat, version: v.version })
    say(file ? `${v.version} 파일을 바꿔 검색 준비를 다시 시작했어요.` : `${v.version} 검색 준비를 다시 시작했어요.`)
    reload()
  }
  const applyActive = async (g: Guide, to: boolean) => {
    const r = await setGuideActive(user, g.id, to)
    if (!r.ok) return fail(r.error.message)
    say(to ? `${g.docCode}을(를) 활성화했어요.` : `${g.docCode}을(를) 비활성화했어요. 번호는 그대로 남아요.`)
    reload()
  }
  const makeCurrent = async (g: Guide, v: GuideVersion) => {
    // 이 가이드에 아직 검토하지 않은 AI 가이드 제안이 있으면 현행을 바꾸지 못하게 막는다 (바뀌면 그 제안은 기준 가이드가 달라져 등록할 수 없게 된다)
    if (CASES_FROM_SERVER) await loadCases()
    const n = getAllCases().filter((c) => c.state === 'review' && c.target?.docCode === g.docCode).length
    if (n > 0) return setDlg({ kind: 'blocked', g, n })
    const r = await setGuideCurrent(user, g.id, v.id)
    if (!r.ok) return fail(r.error.message)
    say(v.state === '만료' ? `${v.version}을(를) 다시 현행으로 되돌렸어요.` : '현행 버전을 바꿨어요.')
    reload()
  }

  const gpanel = (g: Guide) => {
    const open = openId === g.id
    const list = vers[g.id] ?? g.versions
    return (
      <div className={`gprow${g.isActive ? '' : ' off'}`} key={g.id}>
        <div className="gprh">
        <button type="button" className="grb" aria-expanded={open} onClick={() => setOpenId(open ? null : g.id)}>
          <span className="grt">
            <span className="grtl">
              <b>{guideLabel(g)}</b>
              {failDocs.has(g.id) && <span className="fdot" role="img" aria-label="적재 실패가 있어요" title="적재에 실패한 버전이 있어요" />}
              {!g.isActive && <StateBadge tone="recv" label="비활성" />}
            </span>
            <div className="small muted">
              {g.current ? `현행 ${g.current.version}` : '현행 없음'}
              {!g.isActive && ' · 검색·답변에 쓰이지 않아요'}
            </div>
          </span>
          <span className="gbs">
            <span className="gb1">{g.current?.scope && <ScopeBadge scope={g.current.scope} />}</span>
            <span className="gb2">{g.current?.tx === '금지' ? <StateBadge tone="urg" label="외부 전송 금지" /> : g.current?.tx === '마스킹 후 허용' ? <StateBadge tone="warn" label="마스킹 후 전송" /> : null}</span>
          </span>
        </button>
        </div>
        <Collapse open={open}>
        {open && (
          <div className="gvt-wrap">
            {/* 문서 전체를 켜고 끄는 버튼: 접었을 때 줄 정렬을 흔들지 않도록 펼친 영역 안 오른쪽 위에 둔다 */}
            <div className="gvt-bar">
              <span className="small muted">{list ? `버전 ${list.length}개` : ''}</span>
              <button type="button" className={`btn ${g.isActive ? 'sec' : 'pri'} sm`} aria-label={`${g.docCode} ${g.isActive ? '비활성화' : '활성화'}`} onClick={() => setDlg({ kind: 'active', g, to: !g.isActive })}>
                {g.isActive ? '비활성화' : '활성화'}
              </button>
            </div>
          <div className="tw gvt">
            {!list ? (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>버전</th>
                    <th className="c">상태</th>
                    <th className="c">검색 준비</th>
                    <th>열람 범위</th>
                    <th className="c" title="이 가이드의 내용을 외부 AI 모델에 보내 답변 생성에 써도 되는지">
                      외부 AI 전송
                    </th>
                    <th className="c">현행 관리</th>
                    <th>올린 시각</th>
                    <th className="c">본문</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((v) => (
                    <tr key={v.id} className={v.state === '현행' ? 'vcur' : v.state === '만료' ? 'vold' : undefined}>
                      <td>
                        <b>{v.version}</b>
                      </td>
                      <td className="c">
                        <StateBadge tone={v.state === '현행' ? 'ok' : v.state === '초안' ? 'warn' : 'recv'} label={v.state} />
                      </td>
                      <td className="c">
                        {v.ready === '준비 실패' ? (
                          <button type="button" className="rfail" aria-label={`${v.version} 준비 실패 사유 보기`} title="실패 사유와 다시 시도 보기" onClick={() => setDlg({ kind: 'ingest', g, v })}>
                            <StateBadge tone="urg" label="준비 실패" />
                            <span className="rfm">사유 보기</span>
                          </button>
                        ) : (
                          <StateBadge tone={v.ready === '준비 완료' ? 'ok' : 'warn'} label={v.ready} />
                        )}
                      </td>
                      <td>
                        <ScopeBadge scope={v.scope} />
                      </td>
                      <td className="c">
                        <div className="seg tx" role="group" aria-label={`${v.version} 외부 AI 전송`}>
                          {GUIDE_TXS.slice()
                            .reverse()
                            .map((k) => (
                              <button key={k} type="button" className={v.tx === k ? `on ${TX_CLS[k]}` : ''} aria-pressed={v.tx === k} title={v.tx === k ? undefined : `${k}(으)로 바꾸기`} onClick={() => v.tx !== k && changeTx(g, v, k)}>
                                {k}
                              </button>
                            ))}
                        </div>
                      </td>
                      <td className="c">
                        {v.state !== '현행' && (
                          <button type="button" className="btn ghost sm" disabled={v.ready !== '준비 완료'} title={v.ready !== '준비 완료' ? '검색 준비가 끝나야 현행으로 바꿀 수 있어요' : v.state === '만료' ? '이전 버전을 다시 현행으로 되돌려요' : undefined} onClick={() => void makeCurrent(g, v)}>
                            현행 전환
                          </button>
                        )}
                      </td>
                      <td className="nw">
                        {v.registeredAt ? formatDateTime(v.registeredAt) : '-'}
                        {v.registeredAt && Date.now() - Date.parse(v.registeredAt) < 24 * 3600_000 && <span className="nwb">NEW</span>}
                      </td>
                      <td className="c">
                        <button type="button" className="btn sec sm" aria-label={`${g.docCode} ${v.version} 본문 보기`} onClick={() => setReader({ id: g.id, docCode: g.docCode, title: g.title, versionId: v.id, version: v.version })}>
                          보기
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          </div>
        )}
        </Collapse>
      </div>
    )
  }

  const list = guides && (
    <>
      {failures.length > 0 && (
        <div className="alert err" role="status" style={{ margin: 0 }}>
          <Icon name="alert" />
          <div>
            검색 준비(적재)에 실패한 가이드 버전이 <b>{failures.length}개</b> 있어요. 실패한 버전은 현행으로 바꿀 수 없어요.
            <button type="button" className="btn ghost sm" onClick={() => setFailureListOpen(true)}>
              실패 목록 보기
            </button>
          </div>
        </div>
      )}
      <div className="row" style={{ justifyContent: 'space-between', margin: 0 }}>
        <span className="small muted">
          분류 {cats.length}개 · 가이드 {shown?.length ?? 0}개{inactiveN > 0 && !hideInactive ? ` (비활성 ${inactiveN}개 포함)` : ''}
        </span>
        <span className="row" style={{ gap: 4 }}>
          {inactiveN > 0 && (
            <button type="button" className="btn ghost sm" aria-pressed={hideInactive} onClick={() => setHideInactive((x) => !x)}>
              {hideInactive ? '비활성 문서도 보기' : '비활성 문서 숨기기'}
            </button>
          )}
          <button type="button" className="btn ghost sm" onClick={() => setCatOpen(allOpen ? {} : Object.fromEntries(cats.map((c) => [c, true])))}>
            {allOpen ? '모두 접기' : '모두 펼치기'}
          </button>
        </span>
      </div>
      <div className="gseclist">
        {cats.map((c) => {
          const gs = (shown ?? []).filter((g) => g.cat === c)
          const open = !!catOpen[c]
          return (
            <section key={c} className={`gsec${open ? ' open' : ''}`}>
              <button type="button" className="gcb" aria-expanded={open} onClick={() => setCatOpen((m) => ({ ...m, [c]: !m[c] }))}>
                <span className={`tag c-${c} gcbar`} aria-hidden="true" />
                <span className="gcm">
                  <b>
                    {CATEGORIES[c].name}
                    {failCats.has(c) && <span className="fdot" role="img" aria-label="적재 실패가 있어요" title="적재에 실패한 가이드가 있어요" />}
                  </b>
                  <small>
                    {guideLabel(gs[0])}
                    {gs.length > 1 ? ` 외 ${gs.length - 1}개` : ''}
                  </small>
                </span>
                <span className="gcr">
                  <span className="gcn">{gs.length}개</span>
                  <span className={`gchv${open ? ' on' : ''}`} aria-hidden="true">
                    <Icon name="chevronDown" />
                  </span>
                </span>
              </button>
              <Collapse open={open} className="gcp">
                {open && gs.map(gpanel)}
              </Collapse>
            </section>
          )
        })}
      </div>
    </>
  )

  return (
    <>
      <main className="main">
        <Topbar title="가이드 관리" sub="AI 답변의 근거가 되는 문서" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">KNOWLEDGE</div>
              <h1>AI 답변의 근거를 관리해요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                현재 사용 중인 버전 중 검색 준비가 완료된 버전만 AI 답변에 활용돼요.
              </p>
            </div>
            <div>
              <p className="muted">
                <b>외부 AI 전송</b>은 이 가이드 내용을 AI 모델에 보내 답변을 만들어도 되는지에 관한 설정이에요(문서 열람 권한인 열람 범위와는 별개). <b>허용</b>은 그대로 보내고, <b>마스킹 후 허용</b>은 민감정보를 가린 내용만 보내요. <b>금지</b>인 가이드 내용은 외부 AI에 보내지 않아요. 사용할 수 있는 근거가 없으면 담당자 연결을 제안해요. 열람 범위와 전송 정책을 정하지 않으면 관리자만·금지로 처리돼요.
              </p>
            </div>
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div className="seg" role="group" aria-label="보기">
                <button type="button" className={tab === 'list' ? 'on' : ''} aria-pressed={tab === 'list'} onClick={() => setTab('list')}>
                  가이드 목록 <span className="count">{guides?.length ?? 0}</span>
                </button>
                <button type="button" className={tab === 'case' ? 'on' : ''} aria-pressed={tab === 'case'} onClick={() => setTab('case')}>
                  AI 가이드 제안 <span className="count">{reviewN}</span>
                </button>
              </div>
              {tab === 'list' && (
                <button type="button" className="btn pri sm" onClick={() => setDlg({ kind: 'upload' })}>
                  <Icon name="plus" />
                  가이드 파일 업로드
                </button>
              )}
            </div>

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={reload}>
                    다시 시도
                  </button>
                </div>
              </div>
            )}

            {tab === 'list' ? (
              guides ? (
                list
              ) : (
                <div className="empty" role="status">
                  불러오는 중이에요…
                </div>
              )
            ) : (
              <CaseGuideTab
                onReview={(c) => {
                  setReader(null)
                  setCasePanel(c.id)
                }}
                onVersion={(c) => {
                  setCasePanel(null)
                  if (!c.registered) return
                  const t = { id: c.registered.docId, docCode: c.registered.docCode, title: c.target?.title ?? c.title ?? c.topic, version: c.registered.version }
                  // 서버 연결 환경에서는 등록한 버전의 본문을 서버에서 읽고, 모의에서는 제안 내용을 보여 준다
                  setReader(CASES_FROM_SERVER ? { ...t, versionId: c.registered.versionId } : { ...t, text: registeredText(c) })
                }}
                onGoLive={goLive}
              />
            )}
          </div>
        </div>
      </main>
      {reader && <GuideReaderPanel target={reader} onClose={() => setReader(null)} />}
      {casePanel && <CaseReviewPanel key={casePanel} id={casePanel} onClose={() => setCasePanel(null)} onGoLive={goLive} />}
      {dlg?.kind === 'upload' && (
        <UploadDialog
          guides={guides ?? []}
          onClose={() => setDlg(null)}
          onActivate={(g) => setDlg({ kind: 'active', g, to: true })}
          onDone={(u) => {
            setDlg(null)
            setTab('list')
            setCatOpen((m) => ({ ...m, [u.cat]: true }))
            setOpenId(u.docId)
            // 검색 준비가 끝나는지(실패하는지)를 다른 화면에 있어도 알 수 있게 추적한다
            if (u.versionId) trackIngest({ docId: u.docId, versionId: u.versionId, docCode: u.docCode, title: u.title, cat: u.cat, version: u.version })
            say(`${u.version}을(를) 초안으로 올렸어요. 검색 준비가 끝나면 내용을 확인한 뒤 '현행 전환'을 눌러 주세요.`)
            reload()
          }}
        />
      )}
      {dlg?.kind === 'ingest' && (
        <IngestDialog
          g={dlg.g}
          v={dlg.v}
          onClose={() => setDlg(null)}
          onRetry={(file) => {
            const d = dlg
            setDlg(null)
            void retryIngest(d.g, d.v, file)
          }}
        />
      )}
      {dlg?.kind === 'blocked' && (
        <Modal title="현행을 바꿀 수 없어요" variant="form" onClose={() => setDlg(null)}>
          <p style={{ margin: 0 }}>
            <b>{dlg.g.docCode} {dlg.g.title}</b>에 검토할 AI 가이드 제안이 <b>{dlg.n}건</b> 있어요. 제안을 먼저 확인한 뒤 현행을 변경해 주세요.
          </p>
          <p className="small muted" style={{ margin: 0 }}>
            현행을 바꾸면 이 제안들의 기준 가이드가 달라져서 그대로 등록할 수 없게 돼요.
          </p>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setDlg(null)}>
              닫기
            </button>
            <button
              type="button"
              className="btn pri"
              onClick={() => {
                setDlg(null)
                setTab('case')
              }}
            >
              AI 가이드 제안 보기
            </button>
          </div>
        </Modal>
      )}
      {dlg?.kind === 'active' && (
        <ActiveDialog
          g={dlg.g}
          to={dlg.to}
          onClose={() => setDlg(null)}
          onApply={() => {
            const d = dlg
            setDlg(null)
            void applyActive(d.g, d.to)
          }}
        />
      )}
      {dlg?.kind === 'tx' && (
        <TxDialog
          g={dlg.g}
          v={dlg.v}
          to={dlg.to}
          onClose={() => setDlg(null)}
          onApply={(why) => {
            const d = dlg
            setDlg(null)
            void applyTx(d.g, d.v, d.to, why)
          }}
        />
      )}
    </>
  )
}

/** 업로드가 끝났을 때 알려 주는 값. 업로드한 버전은 항상 초안이고, 현행 전환은 관리자가 직접 한다 */
interface Uploaded {
  docId: number
  docCode: string
  title: string
  versionId: number
  cat: CategoryCode
  version: string
}

const VERSION_TONE = { 현행: 'ok', 초안: 'prog', 만료: 'recv' } as const

const safeJson = (s: string): unknown => {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

/** 적재 실패 사유 창: 사유와 안내를 보여 주고 같은 파일로 / 파일을 바꿔 다시 시도하게 한다 */
function IngestDialog({ g, v, onClose, onRetry }: { g: Guide; v: GuideVersion; onClose: () => void; onRetry: (file?: File) => void }) {
  return (
    <Modal title="검색 준비에 실패했어요" onClose={onClose}>
      <p className="small muted">
        {guideLabel(g)} · {v.version}
      </p>
      <div className="alert warn">
        <Icon name="alert" />
        <div style={{ whiteSpace: 'pre-line' }}>{breakSentences(v.error || '실패 사유를 받지 못했어요.')}</div>
      </div>
      <p className="small muted">실패한 버전은 현행으로 바꿀 수 없어요. 같은 파일은 다시 올릴 수 없어서, 아래에서 다시 시도하거나 글자가 있는 원본 파일로 바꿔 시도해 주세요.</p>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          닫기
        </button>
        <button type="button" className="btn sec" onClick={() => onRetry()}>
          같은 파일로 다시 시도
        </button>
        <label className="btn pri" style={{ cursor: 'pointer' }}>
          파일 바꿔 시도
          <input
            type="file"
            className="sr"
            accept=".pdf,.docx,.pptx,.md,.txt"
            aria-label={`${v.version} 파일을 바꿔서 검색 준비 다시 시도`}
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) onRetry(f)
            }}
          />
        </label>
      </div>
    </Modal>
  )
}

/** 문서 활성화·비활성화 확인 창. 활성화하면 비활성화 전의 현행 버전이 바로 검색·답변에 쓰이므로 한 번 더 묻는다 */
function ActiveDialog({ g, to, onClose, onApply }: { g: Guide; to: boolean; onClose: () => void; onApply: () => void }) {
  return (
    <Modal title={to ? '가이드를 활성화할까요?' : '가이드를 비활성화할까요?'} onClose={onClose}>
      <p className="small muted">{guideLabel(g)}</p>
      <div className="alert warn">
        <Icon name="alert" />
        <div>
          {to ? (
            <>
              활성화하면 비활성화 전의 현행 버전이 <b>바로 검색·답변에 쓰여요.</b> 현행 버전의 내용과 외부 AI 전송 정책을 한 번 더 확인해 주세요.
              <br />
              비활성화할 때 자동으로 내려간 FAQ는 활성화해도 <b>다시 게시되지 않아요.</b> 필요하면 FAQ를 직접 다시 게시해 주세요.
            </>
          ) : (
            <>
              비활성화하면 이 가이드의 현행 버전이 검색·답변에서 빠지고, 이 가이드를 근거로 게시된 FAQ도 자동으로 내려가요. 목록에는 그대로 남고 문서 번호도 바뀌지 않아요.
              <br />
              다시 활성화해도 내려간 FAQ는 자동으로 다시 게시되지 않아요.
            </>
          )}
        </div>
      </div>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" onClick={onApply}>
          {to ? '활성화' : '비활성화'}
        </button>
      </div>
    </Modal>
  )
}

/** 가이드 파일 업로드: 기존 가이드에 새 버전을 만들거나(DC-07), 새 가이드를 만든다(DC-02 → DC-07) */
function UploadDialog({ guides, onClose, onDone, onActivate }: { guides: Guide[]; onClose: () => void; onDone: (u: Uploaded) => void; onActivate: (g: Guide) => void }) {
  const { user } = useAuth()
  const uid = useId()
  // 고르기 전에는 가이드가 있으면 기존 가이드에 새 버전, 없으면 새 가이드 (가이드 목록이 늦게 와도 따라간다)
  const [picked, setPicked] = useState<'ver' | 'new' | null>(null)
  const mode = picked ?? (guides.length ? 'ver' : 'new')
  const [file, setFile] = useState<File | null>(null)
  const [fileKey, setFileKey] = useState(0)
  const [drag, setDrag] = useState(false)
  // 고른 파일의 단계: 확인 중(잠깐) → 준비됨. 제출은 확인이 끝나기를 기다린다
  const [phase, setPhase] = useState<'idle' | 'checking' | 'ready'>('idle')
  const fileRef = useRef<File | null>(null)
  const checkRef = useRef<Promise<string | null>>(Promise.resolve(null))
  const [cat, setCat] = useState<CategoryCode | ''>('')
  const [docId, setDocId] = useState<number | null>(null)
  const [docVers, setDocVers] = useState<GuideVersion[] | null>(null)
  const [title, setTitle] = useState('')
  const [ver, setVer] = useState('')
  const [policyOpen, setPolicyOpen] = useState(false)
  const pending = useRef<{ version: string } | null>(null)
  const [scope, setScope] = useState<GuideScope>('관리자만')
  const [tx, setTx] = useState<GuideTx>('금지')
  // 파일 머리의 version: 값 (md·txt 만 읽는다). 서버는 이 값과 입력한 버전이 다르면 적재를 실패 처리한다
  const [fileVer, setFileVer] = useState<string | null>(null)
  // 문서 등록(DC-02)은 됐는데 파일 업로드(DC-07)가 실패하면 만든 문서 id 를 기억해 두었다가 다음에는 DC-07 만 다시 부른다
  const [madeDoc, setMadeDoc] = useState<number | null>(null)
  // 같은 파일이 이미 올라간 문서가 비활성일 때: 업로드 대신 활성화를 안내한다
  const [dupDoc, setDupDoc] = useState<Guide | null>(null)
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const clr = (k: string) => setErrs((e) => ({ ...e, [k]: '' }))
  // 파일 고르기(클릭·끌어다 놓기 공통, 한 번에 파일 1개): 20MB 를 넘으면 막고, 잠깐 "확인 중"을 보인 뒤 md·txt 는 머리의 버전을 읽어 채운다
  const pickFile = (f: File | null) => {
    setDupDoc(null)
    if (f && f.size > MAX_UPLOAD_BYTES) {
      // 서버는 20MB 를 넘으면 받는 도중 연결을 끊어 네트워크 오류로 보이므로 먼저 막는다
      clearFile()
      setErrs((x) => ({ ...x, file: `${MAX_UPLOAD_MESSAGE} (선택한 파일 ${formatBytes(f.size)})` }))
      return
    }
    fileRef.current = f
    setFile(f)
    clr('file')
    setFileVer(null)
    if (!f) return setPhase('idle')
    setPhase('checking')
    checkRef.current = Promise.all([readFileVersion(f), new Promise((r) => setTimeout(r, 500))]).then(([fv]) => {
      if (fileRef.current !== f) return null // 그 사이 다른 파일을 골랐거나 취소했다
      setFileVer(fv)
      if (fv) {
        setVer(fv)
        clr('ver')
      }
      setPhase('ready')
      return fv
    })
  }
  const clearFile = () => {
    fileRef.current = null
    checkRef.current = Promise.resolve(null)
    setFile(null)
    setFileVer(null)
    setDupDoc(null)
    setPhase('idle')
    setFileKey((n) => n + 1)
  }

  const inCat = cat ? guides.filter((g) => g.cat === cat) : []
  // 새 버전을 올릴 문서 선택에서는 비활성 문서를 뺀다 (서버는 허용하지만 화면에서는 먼저 활성화하게 한다)
  const selectable = inCat.filter((g) => g.isActive)
  const doc = docId === null ? null : (guides.find((g) => g.id === docId) ?? null)
  const newCode = cat ? nextDocCode(guides, cat) : ''

  const pickMode = (m: 'ver' | 'new') => {
    setPicked(m)
    setDocId(null)
    setDocVers(null)
    setVer(m === 'new' ? (fileVer ?? FIRST_VERSION) : (fileVer ?? ''))
    setErrs({})
  }
  const pickCat = (c: CategoryCode | '') => {
    setCat(c)
    setDocId(null)
    setDocVers(null)
    clr('cat')
    if (mode === 'new' && !ver) setVer(fileVer ?? FIRST_VERSION)
  }
  // 문서를 고르면 모든 버전을 읽어 보여 주고, 다음 버전 이름·앞 버전의 열람 범위·외부 전송 값을 채운다
  const pickDoc = async (id: number | null) => {
    setDocId(id)
    setDocVers(null)
    clr('doc')
    const g = guides.find((x) => x.id === id)
    if (!user || !g) return
    const r = g.versions ? { ok: true as const, data: g.versions } : await listGuideVersions(user, g.id)
    if (!r.ok) return setErr(r.error.message)
    setDocVers(r.data)
    setVer(fileVer ?? nextVersion(r.data))
    const last = r.data.find((x) => x.state === '현행') ?? r.data[0]
    if (last) {
      setScope(last.scope)
      setTx(last.tx)
    }
  }

  const submit = async () => {
    if (!user) return
    // 파일을 확인하는 중이면 끝나기를 기다린다(머리의 버전을 읽은 뒤 그 값으로 검사한다)
    const checked = file && phase === 'checking' ? await checkRef.current : undefined
    const fv = checked !== undefined ? checked : fileVer
    const e: Record<string, string> = {}
    if (!file) e.file = '파일을 선택해 주세요.'
    if (!cat) e.cat = '분류를 선택해 주세요.'
    if (mode === 'ver' && cat && !doc) e.doc = '문서를 선택해 주세요.'
    if (mode === 'new' && !title.trim()) e.title = '가이드 제목을 입력해 주세요.'
    const version = normalizeVersion(checked ? checked : ver)
    if (!(mode === 'ver' && !doc)) {
      if (!version) e.ver = '버전은 v4.0처럼 숫자로 적어 주세요.'
      else if (docVers?.some((x) => sameVersion(x.version, version))) {
        const same = docVers.find((x) => sameVersion(x.version, version))!
        e.ver = same.version === version ? '이미 있는 버전이에요. 다른 번호를 적어 주세요.' : `이미 있는 버전 ${same.version}과 같은 번호예요(${version}도 같은 버전으로 봐요). 다른 번호를 적어 주세요.`
      }
      else if (fv && fv !== version) e.ver = `파일 안의 version(${fv})과 달라요. 서버가 적재를 실패 처리하니 ${fv}으로 맞추거나 파일 안의 version 을 고쳐 주세요.`
    }
    setErrs(e)
    setErr('')
    if (Object.keys(e).length || !file || !cat || !version) return
    // 검증이 끝나면 열람 범위·외부 AI 전송을 정하는 창을 한 번 더 열고, 거기서 확인해야 올린다
    pending.current = { version }
    setPolicyOpen(true)
  }

  const upload = async (scope: GuideScope, tx: GuideTx) => {
    if (!user || !file || !cat || !pending.current) return
    const { version } = pending.current
    setScope(scope)
    setTx(tx)
    setPolicyOpen(false)
    setBusy(true)
    let made = madeDoc
    const r = mode === 'ver' && doc ? await uploadGuideVersion(user, doc.id, { file, version, scope, tx }) : await uploadGuide(user, { file, docCode: newCode, title, cat, scope, tx, version, docId: madeDoc ?? undefined }, (id) => { made = id; setMadeDoc(id) })
    setBusy(false)
    if (!r.ok) {
      if (r.error.code === 'DOCUMENT_FILE_DUPLICATE') {
        // 같은 파일이 이미 올라간 문서가 비활성이면 활성화를 안내한다 (details[0].value 에 documentId·docCode)
        const raw = r.error.details?.[0]?.value as unknown
        const val = (typeof raw === 'string' ? safeJson(raw) : raw) as { documentId?: number; docCode?: string } | null
        const hit = val ? guides.find((x) => x.id === val.documentId || x.docCode === val.docCode) : undefined
        if (hit && !hit.isActive) {
          setDupDoc(hit)
          return setErrs({ file: '이미 올라간 파일이에요.' })
        }
      }
      if (made !== null && mode === 'new') return setErr(`${r.error.message} 문서는 이미 만들어져 있어요. 업로드를 다시 누르면 파일만 다시 올려요.`)
      const f = r.error.details?.find((d) => d.field === 'docCode' || d.field === 'version' || d.field === 'file')
      if (f) return setErrs({ [f.field === 'docCode' ? 'title' : f.field === 'file' ? 'file' : 'ver']: r.error.code === 'DOCUMENT_FILE_DUPLICATE' ? r.error.message : (f.message ?? r.error.message) })
      return setErr(r.error.message)
    }
    const made2 = mode === 'ver' && doc ? null : (r.data as Guide)
    onDone({
      docId: doc && mode === 'ver' ? doc.id : made2!.id,
      docCode: doc && mode === 'ver' ? doc.docCode : newCode,
      title: doc && mode === 'ver' ? doc.title : title.trim(),
      versionId: made2 ? (made2.versions?.[0]?.id ?? 0) : (r.data as GuideVersion).id,
      cat,
      version,
    })
  }

  const field = (k: string, label: string, body: React.ReactNode, hint?: string) => (
    <div className="field gu-f">
      <label htmlFor={`${uid}-${k}`}>{label}</label>
      {body}
      {hint && !errs[k] && <div className="hint">{hint}</div>}
      {errs[k] && (
        <div className="ferr" id={`${uid}-${k}-e`} role="alert">
          {errs[k]}
        </div>
      )}
    </div>
  )
  return (
    <Modal title="가이드 파일 업로드" onClose={onClose}>
      <p className="small muted">PDF·DOCX·PPTX·MD·TXT 파일을 올리면 검색 준비(텍스트 추출·색인)를 거쳐 사용할 수 있어요.</p>
      <div className="seg gu-seg" role="group" aria-label="올리는 방식">
        <button type="button" className={mode === 'ver' ? 'on' : ''} aria-pressed={mode === 'ver'} onClick={() => pickMode('ver')}>
          기존 가이드에 새 버전 만들기
        </button>
        <button type="button" className={mode === 'new' ? 'on' : ''} aria-pressed={mode === 'new'} onClick={() => pickMode('new')}>
          새 가이드 만들기
        </button>
      </div>
      {field(
        'file',
        '파일',
        <div className="gz">
          {!file ? (
            <label
              className={`gdrop${drag ? ' drag' : ''}${errs.file ? ' err' : ''}`}
              htmlFor={`${uid}-file`}
              onDragOver={(e) => {
                e.preventDefault()
                setDrag(true)
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDrag(false)
                pickFile(e.dataTransfer.files?.[0] ?? null)
              }}
            >
              <input key={fileKey} id={`${uid}-file`} className="sr" type="file" accept=".pdf,.docx,.pptx,.md,.txt" aria-invalid={!!errs.file} onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
              <span className="gdi" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
                  <path d="M14 3v5h5M12 17v-6m0 0-2.5 2.5M12 11l2.5 2.5" />
                </svg>
              </span>
              <span className="gdt">
                <b>클릭해서 파일 고르기</b> 또는 끌어다 놓기
              </span>
              <span className="gdh">PDF·DOCX·PPTX·MD·TXT · 파일 1개 · 최대 {MAX_UPLOAD_BYTES / 1024 / 1024}MB</span>
            </label>
          ) : (
            <div className={`gfile${phase === 'checking' ? ' wait' : ''}`} role="status" aria-live="polite">
              <span className="gfi" aria-hidden="true">
                {phase === 'checking' || busy ? (
                  <span className="gspin" />
                ) : (
                  <svg viewBox="0 0 24 24">
                    <path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
                    <path d="M14 3v5h5M9 13h6M9 17h4" />
                  </svg>
                )}
              </span>
              <span className="gfm">
                <b title={file.name}>{file.name}</b>
                <small>
                  {busy ? '업로드 중…' : phase === 'checking' ? '파일을 확인하는 중…' : `용량 ${formatBytes(file.size)}${fileVer ? ` · 파일 안의 version: ${fileVer}` : ''}`}
                </small>
              </span>
              <button type="button" className="gfx" aria-label="선택 취소" title="선택 취소" disabled={busy} onClick={clearFile}>
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path d="M5 5l10 10M15 5 5 15" />
                </svg>
              </button>
            </div>
          )}
        </div>,
      )}
      {field(
        'cat',
        '분류',
        <SelectBox
          id={`${uid}-cat`}
          value={cat}
          invalid={!!errs.cat}
          placeholder="분류를 선택해 주세요"
          options={(Object.keys(CATEGORIES) as CategoryCode[]).map((c) => ({ value: c, label: CATEGORIES[c].name }))}
          onChange={(v) => pickCat(v as CategoryCode | '')}
        />,
      )}
      {mode === 'ver' ? (
        <>
          {field(
            'doc',
            '문서',
            !cat ? (
              <SelectBox id={`${uid}-doc`} value="" options={[]} disabled placeholder="분류를 먼저 선택해 주세요" onChange={() => {}} />
            ) : selectable.length ? (
              <SelectBox
                id={`${uid}-doc`}
                value={docId === null ? '' : String(docId)}
                invalid={!!errs.doc}
                placeholder="새 버전을 올릴 문서를 선택해 주세요"
                options={selectable.map((g) => ({ value: String(g.id), label: guideLabel(g) }))}
                onChange={(v) => void pickDoc(v ? Number(v) : null)}
              />
            ) : (
              <div className="hint">{inCat.length ? '이 분류의 문서가 모두 비활성이에요. 목록에서 활성화한 뒤 올려 주세요.' : '이 분류에는 아직 문서가 없어요. "새 가이드 만들기"로 올려 주세요.'}</div>
            ),
          )}
          {doc && (
            <div className="guv">
              <div className="guvh">
                <span className="mono">{doc.docCode}</span>
                <b>{doc.title}</b>
              </div>
              <div className="guvs">{docVers ? `이 가이드의 버전 ${docVers.length}개` : '버전을 불러오는 중이에요…'}</div>
              <ul className="guvl">
                {(docVers ?? []).map((x) => (
                  <li key={x.id}>
                    <b className="guvn">{x.version}</b>
                    <StateBadge tone={VERSION_TONE[x.state]} label={x.state} />
                    <small>
                      {x.scope} · 외부 전송 {x.tx} · {x.ready}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <>
          {cat && (
            <div className="gucat" aria-label={`${CATEGORIES[cat].name} 분류의 기존 가이드`}>
              <div className="guvs">이 분류에 있는 가이드 {inCat.length}개</div>
              {inCat.length ? (
                <ul>
                  {inCat.map((g) => (
                    <li key={g.id}>
                      <span className="mono">{g.docCode}</span>
                      <span>{g.title}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="hint">아직 없어요. 첫 가이드가 돼요.</div>
              )}
            </div>
          )}
          {field('code', '문서 번호', <input id={`${uid}-code`} className="inp" value={newCode} placeholder="분류를 선택하면 자동으로 정해져요" readOnly tabIndex={-1} aria-readonly="true" />, '직접 적을 수 없어요. 같은 분류의 다음 번호로 자동 부여돼요.')}
          {field('title', '가이드 제목', <input id={`${uid}-title`} className={`inp${errs.title ? ' err' : ''}`} value={title} autoComplete="off" aria-invalid={!!errs.title} onChange={(e) => { setTitle(e.target.value); clr('title') }} />)}
        </>
      )}
      {field('ver', '버전', <input id={`${uid}-ver`} className={`inp${errs.ver ? ' err' : ''}`} value={ver} placeholder="예) v4.0" autoComplete="off" style={{ maxWidth: 160 }} aria-invalid={!!errs.ver} onChange={(e) => { setVer(e.target.value); clr('ver') }} />)}
      <div className="hint">업로드한 버전은 초안으로 올라가요. 검색 준비가 끝나면 내용을 확인한 뒤 목록에서 "현행 전환"을 눌러 주세요. 현행으로 바꾸기 전에는 검색·답변에 쓰이지 않아요.</div>
      {dupDoc && (
        <div className="alert warn" role="alert">
          <Icon name="alert" />
          <div>
            이미 올라간 파일이에요. 그 문서({guideLabel(dupDoc)})가 비활성 상태라서, 새로 올리지 말고 활성화해 주세요.
            <div style={{ marginTop: 8 }}>
              <button type="button" className="btn sec sm" onClick={() => onActivate(dupDoc)}>
                그 문서 활성화하기
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="hint">업로드를 누르면 열람 범위와 외부 AI 전송 정책을 정하는 창이 한 번 더 열려요.{mode === 'ver' && doc ? ' 앞 버전의 값을 채워 둘게요.' : ''}</div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => void submit()}>
          업로드
        </button>
      </div>
      {policyOpen && (
        <PolicyModal
          initialScope={scope}
          initialTx={tx}
          intro={mode === 'ver' && doc ? '올릴 버전의 열람 범위와 외부 AI 전송 정책을 확인해 주세요. 앞 버전의 값을 채워 두었어요.' : '올릴 가이드의 열람 범위와 외부 AI 전송 정책을 정해 주세요. 정하지 않으면 가장 제한적인 값(관리자만·금지)이에요.'}
          confirmLabel="올리기"
          busy={busy}
          onClose={() => setPolicyOpen(false)}
          onConfirm={(sc, t2) => void upload(sc, t2)}
        />
      )}
    </Modal>
  )
}

function TxDialog({ g, v, to, onClose, onApply }: { g: Guide; v: GuideVersion; to: GuideTx; onClose: () => void; onApply: (why: string) => void }) {
  const uid = useId()
  const [why, setWhy] = useState('')
  const [err, setErr] = useState('')
  // 더 넓게 외부로 보내는 변경만 사유가 필수다 (서버도 이때만 요구한다)
  const wide = TX_RANK[to] > TX_RANK[v.tx]
  return (
    <Modal title="외부 전송 정책 변경" onClose={onClose}>
      <p className="small muted">
        {guideLabel(g)} {v.version} · {v.tx} → {to}
      </p>
      {wide && (
        <div className="alert warn">
          <Icon name="alert" />
          <div>이 가이드 내용이 이전보다 넓게 외부 AI 모델에 전달될 수 있어요. 변경 사유를 남겨 주세요.</div>
        </div>
      )}
      <div className="field">
        <label htmlFor={`${uid}-w`}>변경 사유 ({wide ? '필수' : '선택'})</label>
        <input id={`${uid}-w`} className={`inp${err ? ' err' : ''}`} value={why} placeholder={wide ? '예) 개인정보 없음을 확인함' : '예) 외부 전송 범위를 줄임'} maxLength={500} autoComplete="off" aria-invalid={!!err} onChange={(e) => { setWhy(e.target.value); setErr('') }} />
        {err && (
          <div className="ferr" role="alert">
            {err}
          </div>
        )}
        <div className="wcnt">
          <span className="hint">{wide ? '필수 입력값이에요. 운영 기록에 남아요.' : '필수 입력값은 아니에요. 운영 기록에 남아요.'}</span>
          <span className="hint">
            <b>{why.length}</b>/500
          </span>
        </div>
      </div>
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" onClick={() => (why.trim() || !wide ? onApply(why.trim()) : setErr('변경 사유를 입력해 주세요.'))}>
          변경
        </button>
      </div>
    </Modal>
  )
}
