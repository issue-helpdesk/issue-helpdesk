/**
 * 잠깐 뜨는 안내 (공통 UI). 앱 틀(AppShell)에 한 번 두면 어느 화면의 토스트든 여기에 쌓여 보인다 (ui/toastStore.ts).
 * 화면 전체 기준으로 보이도록 body 에 그린다 (상세 패널 같은 움직이는 상자 안에서는 position:fixed 가 그 상자를 기준으로 잡혀 좁고 뚱뚱해진다).
 * 새 토스트는 아래에 붙고 먼저 뜬 것은 위로 밀려 쌓인다.
 */
import { useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { getToasts, watchToasts } from './toastStore'

export function ToastHost() {
  const toasts = useSyncExternalStore(watchToasts, getToasts)
  if (!toasts.length) return null
  return createPortal(
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.out ? ' out' : ''}`} role="status">
          {t.text}
        </div>
      ))}
    </div>,
    document.body,
  )
}
