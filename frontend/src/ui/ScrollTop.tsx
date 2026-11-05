/**
 * "맨 위로" 버튼 (공통 UI). 본문(.main > .scroll)이 길어서 아래로 한참 내려갔을 때만 오른쪽 아래에 나타난다.
 * 위치는 모든 화면이 같다(오른쪽 아래 24px, 전체 문의 화면 기준). 짧은 화면이나 맨 위 근처에서는 보이지 않으므로 화면마다 따로 넣지 않고, 앱 틀(AppShell)에서 한 번만 둔다.
 *
 * 화면마다 본문 상자가 따로 생기고(불러오는 중 → 내용) 사라지므로, 스크롤 이벤트를 문서에서 한꺼번에 듣고
 * 지금 스크롤 중인 본문 상자를 기억한다. 상세 패널·창 안의 스크롤은 대상이 아니다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

/** 이만큼(px) 내려가야 나타난다 */
const SHOW_AFTER = 320
/** 본문이 화면보다 이만큼(px) 이상 길어야 의미가 있다 */
const MIN_EXTRA = 640
/** 사라지는 모션(.totop.out)이 끝나는 시간(ms) */
const OUT_MS = 200

const reduced = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function ScrollTop() {
  const { pathname } = useLocation()
  const target = useRef<HTMLElement | null>(null)
  const [on, setOn] = useState(false)
  const [mounted, setMounted] = useState(false)
  if (on && !mounted) setMounted(true)

  useEffect(() => {
    if (on || !mounted) return
    const t = setTimeout(() => setMounted(false), OUT_MS)
    return () => clearTimeout(t)
  }, [on, mounted])

  // 화면을 옮기면 이전 본문 상자는 잊는다
  useEffect(() => {
    target.current = null
    setOn(false)
  }, [pathname])

  useEffect(() => {
    const onScroll = (e: Event) => {
      const el = e.target
      if (!(el instanceof HTMLElement) || !el.matches('main.main > .scroll')) return
      target.current = el
      setOn(el.scrollTop > SHOW_AFTER && el.scrollHeight - el.clientHeight > MIN_EXTRA)
    }
    document.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => document.removeEventListener('scroll', onScroll, true)
  }, [])

  if (!mounted && !on) return null
  return (
    <button
      type="button"
      className={`totop${on ? '' : ' out'}`}
      aria-label="맨 위로"
      title="맨 위로"
      tabIndex={on ? 0 : -1}
      onClick={() => target.current?.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' })}
    >
      <svg className="i" viewBox="0 0 20 20" aria-hidden="true">
        <path d="M5 3.5h10M10 16.5V7M6 10.5 10 6.5l4 4" />
      </svg>
    </button>
  )
}
