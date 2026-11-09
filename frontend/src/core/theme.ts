/**
 * 화면 모드(라이트/다크)와 고대비. 고른 값은 이 브라우저에만 저장한다.
 * 고르기 전에는 기기 설정(prefers-color-scheme · prefers-contrast)을 따른다. (디자인 가이드: 화면 모드 · 고대비 모드)
 *
 * 고대비는 라이트·다크와 나란한 세 번째 바탕이 아니라 그 위에 겹쳐 켜는 별도 설정이다.
 * 켜면 문서에 data-contrast="high" 가 붙고, 지금 보는 라이트 또는 다크 바탕은 그대로 둔 채 색·선만 고대비 값으로 덮인다.
 */
export type ThemeMode = 'light' | 'dark'
/** high: 켬, off: 사용자가 일부러 끔(기기 설정보다 우선) */
export type ContrastMode = 'high' | 'off'

const KEY = 'itssue-theme'
const CONTRAST_KEY = 'itssue-contrast'

function stored(): ThemeMode | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null // 저장소를 못 쓰는 환경에서도 화면은 그대로 동작한다
  }
}

function storedContrast(): ContrastMode | null {
  try {
    const v = localStorage.getItem(CONTRAST_KEY)
    return v === 'high' || v === 'off' ? v : null
  } catch {
    return null
  }
}

/** 지금 보이는 모드: 고른 값이 있으면 그것, 없으면 기기 설정 */
export function currentTheme(): ThemeMode {
  return stored() ?? (window.matchMedia?.('(prefers-color-scheme:dark)').matches ? 'dark' : 'light')
}

/** 지금 고대비 여부: 고른 값(켬·끔)이 있으면 그것, 없으면 기기의 대비 늘리기 설정 */
export function currentContrast(): ContrastMode {
  return storedContrast() ?? (window.matchMedia?.('(prefers-contrast: more)').matches ? 'high' : 'off')
}

function paintContrast(mode: ContrastMode) {
  if (mode === 'high') document.documentElement.setAttribute('data-contrast', 'high')
  else document.documentElement.removeAttribute('data-contrast')
}

/** 저장된(또는 기기 설정에 따른) 모드를 문서에 적용한다. 앱을 그리기 전에 한 번 부른다. */
export function applyStoredTheme() {
  const v = stored()
  if (v) document.documentElement.setAttribute('data-theme', v)
  paintContrast(currentContrast())
}

type ViewTransitionDoc = Document & { startViewTransition?: (update: () => void) => { ready: Promise<void> } }

/**
 * 누른 버튼(from)에서 원이 퍼지며 새 모드로 덮이게 바꾼다 (View Transitions API).
 * 지원하지 않는 브라우저나 모션 줄이기 설정에서는 바로 바꾼다.
 */
function animateFrom(from: HTMLElement, apply: () => void) {
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

/** after 는 화면 상태(React)를 같은 순간에 맞출 때 쓴다. */
export function setThemeAnimated(mode: ThemeMode, from: HTMLElement, after?: () => void) {
  animateFrom(from, () => {
    setTheme(mode)
    after?.()
  })
}

/** 고대비를 켜고 끈다. 라이트·다크 선택은 건드리지 않는다. */
export function setContrastAnimated(mode: ContrastMode, from: HTMLElement, after?: () => void) {
  animateFrom(from, () => {
    setContrast(mode)
    after?.()
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

export function setContrast(mode: ContrastMode) {
  paintContrast(mode)
  try {
    localStorage.setItem(CONTRAST_KEY, mode)
  } catch {
    /* 저장 실패는 무시: 이번 화면에서만 적용된다 */
  }
}
