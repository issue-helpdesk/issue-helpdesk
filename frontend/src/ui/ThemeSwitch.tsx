/**
 * 화면 모드 선택: 라이트 · 다크 · 고대비(준비 중, 사용할 수 없음).
 * 로그인 화면 오른쪽 위와 사이드바 아래에 둔다.
 */
import { useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { currentTheme, setThemeAnimated, type ThemeMode } from '../core/theme'
import { Icon } from './Icon'

const MODES: { mode: ThemeMode; label: string; icon: 'sun' | 'moon' }[] = [
  { mode: 'light', label: '라이트 모드', icon: 'sun' },
  { mode: 'dark', label: '다크 모드', icon: 'moon' },
]

/**
 * compact: 평소에는 지금 모드 아이콘 하나만 보이고, 마우스를 올리거나 키보드로 오면 3칸으로 펼쳐진다 (터치는 누르면 펼침).
 * 로그인 화면은 처음부터 3칸이고, 로그인 뒤 우상단(ui/UserControls.tsx)에서는 compact 로 쓴다.
 */
export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const [cur, setCur] = useState<ThemeMode>(currentTheme)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  // 터치로 펼친 3칸은 바깥을 누르거나 Esc 를 누르면 접는다
  useEffect(() => {
    if (!open) return
    const out = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', out)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', out)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const group = (
    <div className="tgm" role="group" aria-label="화면 모드">
      {MODES.map((m) => (
        <button
          key={m.mode}
          type="button"
          aria-pressed={cur === m.mode}
          aria-label={m.label}
          title={m.label}
          onClick={(e) => {
            // 마우스로 골랐으면 3칸을 접는다 (키보드는 초점을 그대로 둔다)
            if (compact) {
              setOpen(false)
              if (e.detail > 0) e.currentTarget.blur()
            }
            if (cur === m.mode) return
            // 화면이 바뀌는 순간에 눌림 표시도 같이 바뀌도록 전환 안에서 상태를 맞춘다
            setThemeAnimated(m.mode, e.currentTarget, () => flushSync(() => setCur(m.mode)))
          }}
        >
          <Icon name={m.icon} />
        </button>
      ))}
      <button type="button" disabled aria-label="고대비 모드 (준비 중)" title="고대비 (준비 중)">
        <Icon name="contrast" />
      </button>
    </div>
  )
  if (!compact) return group
  return (
    <div className={`t1${open ? ' open' : ''}`} ref={box}>
      <button type="button" className="one" aria-label={`화면 모드: ${cur === 'dark' ? '다크' : '라이트'} (눌러서 바꾸기)`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name={cur === 'dark' ? 'moon' : 'sun'} />
      </button>
      {group}
    </div>
  )
}
