/**
 * 안내 창 (공통 UI). 출처 미리보기나 사유 입력처럼 대화를 잠깐 멈추고 확인할 때 쓴다.
 *
 * 바깥을 누르거나 Esc 를 누르면 닫힌다. 꼭 골라야 하는 창(돌아옴 선택)은 dismissible={false} 로 닫히지 않게 한다.
 * 키보드 사용자를 위해 초점을 관리한다: 열면 첫 입력칸(없으면 첫 버튼)으로 옮기고, Tab 은 창 안에서만 돌며,
 * 뒤의 화면은 조작할 수 없게 막고(inert), 닫으면 창을 열었던 버튼으로 돌아간다.
 */
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

interface Props {
  title: string
  onClose?: () => void
  /** false 이면 Esc·바깥 누르기로 닫히지 않고, 버튼으로만 닫는다 */
  dismissible?: boolean
  /** 'choice': 화면 가운데에서 꼭 하나를 고르는 창 (뒤는 어둡고 흐리게). 제목 위에 lead 를 둘 수 있다 */
  variant?: 'choice'
  lead?: ReactNode
  children: ReactNode
}

export function Modal({ title, onClose = () => {}, dismissible = true, variant, lead, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  // 부모가 렌더링될 때마다 새 함수를 넘겨도 초점이 다시 움직이지 않도록 최신 함수만 기억해 둔다
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })

  useEffect(() => {
    const box = ref.current
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const root = document.getElementById('root')
    root?.setAttribute('inert', '')
    ;(box?.querySelector<HTMLElement>('input,textarea,select,button') ?? box)?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (dismissible) closeRef.current()
        return
      }
      if (e.key !== 'Tab' || !box) return
      const items = [...box.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (!items.length) {
        e.preventDefault()
        box.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const inside = box.contains(document.activeElement)
      if (e.shiftKey && (!inside || document.activeElement === first)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (!inside || document.activeElement === last)) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      root?.removeAttribute('inert')
      // 창을 열었던 버튼이 아직 화면에 있으면 그곳으로 돌아간다
      if (opener && document.contains(opener)) opener.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return createPortal(
    <div
      className={`ov${variant === 'choice' ? ' rs' : ''}`}
      onMouseDown={(e) => {
        // 창 바깥(어두운 배경)을 눌렀을 때만 닫는다
        if (dismissible && e.target === e.currentTarget) onClose()
      }}
    >
      <div ref={ref} className={`modal${variant === 'choice' ? ' rdlg' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        {lead}
        <h3>{title}</h3>
        {children}
      </div>
    </div>,
    document.body,
  )
}
