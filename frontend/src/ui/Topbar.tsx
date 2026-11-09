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
import { UserControls } from './UserControls'

/** status: 제목 아래에 놓는 상태 배지 (보조 글이 있으면 그 옆). 오른쪽 위는 화면 모드·사용자 메뉴(UserControls)가 쓰므로 상태는 오른쪽에 두지 않는다
 * lead: 제목 왼쪽 이미지 (대화 화면의 잇슈, 화면별 제목 이미지). quiet: 실제 제목을 아직 모를 때(불러오는 중) 제목 글을 보이지 않게 두고 높이만 지킨다 */
export function Topbar({ title, sub, right, lead, status, quiet = false }: { title: string; sub?: string; right?: ReactNode; lead?: ReactNode; status?: ReactNode; quiet?: boolean }) {
  const { toggleNav } = useShell()
  const ref = useRef<HTMLElement>(null)
  // 화면 제목으로 문서 제목을 갱신한다
  useEffect(() => {
    if (!quiet) document.title = `${title} · ITssue`
  }, [title, quiet])
  useLayoutEffect(() => {
    const el = ref.current
    const main = el?.parentElement
    if (!el || !main) return
    // 옆에 붙는 상세 패널(.detail)도 같은 높이를 쓰도록 한 칸 위(.app)에도 알린다
    const app = main.parentElement
    const set = () => {
      const h = `${el.offsetHeight}px`
      main.style.setProperty('--topH', h)
      app?.style.setProperty('--topH', h)
    }
    set()
    // 본문이 위로 밀려 올라가 상단바 밑으로 들어갈 때만 아래 선을 보인다(맨 위에서는 배경과 이어져 보이게)
    const onScroll = (e: Event) => {
      const t = e.target as HTMLElement | null
      if (t && t !== el && t.parentElement === main) el.classList.toggle('stuck', t.scrollTop > 0)
    }
    main.addEventListener('scroll', onScroll, true)
    // 크기 관찰을 못 쓰는 환경(오래된 브라우저·테스트)에서는 처음 높이만 쓴다
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(set)
    ro?.observe(el)
    return () => {
      ro?.disconnect()
      main.removeEventListener('scroll', onScroll, true)
      main.style.removeProperty('--topH')
      main.parentElement?.style.removeProperty('--topH')
    }
  }, [])
  return (
    <header className="top" ref={ref}>
      <div className="row" style={{ flexWrap: 'nowrap', gap: 10 }}>
        <button className="btn sec sm ico menu" type="button" aria-label="메뉴 열기" onClick={toggleNav}>
          <Icon name="chevron" />
        </button>
        {lead}
        {/* 제목이 바뀌면(채팅에서 문의를 바꿔 열 때 임시 제목 → 실제 제목) 제목 블록이 다시 나타나는 모션을 쓴다 */}
        <div className={quiet ? 'tt' : 'tt tin'} key={quiet ? '' : title} style={quiet ? { visibility: 'hidden' } : undefined} aria-hidden={quiet || undefined}>
          <h2>{title}</h2>
          {(status || sub) && (
            <div className="sub tst">
              {status}
              {sub && <span>{sub}</span>}
            </div>
          )}
        </div>
      </div>
      {right && <div className="row" style={{ gap: 8 }}>{right}</div>}
      <UserControls />
    </header>
  )
}
