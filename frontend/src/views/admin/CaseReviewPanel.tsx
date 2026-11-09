/**
 * 해결 사례 → 가이드 초안 검토 패널 (관리자). 근거 티켓·AI 판단 이유·경고를 확인하고, 기존 가이드 보강이면 기존 내용과 AI 수정 제안문을
 * 비교해 편집하고, 신규 가이드면 제목·분류·본문을 확인·편집한다. 열람 범위·외부 AI 전송 정책을 골라 승인하면
 * 현행이 아닌 초안 버전으로 가이드 목록에 등록되고 검색 준비가 시작된다 (현행 전환은 준비가 끝난 뒤 가이드 목록에서). 모의 환경에서는 모의 상태로 바뀐다.
 * 서버 연결 환경(api/caseClusters.ts)에서는 임시 저장(GC-05)·거절(GC-03)·직접 반영 표시(GC-04)에 더해 초안 등록(GC-06)·다시 맞추기(GC-07)·
 * 넣을 문서 변경(GC-08)을 한다. 등록은 글을 받지 않으므로 고친 글이 있으면 먼저 저장하고 그 응답의 번호로 등록한다.
 * 열람 범위·외부 AI 전송은 검토 중에는 보이지 않고, "승인하고 초안 등록"을 누르면 뜨는 창에서 한 번 더 확인하며 고른다.
 * 열고 닫는 모션과 크게 보기는 접수 상세·가이드 본문 패널과 같다.
 */
import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import type { GuideScope, GuideTx } from '../../api/guides'
import { CASES_FROM_SERVER, applyCase, getAllCases, loadCaseDetail, loadCases, rebaseServerCase, registerCase, rejectCase, saveCaseDraft, subscribeAllCases } from '../../api/caseClusters'
import { retryGuideIngest } from '../../api/guides'
import { CASE_KIND_LABEL, CASE_KIND_TONE, CASE_STATE_LABEL, CASE_STATE_TONE, approveCase, baseChanged, dropCase, rebaseCase, retryCase, saveCase, type CaseItem } from '../../api/mock/caseGuides'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { MarkdownField } from '../../ui/MarkdownField'
import { Modal } from '../../ui/Modal'
import { PolicyModal } from '../../ui/PolicyModal'
import { useOutsideClose } from '../../ui/useOutsideClose'
import { SelectBox } from '../../ui/SelectBox'
import { StateBadge } from '../../ui/StateBadge'
import { useToast } from '../../ui/useToast'
import { CaseTargetDialog } from './CaseTargetDialog'

/** 새 가이드 뼈대에서 "(작성 필요)" 자리가 남은 장. 서버가 등록할 때 같은 것을 거절하므로, 미리 알려 준다 */
const TODO_MARK = '(작성 필요)'
function todoChapters(md: string): string[] {
  const out: string[] = []
  let head = ''
  for (const line of md.split('\n')) {
    const m = /^##\s+(.+?)\s*$/.exec(line)
    if (m) head = m[1]
    else if (line.trim() === TODO_MARK && head && !out.includes(head)) out.push(head)
  }
  return out
}

