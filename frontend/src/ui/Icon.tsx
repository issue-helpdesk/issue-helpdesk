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
  arrow: <path d="M4 10h12M11 5l5 5-5 5" />,
  plus: <path d="M10 4v12M4 10h12" />,
  chat: <path d="M4 4.5h12v8H9.5L6 16v-3.5H4z" />,
  home: <path d="M3.5 9 10 3.5 16.5 9v7.5h-4.2V12H7.7v4.5H3.5z" />,
  chevron: <path d="m8 5 5 5-5 5" />,
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
