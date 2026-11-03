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

type ViewTransitionDoc = Document & { startViewTransition?: (update: () => void) => { ready: Promise<void> } }

/**
 * 누른 버튼(from)에서 원이 퍼지며 새 모드로 덮이게 바꾼다 (View Transitions API).
 * 지원하지 않는 브라우저나 모션 줄이기 설정에서는 바로 바꾼다. after 는 화면 상태(React)를 같은 순간에 맞출 때 쓴다.
 */
export function setThemeAnimated(mode: ThemeMode, from: HTMLElement, after?: () => void) {
  const apply = () => {
    setTheme(mode)
    after?.()
  }
  const doc = document as ViewTransitionDoc
  if (!doc.startViewTransition || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return apply()
  const r = from.getBoundingClientRect()
  const x = r.left + r.width / 2
  const y = r.top + r.height / 2
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
  doc
    .startViewTransition(apply)
    .ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 650, easing: 'cubic-bezier(.4,0,.2,1)', pseudoElement: '::view-transition-new(root)' },
      )
    })
    .catch(() => {
      /* 전환이 취소돼도 모드는 이미 바뀐다 */
    })
}

export function setTheme(mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', mode)
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* 저장 실패는 무시: 이번 화면에서만 적용된다 */
  }
}
