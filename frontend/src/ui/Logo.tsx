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
const VIEWBOX = { full: [488, 108], word: [370, 98.5], acc: [370, 98.5] } as const

/** 로고. 가로 폭(px)만 정하면 세로는 비율대로 정해진다. 사이드바·로그인처럼 작은 곳은 word 를 쓴다. */
export function Logo({ width, kind = 'full' }: { width: number; kind?: keyof typeof VIEWBOX }) {
  const [w, h] = VIEWBOX[kind]
  return (
    <svg className="lg" role="img" aria-label="ITssue" width={width} height={+((width * h) / w).toFixed(1)} viewBox={`0 0 ${w} ${h}`}>
      <use href={`#lg-${kind}`} />
    </svg>
  )
}
