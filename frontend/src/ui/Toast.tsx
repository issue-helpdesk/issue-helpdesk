/**
 * 잠깐 뜨는 안내 (공통 UI). text 가 있으면 아래에서 올라오고, 비면 아래로 내려가며 사라진다.
 * 부모는 기존처럼 문구를 state 에 넣었다가 비우기만 하면 된다.
 */
import { useEffect, useState } from 'react'

/** 사라지는 모션(.toast.out)이 끝나는 시간(ms) */
const OUT_MS = 260

export function Toast({ text }: { text: string }) {
  // 비워진 뒤에도 모션이 끝날 때까지는 마지막 문구를 붙들고 있는다
  const [shown, setShown] = useState(text)
  if (text && text !== shown) setShown(text)

  useEffect(() => {
    if (text) return
    const t = setTimeout(() => setShown(''), OUT_MS)
    return () => clearTimeout(t)
  }, [text])

  if (!text && !shown) return null
  return (
    <div className={`toast${text ? '' : ' out'}`} role="status">
      {text || shown}
    </div>
  )
}
