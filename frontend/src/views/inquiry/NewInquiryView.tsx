/**
 * 새 문의 화면 (챗봇 시작 화면).
 *
 * 인사말, 문의 입력창, 자주 묻는 분류 칩, 추천 FAQ 카드를 보여 준다.
 * 칩을 누르면 입력창에 문장이 채워지고, 사용자가 확인한 뒤 보낸다. 추천 FAQ 카드는 그 FAQ 가 열린 FAQ 화면으로 이동한다.
 * 보내면 문의가 만들어지고 대화 화면(/chat/:id)으로 이동한다.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { beginChat, startChat } from '../../api/chat'
import { listFaqs } from '../../api/faq'
import { CATEGORY_NAME } from '../../api/mock/faqs'
import type { Faq } from '../../api/types'
import { USE_MOCK_INQUIRY } from '../../core/config'
import { useAuth } from '../../core/session'
import { Composer } from '../../ui/Composer'
import { Icon, type IconName } from '../../ui/Icon'
import { Mascot } from '../../ui/Mascot'
import { useShell } from '../../ui/shellContext'
import { UserControls } from '../../ui/UserControls'

/** 자주 묻는 분류 칩: [아이콘, 이름, 입력창에 채울 문장] */
const CATEGORY_CHIPS: [IconName, string, string][] = [
  ['shield', '계정·로그인', '계정이 잠겼어요'],
  ['refresh', 'VPN·네트워크', 'VPN이 자꾸 끊겨요'],
  ['file', '소프트웨어 설치', '업무용 프로그램을 설치하고 싶어요'],
  ['help', '프린터·장비', '복합기에서 인쇄가 안 돼요'],
  ['chat', '사내 시스템', '전자결재 접속이 안 돼요'],
]

/** 추천 FAQ: 분류가 겹치지 않게 이 순서로 한 건씩 고른다 (최대 3건) */
const SUGGEST_ORDER = ['ACC', 'NET', 'ACS', 'SW', 'HW', 'SYS', 'SEC']
const pickSuggested = (faqs: Faq[]) =>
  SUGGEST_ORDER.map((c) => faqs.find((f) => f.categoryCode === c))
    .filter((f): f is Faq => !!f)
    .slice(0, 3)

const NOTE = '비밀번호·인증번호·API 키는 입력하지 마세요.'

/** FAQ 화면에서 "상담하기"로 넘어올 때 함께 전달되는 값 */
interface LocationState {
  prefill?: string
}

export function NewInquiryView() {
  const { user } = useAuth()
  const { toggleNav } = useShell()
  const state = useLocation().state as LocationState | null
  const prefill = state?.prefill
  const [text, setText] = useState(prefill ?? '')
  const [notice, setNotice] = useState('')
  const [sending, setSending] = useState(false)
  const navigate = useNavigate()
  // 추천 카드는 실제 FAQ 에서 고른다. 누르면 입력창에 채우지 않고 그 FAQ 가 펼쳐진 FAQ 화면으로 간다
  // null = 불러오는 중. 카드 자리를 미리 잡아 두어, 늦게 도착해도 가운데 정렬된 인사말·입력창이 위로 튀지 않게 한다
  const [suggested, setSuggested] = useState<Faq[] | null>(null)
  useEffect(() => {
    let alive = true
    listFaqs(false).then((r) => alive && setSuggested(r.ok ? pickSuggested(r.data) : []))
    return () => {
      alive = false
    }
  }, [])

  // 같은 화면에서 다른 FAQ 로 다시 들어오면(전달된 문장이 바뀌면) 입력창 내용을 새 문장으로 바꾼다
  const [lastPrefill, setLastPrefill] = useState(prefill)
  if (lastPrefill !== prefill) {
    setLastPrefill(prefill)
    if (prefill) setText(prefill)
  }

  /** 칩·카드를 누르면 입력창에 문장만 채운다 (바로 보내지 않는다) */
  const fill = (t: string) => {
    setText(t)
    setNotice('')
  }

  async function send() {
    if (!text.trim() || sending || !user) return
    setNotice('')
    // 서버는 AI 답변까지 만들어서 응답하므로 오래 걸린다. 입력창에 머물지 않고 대화 화면으로 먼저 넘어간다
    if (!USE_MOCK_INQUIRY) {
      beginChat(user, text.trim())
      navigate('/chat/new', { state: { fresh: true } })
      return
    }
    setSending(true)
    const r = await startChat(user, text.trim())
    setSending(false)
    if (r.ok) {
      navigate(`/chat/${r.data.id}`, { state: { fresh: true } }) // 방금 만든 대화에서는 이어가기 창을 띄우지 않는다
    } else {
      // 실패하면 쓴 내용은 그대로 두고 안내만 한다
      setNotice(r.error.message)
    }
  }

  if (!user) return null

  return (
    <main className="main">
      {/* 이 화면은 상단바가 없어서 화면 모드·사용자 메뉴를 오른쪽 위에 띄운다 */}
      <UserControls floating />
      <div className="scroll">
        {/* 화면 이름은 스크린리더용으로만 두고, 시각적으로는 큰 인사말을 보여 준다 */}
        <h2 className="sr">새 문의</h2>

        {/* 좁은 화면에서 사이드바를 여는 버튼 */}
        <button className="btn sec sm ico xmenu" type="button" aria-label="메뉴 열기" onClick={toggleNav}>
          <Icon name="chevron" />
        </button>

        <div className="hero">
          <Mascot />

          <div className="hi">{user.name}님, 안녕하세요</div>
          <h1>무엇을 도와드릴까요?</h1>

          <div style={{ width: '100%', maxWidth: 720 }}>
            <Composer value={text} onChange={setText} onSend={send} disabled={sending} placeholder="겪고 있는 문제를 적어 주세요." />
          </div>
          {notice && (
            <div className="hint" role="status" style={{ marginTop: 10 }}>
              {notice}
            </div>
          )}

          {/* .fold: 입력이 길어지면 접히는 영역 (layout.css) */}
          <div className="fold">
            <div className="inner">
              <div className="cats">
                {CATEGORY_CHIPS.map(([icon, label, sentence]) => (
                  <button key={label} type="button" className="chip" style={{ minHeight: 44, background: 'var(--white)' }} onClick={() => fill(sentence)}>
                    <Icon name={icon} />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {(suggested === null || suggested.length > 0) && (
            <div className="fold">
              <div className="inner">
                <div className="faqs3" aria-label="자주 묻는 질문" aria-busy={suggested === null}>
                  {suggested === null && [0, 1, 2].map((i) => <span key={i} className="faqc ph" aria-hidden="true" />)}
                  {suggested?.map((f) => (
                    <button key={f.id} type="button" className="faqc" onClick={() => navigate(`/faq?open=${encodeURIComponent(f.id)}`)}>
                      <b>{f.question}</b>
                      <small>{CATEGORY_NAME[f.categoryCode] ?? f.categoryCode} · FAQ에서 보기</small>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="hint" style={{ marginTop: 22 }}>
            AI가 먼저 안내해 드려요. 해결되지 않으면 내용을 확인한 뒤 담당자에게 접수할 수 있어요 · {NOTE}
          </div>
        </div>
      </div>
    </main>
  )
}
