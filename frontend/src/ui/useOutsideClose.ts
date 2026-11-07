/**
 * 오른쪽 상세 패널을 패널 밖의 빈 곳(본문의 글자·여백)을 눌러도 닫히게 한다.
 * 단추·링크·입력칸·표의 행처럼 눌러서 무언가 하는 요소를 누르면 닫지 않는다(행을 눌러 다른 건으로 바꾸거나, 단추로 일을 하는 데 방해되지 않게).
 * 패널 안, 열려 있는 창(모달)·메뉴 위의 누름도 무시한다. 글자를 끌어서 고르다 패널 밖에서 놓는 경우도 닫지 않는다.
 */
import { useEffect, useRef } from 'react'

const KEEP = [
  'button',
  'a',
  'input',
  'select',
  'textarea',
  'label',
  'summary',
  'tr',
  '[role="button"]',
  '[role="row"]',
  '[role="gridcell"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="complementary"]',
  '[tabindex]:not([tabindex="-1"])',
  '.detail',
  '.ov',
  '.modal',
  '.pop',
  '.toast',
  'aside',
  'nav',
].join(',')

export function useOutsideClose(close: () => void) {
  const ref = useRef(close)
  useEffect(() => {
    ref.current = close
  })
  useEffect(() => {
    let pressedOutside = false
    const outside = (e: MouseEvent) => {
      const t = e.target
      return t instanceof Element && document.contains(t) && !t.closest(KEEP)
    }
    const down = (e: MouseEvent) => {
      pressedOutside = outside(e)
    }
    const click = (e: MouseEvent) => {
      if (pressedOutside && outside(e)) ref.current()
      pressedOutside = false
    }
    // 패널을 연 바로 그 누름에는 반응하지 않도록 한 박자 늦게 건다
    const t = setTimeout(() => {
      document.addEventListener('mousedown', down)
      document.addEventListener('click', click)
    }, 0)
    return () => {
      clearTimeout(t)
      document.removeEventListener('mousedown', down)
      document.removeEventListener('click', click)
    }
  }, [])
}
