/**
 * **굵게** 표시만 지원하는 가벼운 텍스트 렌더러 (공통 UI).
 * HTML 을 해석하지 않고 React 요소로만 그리므로, 서버가 준 문구를 그대로 넣어도 스크립트가 실행되지 않는다.
 */
import { Fragment } from 'react'

export function RichText({ text }: { text: string }) {
  // '**굵게**' 를 기준으로 쪼개면 홀수 번째 조각이 굵게 표시할 부분이다
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>{i % 2 ? <b>{p}</b> : p}</Fragment>
      ))}
    </>
  )
}
