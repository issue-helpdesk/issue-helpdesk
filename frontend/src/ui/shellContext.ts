/**
 * 화면 틀(AppShell)이 각 화면에 알려 주는 값.
 * 좁은 화면에서 상단바의 메뉴 버튼이 사이드바를 열 때 쓴다.
 */
import { createContext, useContext } from 'react'

interface ShellState {
  /** 사이드바를 열고 닫는다 (좁은 화면 전용) */
  toggleNav: () => void
}

export const ShellContext = createContext<ShellState>({ toggleNav: () => {} })

export const useShell = () => useContext(ShellContext)
