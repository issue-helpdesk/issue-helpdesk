/**
 * 사이드바 접기/펼치기 버튼. 사이드바가 보일 때는 로고 옆(접기), 접힌 뒤에는 위쪽 왼쪽(펼치기)에 나타난다.
 * 860px 이하에서는 기존 메뉴 버튼을 쓰므로 css 가 숨긴다.
 */
import { useShell } from './shellContext'

export function SideToggle({ open }: { open?: boolean }) {
  const { toggleSide } = useShell()
  const label = open ? '사이드바 펼치기' : '사이드바 접기'
  return (
    <button type="button" className={`sbt${open ? ' sbopen' : ''}`} aria-label={label} title={label} aria-expanded={!open} onClick={toggleSide}>
      <svg className="i" viewBox="0 0 20 20" aria-hidden="true">
        <rect x="3" y="4" width="14" height="12" rx="2.5" />
        <path d="M8 4v12" />
      </svg>
    </button>
  )
}
