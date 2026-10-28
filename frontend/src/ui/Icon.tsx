/**
 * 아이콘 모음 (공통 UI).
 * 20px 격자, 선 두께 1.75 (디자인 가이드). 이모지 아이콘은 쓰지 않는다.
 * 새 아이콘이 필요하면 프로토타입의 ICO 목록에서 path 를 가져와 추가한다.
 */
const PATHS = {
  shield: <path d="M10 3 16 5.5v4.2c0 3.4-2.4 6-6 7.3-3.6-1.3-6-3.9-6-7.3V5.5z" />,
  send: <path d="M17 3 8.5 11.5M17 3l-5.5 14-3-5.5L3 8.5z" />,
  file: <path d="M5 3h6l4 4v10H5zM11 3v4h4M7.5 11h5M7.5 14h5" />,
  alert: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6.2v4.4M10 13.4v.1" />
    </>
  ),
  bell: <path d="M5 14V9a5 5 0 0 1 10 0v5l1.5 2h-13zM8.5 17.5a1.7 1.7 0 0 0 3 0" />,
  logout: (
    <>
      <path d="M8 4H5.5A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8" />
      <path d="M12 6.5 15.5 10 12 13.5M15.5 10H8.5" />
    </>
  ),
  search: (
    <>
      <circle cx="9" cy="9" r="5.5" />
      <path d="M13.2 13.2 17 17" />
    </>
  ),
  down: <path d="M5 8l5 5 5-5" />,
  x: <path d="M5.5 5.5l9 9M14.5 5.5l-9 9" />,
  clock: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4.3l2.8 1.7" />
    </>
  ),
  user: (
    <>
      <circle cx="10" cy="7" r="3" />
      <path d="M4.5 16.5c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5" />
    </>
  ),
  arrow: <path d="M4 10h12M11 5l5 5-5 5" />,
  sun: (
    <>
      <circle cx="10" cy="10" r="3.4" />
      <path d="M10 2.5v1.6M10 15.9v1.6M2.5 10h1.6M15.9 10h1.6M4.7 4.7l1.1 1.1M14.2 14.2l1.1 1.1M15.3 4.7l-1.1 1.1M5.8 14.2l-1.1 1.1" />
    </>
  ),
  moon: <path d="M16.5 11.6A6.8 6.8 0 0 1 8.4 3.5a6.8 6.8 0 1 0 8.1 8.1z" />,
  contrast: (
    <>
      <circle cx="10" cy="10" r="6.8" />
      <path d="M10 3.2v13.6a6.8 6.8 0 0 0 0-13.6z" fill="currentColor" />
    </>
  ),
  plus: <path d="M10 4v12M4 10h12" />,
  chat: <path d="M4 4.5h12v8H9.5L6 16v-3.5H4z" />,
  home: <path d="M3.5 9 10 3.5 16.5 9v7.5h-4.2V12H7.7v4.5H3.5z" />,
  chevron: <path d="m8 5 5 5-5 5" />,
  chart: <path d="M4 16.5h12M6.5 16V10.5M10 16V4.5M13.5 16v-3.5" />,
  check: <path d="m5 10.5 3.2 3.2L15 6.8" />,
  lock: (
    <>
      <rect x="4.5" y="9" width="11" height="7.5" rx="2" />
      <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
    </>
  ),
  refresh: <path d="M16 10a6 6 0 1 1-2-4.5M16 3.5V6h-2.5" />,
  paperclip: <path d="M15.5 9.5 9.8 15.2a3.5 3.5 0 0 1-5-5l6-6a2.3 2.3 0 0 1 3.3 3.3l-6 6a1.2 1.2 0 0 1-1.7-1.7l5.3-5.3" />,
  help: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M7.9 8a2.2 2.2 0 1 1 3.3 1.9c-.8.5-1.2.9-1.2 1.8M10 14.2v.1" />
    </>
  ),
} as const

export type IconName = keyof typeof PATHS

/** 이름으로 아이콘을 그린다. 의미는 글자 라벨이 전하므로 스크린리더에는 숨긴다. */
export function Icon({ name, size, className = '' }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`i ${className}`.trim()}
      viewBox="0 0 20 20"
      aria-hidden="true"
      style={size ? { width: size, height: size } : undefined}
    >
      {PATHS[name]}
    </svg>
  )
}
