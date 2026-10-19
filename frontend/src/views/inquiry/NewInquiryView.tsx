/**
 * 새 문의 화면 (챗봇 시작 화면).
 *
 * 인사말, 문의 입력창, 자주 묻는 분류 칩, 추천 FAQ 카드를 보여 준다.
 * 칩이나 카드를 누르면 입력창에 문장이 채워지고, 사용자가 확인한 뒤 보낸다.
 * 보내면 문의가 만들어지고 대화 화면(/chat/:id)으로 이동한다.
 */
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { startChat } from '../../api/chat'
import { useAuth } from '../../core/session'
import { Composer } from '../../ui/Composer'
import { Icon, type IconName } from '../../ui/Icon'
import { useShell } from '../../ui/shellContext'

/** 자주 묻는 분류 칩: [아이콘, 이름, 입력창에 채울 문장] */
const CATEGORY_CHIPS: [IconName, string, string][] = [
  ['shield', '계정·로그인', '계정이 잠겼어요'],
  ['refresh', 'VPN·네트워크', 'VPN이 자꾸 끊겨요'],
  ['file', '소프트웨어 설치', '업무용 프로그램을 설치하고 싶어요'],
  ['help', '프린터·장비', '복합기에서 인쇄가 안 돼요'],
  ['chat', '메일·협업툴', '전자결재 접속이 안 돼요'],
]

/** 추천 FAQ 카드: [제목, 설명, 입력창에 채울 문장] */
const SUGGESTED: [string, string, string][] = [
  ['비밀번호를 잊었어요', '초기화 방법 안내', '비밀번호를 잊어버렸어요'],
  ['VPN이 자주 끊겨요', '재택 환경 점검', '재택근무 중 VPN이 자주 끊겨요'],
  ['폴더 권한이 필요해요', '신청 절차 안내', '공유 폴더 접근권한을 신청하고 싶어요'],
]

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
    setSending(true)
    setNotice('')
    const r = await startChat(user, text.trim())
    setSending(false)
    if (r.ok) {
      navigate(`/chat/${r.data.id}`)
    } else {
      // 실패하면 쓴 내용은 그대로 두고 안내만 한다
      setNotice(r.error.message)
    }
  }

  if (!user) return null

  return (
    <main className="main">
      <div className="scroll">
        {/* 화면 이름은 스크린리더용으로만 두고, 시각적으로는 큰 인사말을 보여 준다 */}
        <h2 className="sr">새 문의</h2>

        {/* 좁은 화면에서 사이드바를 여는 버튼 */}
        <button className="btn sec sm ico xmenu" type="button" aria-label="메뉴 열기" onClick={toggleNav}>
          <Icon name="chevron" />
        </button>

        <div className="hero">
          {/* 레트로 창 모양 로고 장식 (디자인 가이드: 소개·시작 화면에만 쓴다) */}
          <div className="xhero" aria-hidden="true">
            <div className="xw gh">
              <div className="xb"><i /><i /><i /><span /><b>▢</b><b>✕</b></div>
            </div>
            <div className="xw xm">
              <div className="xb"><i /><i /><i /><span /><b>▢</b><b>✕</b></div>
              <div className="xy">
                <svg width="170" height="66.5" viewBox="0 0 138 54"><use href="#lg-full" /></svg>
              </div>
            </div>
            <i className="xs s1" /><i className="xs s2" /><i className="xs s3" />
            <svg className="xc" width="32" height="48" viewBox="0 0 14 21"><use href="#cursor" /></svg>
          </div>

          <div className="hi">{user.name}님, 안녕하세요</div>
          <h1>무엇을 도와드릴까요?</h1>

          <div style={{ width: '100%', maxWidth: 720 }}>
            <Composer value={text} onChange={setText} onSend={send} disabled={sending} placeholder="겪고 있는 문제를 편하게 적어 주세요" />
          </div>
          {notice && (
            <div className="hint" role="status" style={{ marginTop: 10 }}>
              {notice}
            </div>
          )}

          <div className="cats">
            {CATEGORY_CHIPS.map(([icon, label, sentence]) => (
              <button key={label} type="button" className="chip" style={{ minHeight: 44, background: 'var(--white)' }} onClick={() => fill(sentence)}>
                <Icon name={icon} />
                {label}
              </button>
            ))}
          </div>

          <div className="faqs3">
            {SUGGESTED.map(([title, desc, sentence]) => (
              <button key={title} type="button" className="faqc" onClick={() => fill(sentence)}>
                <b>{title}</b>
                <small>{desc}</small>
              </button>
            ))}
          </div>

          <div className="hint" style={{ marginTop: 22 }}>
            AI가 먼저 답하고, 해결되지 않으면 담당자에게 바로 연결해 드려요 · {NOTE}
          </div>
        </div>
      </div>
    </main>
  )
}
