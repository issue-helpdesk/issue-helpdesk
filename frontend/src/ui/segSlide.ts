/**
 * 선택 버튼(.seg · .d2seg · .subc)의 슬라이딩 모션 (공통 UI). 앱 시작 때 한 번 켜면 모든 .seg 에 적용되고, 화면 코드는 그대로 둔다.
 *
 * 누르는 순간(화면이 바뀌기 전) 지금 선택된 버튼의 위치·색을 기억해 두었다가, 선택이 바뀐 뒤에
 * 그 자리에서 새 자리로 칠이 두 버튼에 걸쳐 늘어났다 줄어들며 이동하고 색도 서서히 바뀐다.
 * - 회색 판 위에 있는 형태는 칠(조각)이 버튼 뒤로, 판 없이 버튼마다 칠이 있는 알약형은 테두리만 버튼 위로 지나간다.
 * - 움직이는 동안 도착 버튼의 칠은 비워 두고, 끝나면 버튼의 칠을 먼저 되돌린 뒤 다음 프레임에 조각을 치운다 (깜빡임 방지).
 * 모션을 쓸 수 없는 환경(테스트, 모션 줄이기)에서는 아무것도 하지 않는다.
 */

/** 이동에 걸리는 시간(ms). 글자색은 이 값의 60% 로 바뀐다 (components.css 의 --seg-dur) */
const DURATION = 520

/** 선택이 바뀌기를 기다리는 최대 프레임 수. 서버 응답 뒤에 바뀌는 버튼은 기다리지 않고 건너뛴다 */
const WAIT_FRAMES = 12

/** 선택 버튼 묶음: 회색 판형(.seg), 처리 상태 탭(.d2seg), 칩형(.subc) */
const GROUPS = ['.seg', '.d2seg', '.subc']

let enabled = false

interface Look {
  bg: string
  shadow: string
  radius: string
}

const read = (el: HTMLElement): Look => {
  const cs = getComputedStyle(el)
  return { bg: cs.backgroundColor, shadow: cs.boxShadow, radius: cs.borderRadius }
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function slide(seg: HTMLElement, from: DOMRect, fromLook: Look, to: HTMLElement) {
  // 이동 중에 다시 눌렀을 때 이전 조각은 끝 처리 없이 치운다 (끝 처리가 새 이동의 표시(seg-moving)를 지워 버리면 도착 버튼의 칠이 바로 켜져서 움직임이 안 보인다)
  seg.querySelectorAll<HTMLElement>('.seg-ghost').forEach((g) => {
    g.dataset.stale = '1'
    g.remove()
  })
  const sr = seg.getBoundingClientRect()
  const tr = to.getBoundingClientRect()
  if (!tr.width || !from.width) return
  // 도착 버튼의 칠은 색이 바뀌는 중간값을 읽지 않도록 잠깐 전환을 끄고 읽는다
  const prevTr = to.style.transition
  to.style.transition = 'none'
  const look = read(to)
  to.style.transition = prevTr
  const segCs = getComputedStyle(seg)
  const pill = segCs.backgroundColor === 'rgba(0, 0, 0, 0)'
  const bw = parseFloat(segCs.borderLeftWidth) || 0
  const L = (r: DOMRect) => r.left - sr.left - bw
  const T = (r: DOMRect) => r.top - sr.top - bw

  const g = document.createElement('i')
  g.className = `seg-ghost${pill ? ' ring' : ''}`
  g.setAttribute('aria-hidden', 'true')
  g.style.top = `${T(tr)}px`
  g.style.height = `${tr.height}px`
  g.style.borderRadius = look.radius
  seg.append(g)
  seg.classList.add('seg-moving')

  // 가운데쯤에서 출발·도착 두 버튼에 걸쳐 가장 길게 늘어났다가 도착 칸으로 줄어든다 (이웃 칸으로 가도 움직임이 보인다)
  const l0 = L(from)
  const l1 = L(tr)
  const uL = Math.min(l0, l1)
  const uR = Math.max(l0 + from.width, l1 + tr.width)
  const stretch = 10
  const midL = l1 >= l0 ? uL : uL - stretch
  const midW = uR - uL + stretch
  const fromBg = pill ? 'transparent' : fromLook.bg
  const toBg = pill ? 'transparent' : look.bg

  const a = g.animate(
    [
      { left: `${l0}px`, width: `${from.width}px`, backgroundColor: fromBg, boxShadow: fromLook.shadow, offset: 0, easing: 'cubic-bezier(.5,0,.3,1)' },
      { left: `${midL}px`, width: `${midW}px`, offset: 0.42, easing: 'cubic-bezier(.3,1.35,.55,1)' }, // 색은 첫·끝 값 사이를 이어서 서서히 바뀐다
      { left: `${l1}px`, width: `${tr.width}px`, backgroundColor: toBg, boxShadow: look.shadow, offset: 1 },
    ],
    { duration: DURATION, fill: 'both' },
  )
  const done = () => {
    if (g.dataset.stale) return
    seg.classList.remove('seg-moving')
    requestAnimationFrame(() => g.remove())
  }
  a.onfinish = done
  a.oncancel = done
}

/** 앱 시작 때 한 번 부른다. 여러 번 불러도 한 번만 켜진다 */
export function enableSegSlide() {
  if (enabled || typeof document === 'undefined' || typeof Element.prototype.animate !== 'function') return
  enabled = true
  document.documentElement.style.setProperty('--seg-dur', `${DURATION}ms`)

  // 캡처 단계에서 듣는다: 각 화면의 클릭 처리(선택 바꾸기)보다 먼저 지금 상태를 기억해야 한다
  document.addEventListener(
    'click',
    (e) => {
      const btn = (e.target as Element | null)?.closest?.<HTMLButtonElement>(GROUPS.map((g) => `${g} button`).join(','))
      if (!btn || btn.disabled || reduced()) return
      const seg = btn.closest<HTMLElement>(GROUPS.join(','))
      const prev = seg?.querySelector<HTMLElement>('button.on')
      if (!seg || !prev || prev === btn) return
      // 이동 중에 다시 누르면 선택 버튼이 아니라 지금 움직이는 조각의 자리·색에서 이어서 출발한다
      const moving = seg.querySelector<HTMLElement>('.seg-ghost')
      const from = (moving ?? prev).getBoundingClientRect()
      const fromLook = read(moving ?? prev)
      let frames = 0
      const wait = () => {
        const now = seg.isConnected ? seg.querySelector<HTMLElement>('button.on') : null
        if (!now) return
        if (now !== prev) return slide(seg, from, fromLook, now)
        if (++frames < WAIT_FRAMES) requestAnimationFrame(wait)
      }
      requestAnimationFrame(wait)
    },
    true,
  )
}
