/**
 * FAQ 화면 (제안 기능, PRD 4.16 · SRS FAQ-01).
 *
 * 열람이 허용된 Guide를 출처로 한 FAQ 목록이다. 열어 봐도 문의가 접수되지 않으며,
 * 해결되지 않으면 "상담하기"로 새 문의 화면에 질문을 채워 넘어간다.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getFaqSources, listFaqs } from '../../api/faq'
import { CATEGORY_NAME } from '../../api/mock/faqs'
import type { GuideSource } from '../../api/chatTypes'
import type { ApiResult, Faq } from '../../api/types'
import { sourceFull } from '../../core/format'
import titleFaq from '../../assets/mascot/title-faq.webp'
import { Icon } from '../../ui/Icon'
import { Topbar } from '../../ui/Topbar'

/** 출처 줄: 서버 FAQ 는 열기 전에는 비어 있어서 읽는 중·읽지 못함·없음을 구분한다 */
function sourceText(f: Faq, loaded: GuideSource[] | 'err' | undefined): string {
  const list = f.sources.length ? f.sources : loaded
  if (list === 'err') return '출처를 불러오지 못했어요.'
  if (list === undefined) return f.serverId === undefined ? `출처: ${f.sources.map(sourceFull).join(', ')}` : '출처를 불러오는 중이에요…'
  return list.length ? `출처: ${list.map(sourceFull).join(', ')}` : '출처 정보가 없어요.'
}

export function FaqView() {
  const navigate = useNavigate()
  const [faqs, setFaqs] = useState<Faq[] | null>(null) // null = 불러오는 중
  const [error, setError] = useState('')
  // 서버 모드에서 FAQ 를 열 때 읽어 온 출처 (키: FAQ 번호). 'err' 는 읽지 못한 경우
  const [srcs, setSrcs] = useState<Record<string, GuideSource[] | 'err'>>({})

  /** 응답을 화면 상태에 반영한다. */
  const apply = (r: ApiResult<Faq[]>) => {
    if (r.ok) setFaqs(r.data)
    else setError(r.error.message)
  }

  // 처음 열 때 FAQ 목록을 불러온다 (화면이 사라진 뒤에는 상태를 바꾸지 않는다)
  useEffect(() => {
    let alive = true
    listFaqs().then((r) => {
      if (!alive) return
      if (r.ok) setFaqs(r.data)
      else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [])

  /** FAQ 를 열 때 출처가 없고 서버 FAQ 면 상세에서 출처를 읽는다 */
  const loadSources = (f: Faq) => {
    if (f.serverId === undefined || f.sources.length || srcs[f.id]) return
    getFaqSources(f.serverId).then((r) => setSrcs((m) => ({ ...m, [f.id]: r.ok ? r.data : 'err' })))
  }

  /** 오류 후 다시 불러오기 */
  async function retry() {
    setError('')
    setFaqs(null)
    apply(await listFaqs())
  }

  return (
    <main className="main">
      <Topbar title="FAQ" sub="본인에게 열람이 허용된 가이드만 표시돼요" lead={<img className="tti" src={titleFaq} alt="" width={56} height={56} />} />
      <div className="scroll">
        <div className="page">
          <div>
            <div className="eyebrow">IT GUIDE</div>
            <h1>먼저 확인해 보세요</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              자주 발생하는 IT 문제와 사내 가이드를 모았어요. FAQ를 읽어도 문의가 접수되지는 않아요.
            </p>
          </div>

          {error && (
            <div className="alert err" role="alert">
              <Icon name="alert" />
              <div>
                {error}{' '}
                <button type="button" className="btn ghost sm" onClick={() => void retry()}>
                  다시 시도
                </button>
              </div>
            </div>
          )}

          {faqs === null && !error && <div className="empty" role="status">불러오는 중이에요…</div>}
          {faqs?.length === 0 && <div className="empty">표시할 FAQ가 없어요.</div>}

          {faqs?.map((f) => (
            <details key={f.id} className="panel faq" style={{ padding: 0 }} onToggle={(e) => e.currentTarget.open && loadSources(f)}>
              <summary>
                <span className={`tag c-${f.categoryCode}`}>{CATEGORY_NAME[f.categoryCode] ?? f.categoryCode}</span>
                <b>{f.question}</b>
                <span className="chv" aria-hidden="true">
                  <Icon name="chevron" />
                </span>
              </summary>
              <div className="fb">
                {f.answer}
                {/* 근거로 쓴 Guide 출처 (SRS ANSWER-01) */}
                <div className="small muted" style={{ marginTop: 6 }}>
                  {sourceText(f, srcs[f.id])}
                </div>
                <div className="row" style={{ marginTop: 12 }}>
                  <button type="button" className="btn sec sm" onClick={() => navigate('/new', { state: { prefill: f.question } })}>
                    해결되지 않았어요 · 상담하기
                  </button>
                </div>
              </div>
            </details>
          ))}
        </div>
      </div>
    </main>
  )
}
