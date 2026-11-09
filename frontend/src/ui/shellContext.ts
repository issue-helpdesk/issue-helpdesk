/**
 * 화면 틀(AppShell)이 각 화면에 알려 주는 값.
 * 좁은 화면에서 상단바의 메뉴 버튼이 사이드바를 열 때, 사이드바의 프로필이 "내 프로필" 창을 열 때 쓴다.
 */
import { createContext, useContext } from 'react'

interface ShellState {
  /** 사이드바를 열고 닫는다 (좁은 화면 전용) */
  toggleNav: () => void
  /** "내 프로필" 창(정보 + 비밀번호 변경)을 연다 */
  openProfile: () => void
  /** 사이드바를 접었는지 (860px 초과에서만 적용) */
  sideOff: boolean
  /** 사이드바를 접거나 펼친다 */
  toggleSide: () => void
}

export const ShellContext = createContext<ShellState>({ toggleNav: () => {}, openProfile: () => {}, sideOff: false, toggleSide: () => {} })

export const useShell = () => useContext(ShellContext)
