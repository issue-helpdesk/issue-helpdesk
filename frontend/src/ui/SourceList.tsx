/**
 * 출처 Guide 목록 (공통 UI). 같은 가이드(문서 번호·제목·버전)는 제목을 한 번만 쓰고, 그 아래에 절·쪽을 버튼으로 나열한다.
 * 위치(절·쪽)를 누르면 그 부분을 미리 볼 수 있다. PDF·PPTX 가이드는 위치에 쪽 번호(p.5)가 함께 온다.
 */
import type { GuideSource } from '../api/chatTypes'
import { Icon } from './Icon'
import { groupSources } from './sourceGroups'

export function SourceList({ sources, onOpen }: { sources: GuideSource[]; onOpen: (s: GuideSource) => void }) {
  return (
    <div className="srcl">
      <span className="srcl-k">출처</span>
      {groupSources(sources).map((g) => (
        <span key={g.key} className="srcg">
          <span className="srcg-t">{g.head}</span>
          {g.items.map((s, i) => (
            <button key={`${s.section}-${i}`} type="button" className="srcb" title="이 부분 미리보기" onClick={() => onOpen(s)}>
              <Icon name="file" size={14} />
              {s.section || '본문'}
            </button>
          ))}
        </span>
      ))}
    </div>
  )
}
