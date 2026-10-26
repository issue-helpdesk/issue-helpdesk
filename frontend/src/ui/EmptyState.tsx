/**
 * 막다른 길이 되지 않는 안내 화면 (문의를 찾을 수 없을 때, 불러오지 못했을 때).
 * 잇슈, 제목, 한두 줄 설명, 이동 버튼을 가운데에 둔다. 읽어 주는 안내(role="alert")로도 알린다.
 */
import type { ReactNode } from 'react'
import { Pav } from './Pav'

export function EmptyState({ title, children, actions, note }: { title: string; children: ReactNode; actions: ReactNode; note?: ReactNode }) {
  return (
    <div className="emptyst" role="alert">
      <div>
        <Pav size={96} />
        <h3>{title}</h3>
        <p>{children}</p>
        <div className="acts">{actions}</div>
        {note && <p className="small muted">{note}</p>}
      </div>
    </div>
  )
}
