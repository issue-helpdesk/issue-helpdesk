/**
 * 화면 모드 선택: 라이트 · 다크 · 고대비(준비 중, 사용할 수 없음).
 * 로그인 화면 오른쪽 위와 사이드바 아래에 둔다.
 */
import { useState } from 'react'
import { currentTheme, setTheme, type ThemeMode } from '../core/theme'
import { Icon } from './Icon'

const MODES: { mode: ThemeMode; label: string; icon: 'sun' | 'moon' }[] = [
  { mode: 'light', label: '라이트 모드', icon: 'sun' },
  { mode: 'dark', label: '다크 모드', icon: 'moon' },
]

export function ThemeSwitch() {
  const [cur, setCur] = useState<ThemeMode>(currentTheme)
  return (
    <div className="tgm" role="group" aria-label="화면 모드">
      {MODES.map((m) => (
        <button
          key={m.mode}
          type="button"
          aria-pressed={cur === m.mode}
          aria-label={m.label}
          title={m.label}
          onClick={() => {
            setTheme(m.mode)
            setCur(m.mode)
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
}
