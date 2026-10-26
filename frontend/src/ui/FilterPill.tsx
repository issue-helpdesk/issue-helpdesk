/**
 * 조건 고르기 알약 (분류·기간 같은 한 가지를 고른다). 누르면 목록이 열리고, 고르면 알약이 강조되며 ✕로 해제한다.
 * 바깥을 누르거나 Esc 를 누르면 닫히고, 닫으면 알약 버튼으로 초점이 돌아간다. (design/ITssue-Prototype.html pill)
 */
import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'

interface Props {
  label: string
  options: { value: string; label: string }[]
  /** 고른 값. 비었으면 "전체" */
  value: string
  onChange: (v: string) => void
}

export function FilterPill({ label, options, value, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const on = !!value
  const current = options.find((o) => o.value === value)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const pick = (v: string) => {
    onChange(v)
    setOpen(false)
    button.current?.focus()
  }

  return (
    <span className={`d2p ddw${on ? ' act' : ''}`} ref={root}>
      <button type="button" className="ddb" ref={button} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <small>{label}</small>
        <span>{current ? current.label : '전체'}</span>
      </button>
      {on ? (
        <button type="button" className="x" aria-label={`${label} 해제`} onClick={() => pick('')}>
          ✕
        </button>
      ) : (
        <Icon name="down" size={14} />
      )}
      {open && (
        <div className="ddm" role="listbox" aria-label={label}>
          <button type="button" role="option" aria-selected={!on} className={!on ? 'sel' : ''} onClick={() => pick('')}>
            전체
          </button>
          {options.map((o) => (
            <button key={o.value} type="button" role="option" aria-selected={value === o.value} className={value === o.value ? 'sel' : ''} onClick={() => pick(o.value)}>
              {o.label}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}