export function CaseReviewPanel({ id, onClose, onGoLive }: { id: string; onClose: () => void; onGoLive: (c: CaseItem) => void }) {
  const cases = useSyncExternalStore(subscribeAllCases, getAllCases)
  const c = cases.find((x) => x.id === id)
  const { say, fail } = useToast()
  const { user } = useAuth()
  // 서버 연결 환경: 열 때 상세(초안·AI 판단·근거 티켓)를 읽는다
  const [loadErr, setLoadErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [applyOpen, setApplyOpen] = useState(false)
  const reloadDetail = () => {
    setLoadErr('')
    void loadCaseDetail(id).then((r) => {
      if (!r.ok) setLoadErr(r.error.message)
    })
  }
  useEffect(() => {
    if (CASES_FROM_SERVER) reloadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])
  const uid = useId()

  // 열릴 때 밀려 들어오고 닫을 때 밀려 나간 뒤에 실제로 닫는다 (움직임 줄이기 설정이면 바로 닫는다)
  const [wide, setWide] = useState(false)
  const [slid, setSlid] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const opener = useRef<HTMLElement | null>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
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
  useOutsideClose(close)
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

  // 편집 중인 값 (임시 저장·승인할 때 저장소에 반영한다)
  const [after, setAfter] = useState(c?.after ?? '')
  const [title, setTitle] = useState(c?.title ?? '')
  const [cat, setCat] = useState<CategoryCode>(c?.cat ?? 'ACC')
  const [compare, setCompare] = useState(false)
  const [dropOpen, setDropOpen] = useState(false)
  const [setOpen, setSetOpen] = useState(false)
  const [targetOpen, setTargetOpen] = useState(false)
  const [why, setWhy] = useState('')
  const [whyErr, setWhyErr] = useState('')
  const [err, setErr] = useState('')
  // 최신 내용으로 제안문이 바뀌면(기준 버전 맞추기) 편집창도 그 내용으로 바꾼다
  const [seen, setSeen] = useState(c?.after)
  if (c && c.after !== seen) {
    setSeen(c.after)
    setAfter(c.after)
  }

  // 상세를 읽고 나면 새 가이드 제목이 서버의 값(guide_title)으로 바뀐다
  const [seenTitle, setSeenTitle] = useState(c?.title)
  if (c && c.title !== seenTitle) {
    setSeenTitle(c.title)
    setTitle(c.title ?? '')
  }

  if (!c) return null
  const review = c.state === 'review'
  const srv = CASES_FROM_SERVER
  const waiting = srv && !c.server?.detail
  const canEdit = review && (!srv || !!c.server?.hasDraft)
  const changed = baseChanged(c) && c.state === 'review'
  const todo = srv && c.kind === 'new' && review ? todoChapters(after) : []
  const info = c.server?.info
  // 서버 연결: 등록할 수 없는 이유 (있으면 단추를 막고 이유를 보여 준다)
  const blocked = !srv
    ? ''
    : changed
      ? '기준 가이드가 바뀌었어요. "다시 맞추기"를 먼저 해 주세요.'
      : (c.server?.conflicts?.length ?? 0) > 0
        ? '새 현행과 달라진 항목을 비교해 초안을 고쳐 저장해 주세요.'
        : c.kind === 'new' && !c.target
          ? '넣을 문서를 먼저 연결해 주세요.'
          : !c.server?.hasDraft
            ? '아직 초안이 만들어지지 않았어요.'
            : todo.length > 0
              ? `"${TODO_MARK}"가 남은 장을 채워 주세요: ${todo.join(', ')}`
              : ''
  const draft = { title: c.kind === 'new' ? title : undefined, cat: c.kind === 'new' ? cat : undefined, after }
  const edit = { ...draft, scope: c.scope, tx: c.tx }
  const nm = c.kind === 'new' ? (title.trim() || c.topic) : c.topic

  const save = async () => {
    if (CASES_FROM_SERVER) {
      if (busy || !c.server) return
      setBusy(true)
      const r = await saveCaseDraft(id, after, c.server.draftRevision)
      setBusy(false)
      return r.ok ? say('임시 저장했어요.') : fail(r.error.message)
    }
    saveCase(id, draft)
    say('임시 저장했어요.')
  }
  const approve = async (sc: GuideScope, t2: GuideTx) => {
    setErr('')
    if (CASES_FROM_SERVER) {
      if (busy || !c.server) return
      setBusy(true)
      // 등록은 글을 받지 않는다: 고친 글이 있으면 먼저 저장하고, 그 응답의 번호로 등록한다
      let rev = c.server.draftRevision
      if (canEdit && after !== c.after) {
        const saved = await saveCaseDraft(id, after, rev)
        if (!saved.ok) {
          setBusy(false)
          setSetOpen(false)
          return setErr(saved.error.message)
        }
        rev = saved.data.server?.draftRevision ?? rev
      }
      const done = await registerCase(id, rev, sc, t2)
      setBusy(false)
      setSetOpen(false)
      if (!done.ok) return setErr(done.error.message)
      void loadCases()
      return say('초안으로 등록했어요. 검색 준비를 시작해요.')
    }
    const r = approveCase(id, { ...edit, scope: sc, tx: t2 })
    setSetOpen(false)
    if (!r.ok) return setErr(r.message)
    say('초안으로 등록했어요. 검색 준비를 시작해요.')
  }
  const drop = async () => {
    if (!why.trim()) return setWhyErr('사유를 입력해 주세요.')
    if (CASES_FROM_SERVER) {
      if (busy) return
      setBusy(true)
      const r = await rejectCase(id, why)
      setBusy(false)
      if (!r.ok) return setWhyErr(r.error.message)
      setDropOpen(false)
      return say('가이드화하지 않기로 했어요.')
    }
    const r = dropCase(id, why)
    if (!r.ok) return setWhyErr(r.message)
    setDropOpen(false)
    say('가이드화하지 않기로 했어요.')
  }
  const retry = async () => {
    if (CASES_FROM_SERVER) {
      if (!user || !c.registered) return
      const r = await retryGuideIngest(user, c.registered.docId, c.registered.versionId)
      if (!r.ok) return fail(r.error.message)
      void loadCases()
      return say('같은 버전으로 검색 준비를 다시 시작해요.')
    }
    const r = retryCase(id)
    if (!r.ok) return fail(r.message)
    say('같은 버전으로 검색 준비를 다시 시작해요.')
  }
  /** 가이드(또는 매뉴얼)에 직접 반영했다고 표시한다 */
  const markApplied = async () => {
    if (busy) return
    setBusy(true)
    const r = await applyCase(id)
    setBusy(false)
    setApplyOpen(false)
    if (!r.ok) return fail(r.error.message)
    say('직접 반영한 것으로 표시했어요.')
  }
  const rebase = async () => {
    if (CASES_FROM_SERVER) {
      if (busy || !c.server) return
      setBusy(true)
      setErr('')
      const r = await rebaseServerCase(id, c.server.draftRevision)
      setBusy(false)
      if (!r.ok) return setErr(r.error.message)
      const n = r.data.server?.conflicts?.length ?? 0
      return say(n ? `새 현행에 맞췄어요. 달라진 항목 ${n}건은 비교해서 초안을 고쳐 저장해 주세요.` : '새 현행에 맞췄어요. 이제 등록할 수 있어요.')
    }
    const r = rebaseCase(id)
    if (!r.ok) return fail(r.message)
    setCompare(false)
    say('최신 내용에 맞춘 제안으로 바꿨어요. 다시 검토해 주세요.')
  }

  return (
    <>
      <aside
        className={`detail crev${wide ? ' wide' : ''}${!slid && !leaving ? ' slide' : ''}${leaving ? ' leave' : ''}`}
        role="complementary"
        aria-label="가이드 초안 검토"
        onAnimationEnd={() => {
          if (leaving) finish()
          else setSlid(true)
        }}
      >
        <div className="dh">
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <div style={{ minWidth: 0 }}>
              <div className="small muted">
                <span className={`tag c-${c.cat}`}>{CATEGORIES[c.cat].name}</span> <StateBadge tone={CASE_KIND_TONE[c.kind]} label={CASE_KIND_LABEL[c.kind]} /> 근거 {c.ticketCount}건
              </div>
              <h3>{nm}</h3>
            </div>
            <span style={{ flex: 1 }} />
            <StateBadge tone={CASE_STATE_TONE[c.state]} label={CASE_STATE_LABEL[c.state]} />
            <button type="button" className="btn sec sm ico" aria-label={wide ? '패널 크기로 줄이기' : '크게 보기'} aria-pressed={wide} title={wide ? '패널 크기로 줄이기' : '화면 전체로 크게 보기'} onClick={() => setWide((w) => !w)}>
              <Icon name={wide ? 'minimize' : 'expand'} />
            </button>
            <button type="button" ref={closeBtn} className="btn sec sm ico" aria-label="닫기" onClick={close}>
              <Icon name="x" />
            </button>
          </div>
        </div>

        <div className="db crb">
          {changed && c.target && (
            <div className="alert warn" role="alert">
              <Icon name="alert" />
              <div>
                {c.target.baseVersion && c.target.latestVersion ? `기준 가이드가 ${c.target.baseVersion}에서 ${c.target.latestVersion}로 변경됐어요.` : '제안을 만든 뒤 기준 가이드가 바뀌었어요.'} 최신 내용과 비교한 뒤 다시 검토해 주세요. 그전에는 등록을 할 수 없어요.{' '}
                {c.latest && (
                  <button type="button" className="btn ghost sm" aria-expanded={compare} onClick={() => setCompare((v) => !v)}>
                    최신 버전과 비교
                  </button>
                )}
                {srv && c.kind !== 'new' && (
                  <button type="button" className="btn pri sm" disabled={busy} onClick={() => void rebase()}>
                    다시 맞추기
                  </button>
                )}
              </div>
            </div>
          )}
          {changed && compare && c.target && c.latest && (
            <section className="cgs" aria-label="최신 버전과 비교">
              <h4>
                최신 버전({c.target.latestVersion})과 비교 <span className="small muted">· {c.target.section}</span>
              </h4>
              <div className="cgcmp">
                <div>
                  <div className="asl">최신 가이드 내용</div>
                  <pre className="cgpre">{c.latest.before}</pre>
                </div>
                <div>
                  <div className="asl">최신 내용에 맞춘 수정 제안</div>
                  <pre className="cgpre new">{c.latest.after}</pre>
                </div>
              </div>
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <button type="button" className="btn pri sm" onClick={rebase}>
                  이 제안으로 바꾸고 다시 검토
                </button>
              </div>
            </section>
          )}

          {srv && review && (c.server?.conflicts?.length ?? 0) > 0 && (
            <section className="cgs" aria-label="새 현행과 달라진 항목">
              <h4>새 현행과 달라진 항목 <span className="count">{c.server?.conflicts?.length}</span></h4>
              <p className="small muted" style={{ margin: '0 0 8px' }}>
                초안을 만든 뒤 현행 가이드가 바뀌었어요. 오른쪽 현행 내용과 비교해 아래 초안을 고치고 <b>임시 저장</b>하면 충돌이 풀리고 등록할 수 있어요.
              </p>
              {c.server?.conflicts?.map((k) => (
                <div key={`${k.section}-${k.kind}`} style={{ marginBottom: 10 }}>
                  <div className="small" style={{ fontWeight: 700, marginBottom: 4 }}>
                    항목 {k.section} <span className="muted">· {k.message}</span>
                  </div>
                  <div className="cgcmp">
                    <div>
                      <div className="asl">초안을 만들 때의 원문</div>
                      <pre className="cgpre">{k.oldMd}</pre>
                    </div>
                    <div>
                      <div className="asl">지금 현행의 원문</div>
                      <pre className="cgpre new">{k.newMd}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </section>
          )}
          {(c.server?.fresh?.length ?? 0) > 0 && (
            <div className="alert warn" role="status">
              <Icon name="alert" />
              <div>
                <b>합치면서 확인할 내용이 있어요.</b> <span className="small muted">(서버가 저장하지 않아 이 화면에서만 볼 수 있어요)</span>
                <ul className="cgw" style={{ marginTop: 6 }}>
                  {c.server?.fresh?.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {c.state === 'preparing' && c.registered && (
            <div className="alert info" role="status">
              <Icon name="clock" />
              <div>
                <b>{c.registered.docCode} {c.registered.version}</b>로 초안을 등록했고 검색 준비 중이에요. 준비가 끝나기 전에는 같은 건을 다시 승인할 수 없어요.
              </div>
            </div>
          )}
          {c.state === 'failed' && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>{c.failReason}</div>
            </div>
          )}
          {c.state === 'ready' && c.registered && (
            <div className="alert info" role="status">
              <Icon name="check" />
              <div>
                <b>{c.registered.docCode} {c.registered.version}</b>가 검색 준비를 마쳤어요. 아직 현행이 아니라서 사용자 답변에는 쓰이지 않아요. 가이드 목록에서 열람 범위를 확인하고 현행으로 바꿔 주세요.
              </div>
            </div>
          )}
          {c.state === 'live' && c.registered && (
            <div className="alert info" role="status">
              <Icon name="check" />
              <div>
                <b>{c.registered.docCode} {c.registered.version}</b>이 현행으로 반영돼 사용자 답변에 쓰여요.
              </div>
            </div>
          )}
          {c.state === 'applied' && (
            <div className="alert info" role="status">
              <Icon name="check" />
              <div>직접 반영한 것으로 표시한 제안이에요.{c.server?.reviewedBy && ` 표시한 관리자: ${c.server.reviewedBy}`}</div>
            </div>
          )}
          {c.state === 'dropped' && (
            <div className="alert info" role="status">
              <Icon name="file" />
              <div>
                <div>가이드화하지 않기로 한 제안이에요.</div>
                {c.dropReason && <div style={{ marginTop: 4 }}>사유: {c.dropReason}</div>}
              </div>
            </div>
          )}
          {waiting && (
            <div className={loadErr ? 'alert err' : 'empty'} role={loadErr ? 'alert' : 'status'}>
              {loadErr ? (
                <>
                  <Icon name="alert" />
                  <div>
                    {loadErr}{' '}
                    <button type="button" className="btn ghost sm" onClick={reloadDetail}>
                      다시 시도
                    </button>
                  </div>
                </>
              ) : (
                '불러오는 중이에요…'
              )}
            </div>
          )}

          {!waiting && (
            <>
          <section className="cgs" aria-label="근거 티켓">
            <h4>
              근거 티켓 <span className="count">{c.ticketCount}</span>
            </h4>
            <div className="tw">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>접수번호</th>
                    <th>문의 요약</th>
                    <th>최종 처리 결과</th>
                  </tr>
                </thead>
                <tbody>
                  {c.tickets.map((t) => (
                    <tr key={t.no}>
                      <td className="mono nw">{t.no}</td>
                      <td>{t.summary}</td>
                      <td>{t.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="cgs" aria-label="AI 판단">
            <h4>AI 판단</h4>
            {/* 판단 이유는 티켓마다 한 줄씩 줄바꿈으로 온다 */}
            {c.reason.split('\n').filter((l) => l.trim()).map((l) => (
              <p key={l} style={{ margin: '0 0 6px' }}>
                {l}
              </p>
            ))}
            {info?.changeNote && (
              <p style={{ margin: '8px 0 6px' }}>
                <b>변경 이유</b> · {info.changeNote}
              </p>
            )}
            {(info?.guessed.length ?? 0) > 0 && (
              <p className="small" style={{ margin: '8px 0 6px' }}>
                <b>AI가 추측해서 쓴 칸</b> · {info?.guessed.join(', ')} <span className="muted">— 사실과 맞는지 확인하고 고쳐 주세요.</span>
              </p>
            )}
            {(info?.differences.length ?? 0) > 0 && (
              <div className="small" style={{ margin: '8px 0 6px' }}>
                <b>티켓마다 해결 방법이 달라요</b>
                <ul className="cgw" style={{ marginTop: 4 }}>
                  {info?.differences.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              </div>
            )}
            {c.warnings.length > 0 && (
              <ul className="cgw">
                {c.warnings.map((w) => (
                  <li key={w}>
                    <Icon name="alert" /> {w}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="cgs" aria-label="가이드 내용">
            <h4>{c.kind === 'amend' ? (c.before !== undefined ? '기존 내용과 AI 수정 제안' : 'AI 수정 제안') : c.kind === 'new' ? '신규 가이드 초안' : c.kind === 'sec' ? 'SEC 직접 검토 초안' : '매뉴얼 후보'}</h4>
            {srv && !c.server?.hasDraft ? (
              <>
                {info?.manualNote ? (
                  <div className="field">
                    <div className="asl">매뉴얼에 넣을 만한 내용</div>
                    <pre className="cgpre new" style={{ whiteSpace: 'pre-wrap' }}>{info.manualNote}</pre>
                  </div>
                ) : (
                  <p className="small muted" style={{ margin: '0 0 8px' }}>AI가 정리한 내용이 없어요. 근거 티켓을 보고 판단해 주세요.</p>
                )}
                {(info?.manualItems.length ?? 0) > 0 && (
                  <div className="field">
                    <div className="asl">가까운 매뉴얼 항목</div>
                    <ul className="cgw">
                      {info?.manualItems.map((m) => (
                        <li key={m}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="small muted" style={{ margin: 0 }}>
                  이 제안은 가이드 초안을 만들지 않아요. 위 내용을 참고해 매뉴얼에 직접 반영한 뒤 "직접 반영 표시"를 눌러 주세요.
                </p>
              </>
            ) : c.kind === 'amend' && c.target ? (
              <>
                <p className="small muted" style={{ margin: '0 0 8px' }}>
                  반영 위치: <b>{c.target.docCode} {c.target.title}</b>
                  {c.target.baseVersion && ` · 기준 ${c.target.baseVersion}`}
                  {c.target.section && ` · 항목 ${c.target.section}`}
                  {srv && review && (
                    <button type="button" className="btn ghost sm" style={{ marginLeft: 8 }} onClick={() => setTargetOpen(true)}>
                      넣을 문서 변경
                    </button>
                  )}
                </p>
                {c.before !== undefined ? (
                  <div className="cgcmp">
                    <div>
                      <div className="asl">기존 내용 ({c.target.baseVersion})</div>
                      <pre className="cgpre">{c.before}</pre>
                    </div>
                    <div>
                      <label className="asl" htmlFor={`${uid}-after`}>
                        AI 수정 제안문 {canEdit && <span className="muted">(고쳐서 쓸 수 있어요)</span>}
                      </label>
                      <MarkdownField id={`${uid}-after`} label="AI 수정 제안문" value={after} readOnly={!canEdit} onChange={setAfter} />
                    </div>
                  </div>
                ) : (
                  <div className="field">
                    <label className="asl" htmlFor={`${uid}-after`}>
                      AI 수정 제안문 {canEdit && <span className="muted">(고쳐서 쓸 수 있어요)</span>}
                    </label>
                    <MarkdownField id={`${uid}-after`} label="AI 수정 제안문" value={after} readOnly={!canEdit} tall onChange={setAfter} />
                  </div>
                )}
              </>
            ) : c.kind === 'sec' || c.kind === 'manual' ? (
              <div className="field">
                {srv && c.kind === 'sec' && (
                  <p className="small muted" style={{ margin: '0 0 8px' }}>
                    {c.target ? (
                      <>
                        반영 위치: <b>{c.target.docCode} {c.target.title}</b>
                        {c.target.baseVersion && ` · 기준 ${c.target.baseVersion}`}
                      </>
                    ) : (
                      '넣을 문서가 아직 없어요.'
                    )}
                    {review && (
                      <button type="button" className="btn ghost sm" style={{ marginLeft: 8 }} onClick={() => setTargetOpen(true)}>
                        넣을 문서 변경
                      </button>
                    )}
                  </p>
                )}
                <label className="asl" htmlFor={`${uid}-after`}>
                  티켓 글을 옮긴 초안 {canEdit && <span className="muted">(고쳐서 쓸 수 있어요)</span>}
                </label>
                <MarkdownField id={`${uid}-after`} label="초안" value={after} readOnly={!canEdit} tall onChange={setAfter} />
              </div>
            ) : (
              <>
                {srv && (
                  <p className="small muted" style={{ margin: '0 0 8px' }}>
                    {c.target ? (
                      <>
                        연결된 문서: <b>{c.target.docCode} {c.target.title}</b> · v1.0으로 등록돼요
                      </>
                    ) : (
                      '아직 연결된 문서가 없어요. 문서를 연결해야 초안으로 등록할 수 있어요.'
                    )}
                    {review && (
                      <button type="button" className={`btn ${c.target ? 'ghost' : 'pri'} sm`} style={{ marginLeft: 8 }} onClick={() => setTargetOpen(true)}>
                        {c.target ? '넣을 문서 변경' : '문서 연결'}
                      </button>
                    )}
                  </p>
                )}
                {todo.length > 0 && (
                  <div className="alert warn" role="status" style={{ marginBottom: 12 }}>
                    <Icon name="alert" />
                    <div>
                      <b>아직 채워야 할 장이 있어요.</b> 아래 본문에서 <code>{TODO_MARK}</code>로 남은 <b>{todo.join(', ')}</b>을(를) 직접 써 넣고 <b>임시 저장</b>하면 등록할 수 있어요.
                    </div>
                  </div>
                )}
                <div className="row2">
                  <div className="field">
                    <label htmlFor={`${uid}-title`}>제목</label>
                    <input id={`${uid}-title`} className="inp" value={title} readOnly={!review || srv} onChange={(e) => setTitle(e.target.value)} autoComplete="off" />
                  </div>
                  <div className="field">
                    <label htmlFor={`${uid}-cat`}>분류</label>
                    <SelectBox
                      id={`${uid}-cat`}
                      value={cat}
                      disabled={!review || srv}
                      options={(Object.keys(CATEGORIES) as CategoryCode[]).map((k) => ({ value: k, label: CATEGORIES[k].name, accent: k }))}
                      onChange={(v) => setCat(v as CategoryCode)}
                    />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor={`${uid}-body`}>
                    본문 {canEdit && <span className="small muted">(이런 경우 · 조치 방법 · 해결 확인 순서의 가이드 작성 기준에 맞춰 썼어요)</span>}
                  </label>
                  <MarkdownField id={`${uid}-body`} label="본문" value={after} readOnly={!canEdit} tall onChange={setAfter} />
                </div>
              </>
            )}
          </section>
            </>
          )}

          {!srv && !review && c.state !== 'dropped' && (
            <section className="cgs" aria-label="등록 설정">
              <h4>등록 설정</h4>
              <dl className="dl" style={{ margin: 0 }}>
                <dt>열람 범위</dt>
                <dd>{c.scope}</dd>
                <dt>외부 AI 전송</dt>
                <dd>{c.tx}</dd>
              </dl>
            </section>
          )}

          {err && (
            <div className="ferr" role="alert">
              {err}
            </div>
          )}
        </div>

        {(review || c.state === 'failed' || c.state === 'ready') && !waiting && (
        <div className="crf">
          {review && (
            <>
              {canEdit && (
                <button type="button" className="btn sec" disabled={busy} onClick={save}>
                  임시 저장
                </button>
              )}
              <button type="button" className="btn sec dng" disabled={busy} onClick={() => { setWhy(''); setWhyErr(''); setDropOpen(true) }}>
                비가이드화
              </button>
              <span style={{ flex: 1 }} />
              {srv ? (
                <>
                  {c.kind !== 'manual' && (
                    <button type="button" className="btn pri" disabled={busy || !!blocked} title={blocked || undefined} onClick={() => setSetOpen(true)}>
                      승인하고 초안 등록
                    </button>
                  )}
                  <button type="button" className={c.kind === 'manual' ? 'btn pri' : 'btn sec'} disabled={busy} onClick={() => setApplyOpen(true)}>
                    직접 반영 표시
                  </button>
                </>
              ) : (
                <button type="button" className="btn pri" disabled={changed} title={changed ? '기준 가이드가 바뀌어서 등록할 수 없어요. 최신 내용과 비교해 주세요.' : undefined} onClick={() => { setErr(''); setSetOpen(true) }}>
                  승인하고 초안 등록
                </button>
              )}
            </>
          )}
          {c.state === 'failed' && (
            <>
              <span style={{ flex: 1 }} />
              <button type="button" className="btn pri" onClick={retry}>
                검색 준비 다시 시도
              </button>
            </>
          )}
          {c.state === 'ready' && (
            <>
              {srv && (
                <button type="button" className="btn sec" disabled={busy} title="같은 버전에 거절한 제안이 들어 있을 때, 거절한 항목을 빼고 이 버전을 다시 만들어요." onClick={() => setSetOpen(true)}>
                  거절한 항목 빼고 다시 등록
                </button>
              )}
              <span style={{ flex: 1 }} />
              <button type="button" className="btn pri" onClick={() => onGoLive(c)}>
                현행으로 전환
              </button>
            </>
          )}
        </div>
        )}
      </aside>

      {setOpen && (
        <PolicyModal
          initialScope={c.scope}
          initialTx={c.tx}
          intro={srv ? '열람 범위와 외부 AI 전송 정책을 정해야 초안으로 등록할 수 있어요. 가이드 목록의 새 버전에 그대로 적용돼요. 같은 문서에 이어 쓰는 버전이면 값이 그 버전 전체에 적용돼요.' : '열람 범위와 외부 AI 전송 정책을 정해야 초안으로 등록할 수 있어요. 가이드 목록의 새 버전에 그대로 적용돼요.'}
          busy={busy}
          confirmLabel={c.state === 'ready' ? '다시 등록' : '초안으로 등록'}
          onClose={() => setSetOpen(false)}
          onConfirm={(sc, t2) => approve(sc, t2)}
        />
      )}
      {targetOpen && (
        <CaseTargetDialog
          c={c}
          onClose={() => setTargetOpen(false)}
          onDone={(m) => {
            setTargetOpen(false)
            say(m)
            void loadCases()
          }}
        />
      )}
      {applyOpen && (
        <Modal title="직접 반영했다고 표시할까요?" variant="form" onClose={() => setApplyOpen(false)}>
          <p className="small muted" style={{ margin: 0 }}>
            이 제안의 내용을 가이드나 매뉴얼에 직접 반영했을 때만 표시해 주세요. 표시하면 이 제안과 근거 티켓은 반영 완료로 바뀌고, 되돌릴 수 없어요.
          </p>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setApplyOpen(false)}>
              취소
            </button>
            <button type="button" className="btn pri" disabled={busy} onClick={markApplied}>
              반영했어요
            </button>
          </div>
        </Modal>
      )}
      {dropOpen && (
        <Modal title="가이드화하지 않을까요?" variant="form" onClose={() => setDropOpen(false)}>
          <p className="small muted" style={{ margin: 0 }}>
            이 제안은 가이드로 만들지 않고 닫아요. 사유는 기록에 남아요.
          </p>
          <div className="field">
            <label htmlFor={`${uid}-why`}>사유 (필수)</label>
            <textarea id={`${uid}-why`} className={`ta${whyErr ? ' err' : ''}`} maxLength={500} value={why} aria-invalid={!!whyErr} placeholder="예) 한 번만 있었던 일이라 가이드로 만들 필요가 없어요" onChange={(e) => { setWhy(e.target.value); setWhyErr('') }} />
            {whyErr && (
              <div className="ferr" role="alert">
                {whyErr}
              </div>
            )}
          </div>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setDropOpen(false)}>
              취소
            </button>
            <button type="button" className="btn pri" onClick={drop}>
              가이드화 안 함
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
