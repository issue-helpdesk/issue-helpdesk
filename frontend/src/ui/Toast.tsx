/**
 * 잠깐 뜨는 안내 (공통 UI). text 가 있으면 아래에서 올라오고, 비면 아래로 내려가며 사라진다.
 * 부모는 기존처럼 문구를 state 에 넣었다가 비우기만 하면 된다.
 * 화면 전체 기준으로 보이도록 body 에 그린다 (상세 패널 같은 움직이는 상자 안에서는 position:fixed 가 그 상자를 기준으로 잡혀 좁고 뚱뚱해진다).
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

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
  return createPortal(
    <div className={`toast${text ? '' : ' out'}`} role="status">
      {text || shown}
    </div>,
    document.body,
  )
}
