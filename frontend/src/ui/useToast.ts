import { showToast } from './toastStore'

/**
 * 토스트를 띄우는 함수. 화면 어디서든 `const { say } = useToast()` 로 쓴다. 토스트는 앱 틀(AppShell)의 ToastHost 가 한곳에 쌓아 그린다.
 * (보이는 시간·쌓이는 규칙은 toastStore.ts)
 */
export function useToast() {
  return { say: showToast }
}
