/**
 * 화면 상단바. 화면 이름(제목)과 보조 설명을 보여 준다.
 * 좁은 화면에서는 왼쪽에 사이드바를 여는 메뉴 버튼이 나타난다.
 */
import type { ReactNode } from 'react'
import { Icon } from './Icon'
import { useShell } from './shellContext'

export function Topbar({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  const { toggleNav } = useShell()
  return (
    <header className="top">
      <div className="row" style={{ flexWrap: 'nowrap', gap: 10 }}>
        <button className="btn sec sm ico menu" type="button" aria-label="메뉴 열기" onClick={toggleNav}>
          <Icon name="chevron" />
        </button>
        <div>
          <h2>{title}</h2>
          {sub && <div className="sub">{sub}</div>}
        </div>
      </div>
      {right && <div className="row" style={{ gap: 8 }}>{right}</div>}
    </header>
  )
}
