/**
 * 선택 상자 (폼에서 목록 중 하나를 고른다). 브라우저 기본 select 대신 우리 디자인으로 그린다.
 * - 닫힌 모습: 둥근 입력 칸 + 오른쪽 화살표. 열리면 화살표가 위로 바뀌고 칸에 강조 테두리가 생긴다.
 * - 목록: 둥근 판 위에 항목이 나열되고, 고른 항목은 강조색과 ✓ 로 보인다. 창 안에서 잘리지 않게 화면 맨 위 층(portal)에 그린다.
 * - 키보드: ↑↓ 로 옮기고 Enter·Space 로 고르며 Esc 로 닫는다(Esc 는 바깥 창을 닫지 않는다). 초점은 항상 칸에 있다.
 * 접근성은 combobox + listbox 패턴이다. 칸에는 <label htmlFor={id}> 로 이름을 붙인다.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'

export interface SelectOption {
  value: string
  label: string
  /** 분류 코드(ACC·NET …). 있으면 항목 앞에 그 분류의 포인트 색 막대를 그린다 (가이드 관리의 분류 막대와 같은 색) */
  accent?: string
}

interface Props {
  id: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  /** 고른 값이 없을 때 보이는 글 */
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  /** 칸 아래 목록에 보여 줄 빈 목록 안내 */
  empty?: string
  /** 칸 옆에 글자 이름표(label)가 없을 때 스크린리더에 읽어 줄 이름 */
  ariaLabel?: string
  ariaDescribedBy?: string
  /** 폭을 글 길이에 맞출 때 (필터 줄 등). 기본은 칸 전체 폭 */
  auto?: boolean
}

interface Place {
  left: number
  width: number
  top: number
  up: boolean
  max: number
}

export function SelectBox({ id, value, options, onChange, placeholder = '선택해 주세요', disabled, invalid, empty = '고를 수 있는 항목이 없어요', ariaLabel, ariaDescribedBy, auto }: Props) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [place, setPlace] = useState<Place | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const listId = useId()
  const selected = options.findIndex((o) => o.value === value)

  const measure = () => {
    const el = button.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const below = window.innerHeight - r.bottom - 12
    const want = Math.min(Math.max(options.length, 1) * 40 + 12, 280)
    const up = below < want && r.top > below
    setPlace({ left: r.left, width: r.width, top: up ? r.top - 6 : r.bottom + 6, up, max: Math.max(120, Math.min(280, (up ? r.top : below) - 8)) })
  }
  const openMenu = () => {
    if (disabled) return
    measure()
    setActive(selected >= 0 ? selected : options.length ? 0 : -1)
    setOpen(true)
  }
  const close = () => setOpen(false)
  const pick = (i: number) => {
    const o = options[i]
    if (!o) return
    onChange(o.value)
    close()
  }

  // 열려 있는 동안: 바깥을 누르면 닫고, 스크롤·크기 변경에는 목록 위치를 다시 맞춘다
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (button.current?.contains(t) || list.current?.contains(t)) return
      setOpen(false)
    }
    const onMove = () => {
      const el = button.current
      if (!el) return
      const r = el.getBoundingClientRect()
      if (r.bottom < 0 || r.top > window.innerHeight) setOpen(false)
      else measure()
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // 키보드로 옮긴 항목이 목록 안에서 보이게 한다
  useEffect(() => {
    if (!open || active < 0) return
    list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return
    const n = options.length
    if (e.key === 'Escape' && open) {
      e.preventDefault()
      e.stopPropagation()
      e.nativeEvent.stopPropagation() // 바깥 창(모달)이 같이 닫히지 않게 한다
      close()
      return
    }
    if (e.key === 'Tab') return close()
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) return openMenu()
      setActive((a) => (n ? (e.key === 'ArrowDown' ? (a + 1) % n : (a - 1 + n) % n) : -1))
      return
    }
    if (e.key === 'Home' || e.key === 'End') {
      if (!open) return
      e.preventDefault()
      setActive(e.key === 'Home' ? 0 : n - 1)
      return
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (!open) return openMenu()
      pick(active)
    }
  }

  const current = options[selected]
  return (
    <>
      <button
        ref={button}
        id={id}
        type="button"
        role="combobox"
        className={`sbx${open ? ' open' : ''}${invalid ? ' err' : ''}${current ? '' : ' ph'}${auto ? ' auto' : ''}`}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        aria-invalid={invalid || undefined}
        disabled={disabled}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={onKeyDown}
      >
        <span className="sbxv">
          {current?.accent && <span className={`tag gcbar c-${current.accent} sbxbar`} aria-hidden="true" />}
          {current ? current.label : placeholder}
        </span>
        <span className="sbxc" aria-hidden="true">
          <Icon name="chevronDown" />
        </span>
      </button>
      {open &&
        place &&
        createPortal(
          <ul
            ref={list}
            id={listId}
            role="listbox"
            className="sbxl"
            aria-labelledby={id}
            style={{ left: place.left, width: place.width, top: place.top, maxHeight: place.max, transform: place.up ? 'translateY(-100%)' : undefined }}
          >
            {options.length === 0 && <li className="sbxe">{empty}</li>}
            {options.map((o, i) => (
              <li
                key={o.value}
                id={`${listId}-${i}`}
                role="option"
                data-i={i}
                aria-selected={i === selected}
                className={`sbxo${i === selected ? ' sel' : ''}${i === active ? ' act' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(i)}
              >
                <span className="sbxl2">
                  {o.accent && <span className={`tag gcbar c-${o.accent} sbxbar`} aria-hidden="true" />}
                  {o.label}
                </span>
                {i === selected && <Icon name="check" />}
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </>
  )
}
