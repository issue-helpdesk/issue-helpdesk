/**
 * FAQ 화면 (제안 기능, PRD 4.16 · SRS FAQ-01).
 *
 * 열람이 허용된 Guide를 출처로 한 FAQ 목록이다. 열어 봐도 문의가 접수되지 않으며,
 * 해결되지 않으면 "상담하기"로 새 문의 화면에 질문을 채워 넘어간다.
 * 관리자는 FAQ 를 등록·수정하고, 게시를 멈췄다 다시 게시하고, 삭제할 수 있다 (FQ-03~05). 등록·수정 때 출처 가이드를 고른다.
 */
import { useEffect, useId, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { createFaq, deleteFaq, getFaqSources, listFaqs, setFaqActive, updateFaq } from '../../api/faq'
import { listGuides, type Guide } from '../../api/guides'
import { CATEGORY_NAME } from '../../api/mock/faqs'
import type { CategoryCode, GuideSource } from '../../api/chatTypes'
import type { ApiResult, Faq } from '../../api/types'
import { USE_MOCK_FAQ } from '../../core/config'
import { useAuth } from '../../core/session'
import titleFaq from '../../assets/mascot/title-faq.webp'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'
import { useToast } from '../../ui/useToast'
import { SourceList } from '../../ui/SourceList'
import { SourcePreview } from '../../ui/SourcePreview'
import { Topbar } from '../../ui/Topbar'

/** 출처 줄: 서버 FAQ 는 열기 전에는 비어 있어서 읽는 중·읽지 못함·없음을 구분한다. 같은 가이드는 제목을 한 번만 쓴다 */
function Sources({ f, loaded, onOpen }: { f: Faq; loaded: GuideSource[] | 'err' | undefined; onOpen: (s: GuideSource) => void }) {
  const list = f.sources.length ? f.sources : loaded
  if (list === 'err') return <>출처를 불러오지 못했어요.</>
  if (list === undefined) return <>{f.serverId === undefined ? '출처 정보가 없어요.' : '출처를 불러오는 중이에요…'}</>
  return list.length ? <SourceList sources={list} onOpen={onOpen} /> : <>출처 정보가 없어요.</>
}

/** 사라지는 모션(.faq.fout, 420ms)이 보이도록 결과를 그만큼 늦춘다. 모션을 쓸 수 없는 환경(테스트, 모션 줄이기)에서는 늦추지 않는다 */
async function withExitMotion<T>(job: Promise<ApiResult<T>>): Promise<ApiResult<T>> {
  const motion = typeof Element.prototype.animate === 'function' && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const [r] = await Promise.all([job, motion ? new Promise((done) => setTimeout(done, 430)) : null])
  return r
}

export function FaqView() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const admin = user?.serviceRole === 'ADMIN'
  const [faqs, setFaqs] = useState<Faq[] | null>(null) // null = 불러오는 중
  const [error, setError] = useState('')
  // 분류 칩: ''(전체)이면 모두 보인다
  const [cat, setCat] = useState('')
  // 서버 모드에서 FAQ 를 열 때 읽어 온 출처 (키: FAQ 번호). 'err' 는 읽지 못한 경우
  const [srcs, setSrcs] = useState<Record<string, GuideSource[] | 'err'>>({})
  // 관리자: 등록 창, 삭제 확인 창, 처리 결과 안내
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Faq | null>(null)
  const [deleting, setDeleting] = useState<Faq | null>(null)
  const { say, fail } = useToast()
  const [reload, setReload] = useState(0)
  const [preview, setPreview] = useState<GuideSource | null>(null)
  // 삭제하는 중인 FAQ (사라지는 모션용)
  const [leaving, setLeaving] = useState<string | null>(null)
  // 다시 불러오면서 새로 생긴 FAQ 는 위에서 열리며 들어온다 (처음 불러올 때는 그대로 보인다)
  const [known, setKnown] = useState<{ ids: Set<string>; fresh: Set<string> } | null>(null)
  // 새 문의 화면의 추천 FAQ 에서 넘어오면(?open=FAQ-001) 그 FAQ 를 펼쳐서 보여 준다
  const openId = useSearchParams()[0].get('open')

  // 처음 열 때와 관리자가 바꾼 뒤에 FAQ 목록을 불러온다 (화면이 사라진 뒤에는 상태를 바꾸지 않는다)
  useEffect(() => {
    if (!user) return
    let alive = true
    listFaqs(admin).then((r) => {
      if (!alive) return
      if (r.ok) setFaqs(r.data)
      else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, admin, reload])

  // 추천 FAQ 로 들어왔으면 목록이 그려진 뒤 그 FAQ 가 보이는 곳으로 내려간다
  useEffect(() => {
    if (!openId || !faqs) return
    document.getElementById(`faq-${openId}`)?.scrollIntoView?.({ block: 'center' })
  }, [openId, faqs])

  /** FAQ 를 열 때 출처가 없고 서버 FAQ 면 상세에서 출처를 읽는다 */
  const loadSources = (f: Faq) => {
    if (f.serverId === undefined || f.sources.length || srcs[f.id]) return
    getFaqSources(f.serverId).then((r) => setSrcs((m) => ({ ...m, [f.id]: r.ok ? r.data : 'err' })))
  }

  /** 오류 후 다시 불러오기 */
  function retry() {
    setError('')
    setFaqs(null)
    setReload((n) => n + 1)
  }

  /** 관리자 동작 하나를 실행하고 결과를 안내한다 (실패하면 서버가 준 이유를 그대로 보인다) */
  async function run<T>(job: Promise<ApiResult<T>>, done: string) {
    const r = await job
    if (!r.ok) return fail(r.error.message)
    say(done)
    setReload((n) => n + 1)
  }

  if (faqs && (!known || faqs.some((f) => !known.ids.has(f.id)))) {
    setKnown({ ids: new Set(faqs.map((f) => f.id)), fresh: known ? new Set(faqs.filter((f) => !known.ids.has(f.id)).map((f) => f.id)) : new Set() })
  }

  // 있는 분류만 칩으로 보인다 (분류 이름 순서는 카탈로그 순서)
  const cats = Object.keys(CATEGORY_NAME).filter((c) => faqs?.some((f) => f.categoryCode === c))
  const shown = faqs?.filter((f) => !cat || f.categoryCode === cat)

  return (
    <>
      <main className="main">
        <Topbar title="FAQ" sub="본인에게 열람이 허용된 가이드만 표시돼요" lead={<img className="tti" src={titleFaq} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">IT GUIDE</div>
              <h1>먼저 확인해 보세요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                자주 발생하는 IT 문제와 사내 가이드를 모았어요. FAQ를 읽어도 문의가 접수되지는 않아요.
              </p>
            </div>

            {faqs && (faqs.length > 0 || admin) && (
              <div className="subc" role="group" aria-label="분류">
                {faqs && faqs.length > 0 && (
                  <>
                    <button type="button" className={`chip${!cat ? ' on' : ''}`} aria-pressed={!cat} onClick={() => setCat('')}>
                      전체 <em>{faqs.length}</em>
                    </button>
                    {cats.map((c) => (
                      <button key={c} type="button" className={`chip${cat === c ? ' on' : ''}`} aria-pressed={cat === c} onClick={() => setCat(c)}>
                        {/* 분류별 포인트 색 막대 (가이드 관리의 분류 막대와 같은 색) */}
                        <span className={`tag gcbar c-${c} sbxbar`} aria-hidden="true" />
                        {CATEGORY_NAME[c] ?? c} <em>{faqs.filter((f) => f.categoryCode === c).length}</em>
                      </button>
                    ))}
                  </>
                )}
                {admin && (
                  <button type="button" className="btn pri sm faqadd" onClick={() => setAdding(true)}>
                    <Icon name="plus" />
                    FAQ 등록
                  </button>
                )}
              </div>
            )}

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={retry}>
                    다시 시도
                  </button>
                </div>
              </div>
            )}

            {faqs === null && !error && (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            )}
            {faqs?.length === 0 && <div className="empty">표시할 FAQ가 없어요.</div>}

            {shown?.map((f) => {
              const off = f.active === false
              return (
                <details key={f.id} id={`faq-${f.id}`} className={`panel faq${off ? ' foff' : ''}${leaving === f.id ? ' fout' : known?.fresh.has(f.id) ? ' fnew' : ''}`} open={f.id === openId ? true : undefined} style={{ padding: 0 }} onToggle={(e) => e.currentTarget.open && loadSources(f)}>
                  <summary>
                    <span className={`tag c-${f.categoryCode}`}>{CATEGORY_NAME[f.categoryCode] ?? f.categoryCode}</span>
                    <b>{f.question}</b>
                    {off && <span className="tag gray">게시 중단</span>}
                    <span className="chv" aria-hidden="true">
                      <Icon name="chevron" />
                    </span>
                  </summary>
                  <div className="fb">
                    {f.answer}
                    {/* 근거로 쓴 Guide 출처 (SRS ANSWER-01) */}
                    <div className="small muted" style={{ marginTop: 14 }}>
                      <Sources f={f} loaded={srcs[f.id]} onOpen={setPreview} />
                    </div>
                    <div className="row" style={{ marginTop: 12 }}>
                      <button type="button" className="btn sec sm" onClick={() => navigate('/new', { state: { prefill: f.question } })}>
                        해결되지 않았어요 · 상담하기
                      </button>
                      {/* 관리자 단추(게시 중단·삭제)는 오른쪽 끝으로 밀고, 상담하기와 같은 테두리 단추로 맞춘다 */}
                      {admin && (
                        <span className="faqadm">
                          <button type="button" className="btn sec sm" onClick={() => setEditing(f)}>
                            수정
                          </button>
                          <button
                            type="button"
                            className="btn sec sm"
                            onClick={() => {
                              // 서버 모드에서 가이드 출처가 없는 FAQ 는 게시할 수 없다. 수정에서 출처 가이드를 고르게 안내한다
                              const src = srcs[f.id]
                              if (off && !USE_MOCK_FAQ && !f.sources.length && Array.isArray(src) && !src.length) return fail('출처 가이드가 없어서 게시할 수 없어요. 수정에서 출처 가이드를 고른 뒤 게시해 주세요.')
                              void run(setFaqActive(f, off), off ? '다시 게시했어요. 문의자 FAQ 화면에 보여요.' : '게시를 멈췄어요. 문의자에게는 보이지 않아요.')
                            }}
                          >
                            {off ? '다시 게시' : '게시 중단'}
                          </button>
                          <button type="button" className="btn sec sm dng" onClick={() => setDeleting(f)}>
                            삭제
                          </button>
                        </span>
                      )}
                    </div>
                  </div>
                </details>
              )
            })}
          </div>
        </div>
      </main>

      {preview && <SourcePreview source={preview} demo={USE_MOCK_FAQ} onClose={() => setPreview(null)} />}
      {(adding || editing) && (
        <FaqFormDialog
          key={editing?.id ?? 'new'}
          faq={editing}
          loaded={editing ? srcs[editing.id] : undefined}
          onClose={() => {
            setAdding(false)
            setEditing(null)
          }}
          onDone={(msg) => {
            if (editing) setSrcs((m) => Object.fromEntries(Object.entries(m).filter(([k]) => k !== editing.id))) // 출처가 바뀌었으니 다시 읽는다
            setAdding(false)
            setEditing(null)
            say(msg)
            setReload((n) => n + 1)
          }}
        />
      )}
      {deleting && (
        <Modal title="FAQ 삭제" role="alertdialog" onClose={() => setDeleting(null)}>
          <p style={{ margin: 0 }}>
            <b>{deleting.question}</b>
          </p>
          <p className="small muted" style={{ margin: 0 }}>
            삭제하면 되돌릴 수 없어요. 잠시 내리려면 삭제 대신 <b>게시 중단</b>을 쓰세요.
          </p>
          <div className="acts">
            <button type="button" className="btn sec" onClick={() => setDeleting(null)}>
              취소
            </button>
            <button
              type="button"
              className="btn pri"
              onClick={() => {
                const f = deleting
                setDeleting(null)
                setLeaving(f.id)
                // 사라지는 모션이 끝난 뒤에 목록을 다시 불러온다. 실패하면 항목을 되돌린다
                void run(withExitMotion(deleteFaq(f)).then((r) => (r.ok ? r : (setLeaving(null), r))), 'FAQ를 삭제했어요.')
              }}
            >
              삭제
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

/**
 * FAQ 등록·수정 창. 출처 가이드는 전 직원용(사내 일반) 현행 가이드만 고를 수 있다 (서버가 그 문서만 받는다).
 * 수정을 저장하면 FAQ 는 게시가 중단되고, "저장하면서 바로 게시"를 켜면 한 번에 다시 게시한다.
 */
function FaqFormDialog({ faq, loaded, onClose, onDone }: { faq: Faq | null; loaded: GuideSource[] | 'err' | undefined; onClose: () => void; onDone: (message: string) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const edit = !!faq
  const wasOn = !!faq && faq.active !== false
  const [cat, setCat] = useState<CategoryCode>(faq?.categoryCode ?? 'ACC')
  const [q, setQ] = useState(faq?.question ?? '')
  const [a, setA] = useState(faq?.answer ?? '')
  const [guides, setGuides] = useState<Guide[] | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [publish, setPublish] = useState(edit ? wasOn : true)
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const clr = (k: string) => setErrs((e) => ({ ...e, [k]: '' }))

  // 고를 수 있는 가이드를 읽고, 수정이면 연결돼 있던 출처를 미리 고른다 (창을 열 때 한 번만)
  useEffect(() => {
    if (!user) return
    let alive = true
    listGuides(user).then((r) => {
      if (!alive) return
      if (!r.ok) return setErr(r.error.message)
      setGuides(r.data)
      const src = faq ? (faq.sources.length ? faq.sources : Array.isArray(loaded) ? loaded : []) : []
      const ids = src.map((s) => s.documentId ?? r.data.find((g) => g.docCode === s.docCode)?.id).filter((x): x is number => x !== undefined)
      if (ids.length) setPicked(new Set(ids))
    })
    return () => {
      alive = false
    }
  }, [user]) // eslint-disable-line react-hooks/exhaustive-deps

  // 전 직원용 현행 가이드(GUIDE) 가운데 고른 분류의 것만 보이고, 다른 분류에서 이미 고른 가이드는 사라지지 않게 함께 보인다 (위에)
  const eligible = (guides ?? [])
    .filter((g) => g.isActive && g.current?.scope === '사내 일반' && (!g.docType || g.docType === 'GUIDE'))
    .filter((g) => g.cat === cat || picked.has(g.id))
    .sort((x, y) => Number(picked.has(y.id) && y.cat !== cat) - Number(picked.has(x.id) && x.cat !== cat))
  const pubOk = picked.size > 0
  const willPublish = publish && pubOk

  const submit = async () => {
    const e: Record<string, string> = {}
    if (!q.trim()) e.q = '질문 제목을 입력해 주세요.'
    else if (q.trim().length > 500) e.q = '질문은 500자까지 쓸 수 있어요.'
    if (!a.trim()) e.a = '답변을 입력해 주세요.'
    else if (a.trim().length > 4000) e.a = '답변은 4000자까지 쓸 수 있어요.'
    if (!picked.size) e.s = '출처 가이드를 하나 이상 선택해 주세요.'
    else if (picked.size > 20) e.s = '출처 가이드는 20개까지 고를 수 있어요.'
    setErrs(e)
    if (Object.keys(e).length) return
    setBusy(true)
    setErr('')
    const sources = eligible.filter((g) => picked.has(g.id)).map((g) => ({ documentId: g.id, docCode: g.docCode, title: g.title, version: g.current?.version ?? '' }))
    const input = { categoryCode: cat, question: q.trim(), answer: a.trim(), keywords: [], isActive: willPublish, sources }
    const r = faq ? await updateFaq(faq, input) : await createFaq(input)
    setBusy(false)
    if (!r.ok) return setErr(r.error.message)
    if (faq) onDone(willPublish ? 'FAQ를 수정하고 다시 게시했어요.' : 'FAQ를 수정했어요. 게시가 중단된 상태라 문의자에게는 보이지 않아요.')
    else onDone(willPublish ? 'FAQ를 등록했어요. 문의자 FAQ 화면에 바로 보여요.' : 'FAQ를 등록했어요. 게시 전이라 문의자에게는 보이지 않아요.')
  }

  const field = (k: string, label: string, body: React.ReactNode) => (
    <div className="field">
      <label htmlFor={`${uid}-${k}`}>{label}</label>
      {body}
      {errs[k] && (
        <div className="ferr" role="alert">
          {errs[k]}
        </div>
      )}
    </div>
  )

  return (
    <Modal title={edit ? 'FAQ 수정' : 'FAQ 등록'} onClose={onClose}>
      {field(
        'c',
        '분류',
        <SelectBox id={`${uid}-c`} value={cat} options={Object.keys(CATEGORY_NAME).map((c) => ({ value: c, label: CATEGORY_NAME[c], accent: c }))} onChange={(v) => setCat(v as CategoryCode)} />,
      )}
      {field('q', '질문 제목', <input id={`${uid}-q`} className={`inp${errs.q ? ' err' : ''}`} value={q} placeholder="예) 공용 프린터가 보이지 않아요" autoComplete="off" aria-invalid={!!errs.q} onChange={(e) => { setQ(e.target.value); clr('q') }} />)}
      {field('a', '답변', <textarea id={`${uid}-a`} className={`ta${errs.a ? ' err' : ''}`} value={a} placeholder="사내 가이드 기준으로 안내해 주세요" aria-invalid={!!errs.a} onChange={(e) => { setA(e.target.value); clr('a') }} />)}
      <div className="field">
        <label id={`${uid}-s`}>
          출처 가이드 <span className="muted small">(고른 분류의 전 직원용 현행 가이드만 보여요 · 여러 개 선택 가능)</span>
        </label>
        <div className="fsl" role="group" aria-labelledby={`${uid}-s`}>
          {guides === null && !err && (
            <div className="hint" style={{ padding: 10 }}>
              가이드를 불러오는 중이에요…
            </div>
          )}
          {guides !== null && eligible.length === 0 && (
            <div className="hint" style={{ padding: 10 }}>
              이 분류에는 고를 수 있는 가이드가 아직 없어요.
            </div>
          )}
          {eligible.map((g) => (
            <div key={g.id} className="fsrc">
              <label>
                <input
                  type="checkbox"
                  checked={picked.has(g.id)}
                  onChange={(e) => {
                    setPicked((p) => {
                      const n = new Set(p)
                      if (e.target.checked) n.add(g.id)
                      else n.delete(g.id)
                      return n
                    })
                    clr('s')
                  }}
                />
                <span className="fst">
                  <b>
                    {g.docCode} {g.title}
                  </b>
                  <small>
                    {CATEGORY_NAME[g.cat] ?? g.cat} · {g.current?.version}
                    {g.cat !== cat && ' · 다른 분류에서 고른 가이드'}
                  </small>
                </span>
              </label>
            </div>
          ))}
        </div>
        {errs.s && (
          <div className="ferr" role="alert">
            {errs.s}
          </div>
        )}
      </div>
      {edit && (
        <div className="alert warn">
          <Icon name="alert" />
          <div>{wasOn ? '수정을 저장하면 이 FAQ는 자동으로 게시가 중단돼요.' : '지금은 게시 중단 상태예요.'} 아래에서 저장하면서 바로 게시할 수 있어요.</div>
        </div>
      )}
      <label className="fpub">
        <input type="checkbox" checked={willPublish} disabled={!pubOk} onChange={(e) => setPublish(e.target.checked)} />
        <span>
          <b>{edit ? '저장하면서 바로 게시' : '등록하면서 문의자에게 공개'}</b>
          <small>{edit ? '끄면 "게시 중단"으로 저장돼요. 목록에서 "다시 게시"를 누르면 그때 공개돼요.' : '끄면 "게시 안 함"으로만 저장돼요. 문의자 FAQ에는 보이지 않고, 목록에서 "다시 게시"를 누르면 그때 공개돼요.'}</small>
        </span>
      </label>
      <div className="hint">{pubOk ? '선택한 출처로 바로 게시할 수 있어요.' : '게시하려면 출처 가이드를 하나 이상 골라야 해요.'}</div>
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
          {edit ? '수정 저장' : '등록'}
        </button>
      </div>
    </Modal>
  )
}
