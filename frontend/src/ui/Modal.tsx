/**
 * 안내 창 (공통 UI). 출처 미리보기나 사유 입력처럼 대화를 잠깐 멈추고 확인할 때 쓴다.
 * 바깥을 누르거나 Esc 를 누르면 닫힌다. 열리면 창으로 포커스를 옮긴다.
 */
import { useEffect, useRef, type ReactNode } from 'react'

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="ov"
      onMouseDown={(e) => {
        // 창 바깥(어두운 배경)을 눌렀을 때만 닫는다
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  )
}
