/**
 * 로고와 AI 아바타 (공통 UI).
 * 로고 도형은 디자인 가이드의 벡터를 그대로 쓰며, 늘리기·기울이기·색 변경을 하지 않는다.
 */
import { LOGO_DEFS } from './logoDefs'

/** 로고 심볼 정의. 앱 루트(App.tsx)에 한 번만 둔다. 정적 문자열이라 사용자 입력이 섞이지 않는다. */
export function LogoDefs() {
  return <div aria-hidden="true" style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }} dangerouslySetInnerHTML={{ __html: LOGO_DEFS }} />
}

/** 로고 종류별 가로·세로 비율. full=설명줄 포함, word=워드마크만, acc=포인트 포함 */
const VIEWBOX = { full: [138, 54], word: [138, 40], acc: [150, 40] } as const

/** 로고. 가로 폭(px)만 정하면 세로는 비율대로 정해진다. 가로 160px 미만에서는 word 를 권장한다. */
export function Logo({ width, kind = 'full' }: { width: number; kind?: keyof typeof VIEWBOX }) {
  const [w, h] = VIEWBOX[kind]
  return (
    <svg className="lg" role="img" aria-label="ITssue" width={width} height={+((width * h) / w).toFixed(1)} viewBox={`0 0 ${w} ${h}`}>
      <use href={`#lg-${kind}`} />
    </svg>
  )
}

/** AI 답변 아바타. 32px 이하는 단색, 그보다 크면 은은한 그라데이션 (디자인 가이드) */
export function Avatar({ size = 32 }: { size?: number }) {
  return (
    <span
      className={`av${size <= 32 ? ' flat' : ''}`}
      style={{ width: size, height: size, borderRadius: Math.max(6, Math.round(size / 4)) }}
    >
      <svg width={Math.round(size * 0.62)} height={Math.round(size * 0.54)} viewBox="0 0 46 40" aria-hidden="true">
        <use href="#lg-it" />
      </svg>
    </span>
  )
}
