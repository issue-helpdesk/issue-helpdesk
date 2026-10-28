/**
 * 화면 상단바. 화면 이름(제목)과 보조 설명을 보여 준다.
 * 좁은 화면에서는 왼쪽에 사이드바를 여는 메뉴 버튼이 나타난다.
 *
 * 상단바는 본문 위에 겹쳐 놓고 배경을 반투명으로 해서, 스크롤하면 본문이 비쳐 보인다.
 * 본문이 가려지지 않도록 상단바 높이를 부모(.main)의 --topH 로 알려 주면 본문 맨 위에 그만큼 빈 칸이 생긴다.
 */
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { Icon } from './Icon'
import { useShell } from './shellContext'

/** lead: 제목 왼쪽 이미지 (대화 화면의 잇슈, 화면별 제목 이미지) */
export function Topbar({ title, sub, right, lead }: { title: string; sub?: string; right?: ReactNode; lead?: ReactNode }) {
  const { toggleNav } = useShell()
  const ref = useRef<HTMLElement>(null)
  // 화면 제목으로 문서 제목을 갱신한다
  useEffect(() => {
    document.title = `${title} · ITssue`
  }, [title])
  useLayoutEffect(() => {
    const el = ref.current
    const main = el?.parentElement
    if (!el || !main) return
    const set = () => main.style.setProperty('--topH', `${el.offsetHeight}px`)
    set()
    // 크기 관찰을 못 쓰는 환경(오래된 브라우저·테스트)에서는 처음 높이만 쓴다
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(set)
    ro?.observe(el)
    return () => {
      ro?.disconnect()
      main.style.removeProperty('--topH')
    }
  }, [])
  return (
    <header className="top" ref={ref}>
      <div className="row" style={{ flexWrap: 'nowrap', gap: 10 }}>
        <button className="btn sec sm ico menu" type="button" aria-label="메뉴 열기" onClick={toggleNav}>
          <Icon name="chevron" />
        </button>
        {lead}
        <div className="tt">
          <h2>{title}</h2>
          {sub && <div className="sub">{sub}</div>}
        </div>
      </div>
      {right && <div className="row" style={{ gap: 8 }}>{right}</div>}
    </header>
  )
}
