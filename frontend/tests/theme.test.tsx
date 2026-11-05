/**
 * 화면 모드: 라이트·다크 + 그 위에 겹치는 고대비.
 * 고대비는 사용자가 고른 값(켬·끔) > 기기 설정(prefers-contrast) > 꺼짐 순서로 정하고, 라이트·다크 선택과는 서로 영향을 주지 않는다.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyStoredTheme, currentContrast, setContrast, setTheme } from '../src/core/theme'
import { ThemeSwitch } from '../src/ui/ThemeSwitch'

const root = document.documentElement

/** jsdom 에는 matchMedia 가 없어서, 기기 설정(대비 늘리기·다크)을 흉내 낸다 */
function device({ more = false, dark = false }: { more?: boolean; dark?: boolean } = {}) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (q: string) => ({
      matches: q.includes('prefers-contrast') ? more : q.includes('prefers-color-scheme') ? dark : false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    }),
  })
}

beforeEach(() => {
  localStorage.clear()
  root.removeAttribute('data-theme')
  root.removeAttribute('data-contrast')
  device()
})
afterEach(() => vi.restoreAllMocks())

describe('고대비 적용', () => {
  it('저장된 값도 기기 설정도 없으면 켜지지 않는다', () => {
    applyStoredTheme()
    expect(root).not.toHaveAttribute('data-contrast')
    expect(currentContrast()).toBe('off')
  })

  it('저장된 값이 없고 기기가 대비 늘리기를 켜 두었으면 고대비로 시작한다', () => {
    device({ more: true })
    applyStoredTheme()
    expect(root).toHaveAttribute('data-contrast', 'high')
  })

  it('사용자가 끈 값은 기기 설정보다 우선한다', () => {
    device({ more: true })
    setContrast('off')
    applyStoredTheme()
    expect(root).not.toHaveAttribute('data-contrast')
    expect(currentContrast()).toBe('off')
  })

  it('사용자가 켠 값은 기기 설정이 꺼져 있어도 적용된다', () => {
    localStorage.setItem('itssue-contrast', 'high')
    applyStoredTheme()
    expect(root).toHaveAttribute('data-contrast', 'high')
  })

  it('알 수 없는 저장 값은 무시한다', () => {
    localStorage.setItem('itssue-contrast', 'maybe')
    applyStoredTheme()
    expect(root).not.toHaveAttribute('data-contrast')
  })

  it('켜고 끄면 속성과 저장 값이 함께 바뀐다', () => {
    setContrast('high')
    expect(root).toHaveAttribute('data-contrast', 'high')
    expect(localStorage.getItem('itssue-contrast')).toBe('high')
    setContrast('off')
    expect(root).not.toHaveAttribute('data-contrast')
    expect(localStorage.getItem('itssue-contrast')).toBe('off')
  })
})

describe('라이트·다크와 독립', () => {
  it('둘 중 무엇을 골라도 고대비는 그대로이고, 반대도 같다', () => {
    setContrast('high')
    setTheme('dark')
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(root).toHaveAttribute('data-contrast', 'high')
    setTheme('light')
    expect(root).toHaveAttribute('data-theme', 'light')
    expect(root).toHaveAttribute('data-contrast', 'high')
    setContrast('off')
    expect(root).toHaveAttribute('data-theme', 'light')
  })

  it('저장소를 쓸 수 없어도 오류 없이 이번 화면에서만 적용된다', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(() => setContrast('high')).not.toThrow()
    expect(root).toHaveAttribute('data-contrast', 'high')
    expect(() => applyStoredTheme()).not.toThrow()
  })
})

describe('화면 모드 버튼', () => {
  it('고대비 칸은 켜짐·꺼짐 토글이고 라이트·다크 칸은 그대로 둔다', async () => {
    const user = userEvent.setup()
    setTheme('dark')
    render(<ThemeSwitch />)
    const light = screen.getByRole('button', { name: '라이트 모드' })
    const dark = screen.getByRole('button', { name: '다크 모드' })
    const hc = screen.getByRole('button', { name: '고대비 모드' })
    expect(hc).toBeEnabled()
    expect(hc).toHaveAttribute('aria-pressed', 'false')

    await user.click(hc)
    expect(hc).toHaveAttribute('aria-pressed', 'true')
    expect(dark).toHaveAttribute('aria-pressed', 'true') // 다크와 함께 눌린다
    expect(light).toHaveAttribute('aria-pressed', 'false')
    expect(root).toHaveAttribute('data-contrast', 'high')
    expect(root).toHaveAttribute('data-theme', 'dark')

    await user.click(light) // 라이트를 눌러도 고대비는 유지
    expect(light).toHaveAttribute('aria-pressed', 'true')
    expect(dark).toHaveAttribute('aria-pressed', 'false')
    expect(hc).toHaveAttribute('aria-pressed', 'true')

    await user.click(hc)
    expect(hc).toHaveAttribute('aria-pressed', 'false')
    expect(root).not.toHaveAttribute('data-contrast')
    expect(light).toHaveAttribute('aria-pressed', 'true')
  })

  it('작게 접힌 버튼의 이름에 고대비 여부가 들어간다', () => {
    setContrast('high')
    render(<ThemeSwitch compact />)
    expect(screen.getByRole('button', { name: /화면 모드: .* · 고대비/ })).toBeInTheDocument()
  })

  it('기기가 대비 늘리기를 켜 두었으면 처음부터 눌려 있다', () => {
    device({ more: true })
    render(<ThemeSwitch />)
    expect(screen.getByRole('button', { name: '고대비 모드' })).toHaveAttribute('aria-pressed', 'true')
  })
})
