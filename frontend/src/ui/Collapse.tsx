/**
 * 펼침/접힘 영역 (공통 UI). open 이 바뀌면 높이가 부드럽게 열리고 닫힌다.
 * 닫힐 때도 모션이 끝날 때까지는 마지막 내용을 그대로 보여 준다. 부모는 `{open && ...}` 처럼 내용을 지워도 된다.
 * 모션을 쓸 수 없는 환경(테스트, 모션 줄이기)에서는 예전처럼 바로 열고 닫는다.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'

/** 닫히는 모션(.clp.out)이 끝나는 시간(ms) */
const OUT_MS = 320

const canMotion = () => typeof Element.prototype.animate === 'function' && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

interface Props {
  open: boolean
  /** 내용 상자에 붙는 클래스 */
  className?: string
  children: ReactNode
}

export function Collapse({ open, className, children }: Props) {
  const [mounted, setMounted] = useState(open)
  // 처음부터 열려 있던 영역은 모션 없이 그대로 보이고, 나중에 열릴 때만 열리는 모션을 쓴다
  const [appear, setAppear] = useState(false)
  const last = useRef(children) // 닫히는 동안 보여 줄 마지막 내용
  if (open) last.current = children
  if (open && !mounted) {
    setMounted(true)
    setAppear(true)
  }

  useEffect(() => {
    if (open || !mounted) return
    const t = setTimeout(() => setMounted(false), OUT_MS)
    return () => clearTimeout(t)
  }, [open, mounted])

  if (!canMotion()) return open ? <div className={className}>{children}</div> : null
  if (!mounted) return null
  return (
    <div className={`clp${appear ? ' in' : ''}${open ? '' : ' out'}`}>
      <div className="clp-in">
        <div className={className}>{open ? children : last.current}</div>
      </div>
    </div>
  )
}
