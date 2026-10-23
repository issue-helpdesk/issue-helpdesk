/**
 * 화면 모드(라이트/다크). 고른 값은 이 브라우저에만 저장한다.
 * 고르기 전에는 기기 설정(prefers-color-scheme)을 따른다. (디자인 가이드: 화면 모드)
 */
export type ThemeMode = 'light' | 'dark'

const KEY = 'itssue-theme'

function stored(): ThemeMode | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null // 저장소를 못 쓰는 환경에서도 화면은 그대로 동작한다
  }
}

/** 지금 보이는 모드: 고른 값이 있으면 그것, 없으면 기기 설정 */
export function currentTheme(): ThemeMode {
  return stored() ?? (window.matchMedia?.('(prefers-color-scheme:dark)').matches ? 'dark' : 'light')
}

/** 저장된 모드를 문서에 적용한다. 앱을 그리기 전에 한 번 부른다. */
export function applyStoredTheme() {
  const v = stored()
  if (v) document.documentElement.setAttribute('data-theme', v)
}

export function setTheme(mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', mode)
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* 저장 실패는 무시: 이번 화면에서만 적용된다 */
  }
}
