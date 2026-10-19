/**
 * 아직 만들지 않은 화면의 자리표시.
 * 사이드바 틀(AppShell) 안에서 화면 이름만 보여 주며, 화면을 만들면 core/router.tsx 에서 실제 화면으로 교체한다.
 */
import { Topbar } from '../ui/Topbar'

export function HomePlaceholder({ title }: { title: string }) {
  return (
    <main className="main">
      <Topbar title={title} />
      <div className="scroll">
        <div className="page">
          <div className="panel">
            <div className="empty">이 화면은 아직 준비 중이에요.</div>
          </div>
        </div>
      </div>
    </main>
  )
}
