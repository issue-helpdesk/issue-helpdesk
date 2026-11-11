import type { LegacyCase } from '../../api/chatTypes'
import { Markdown } from '../../ui/Markdown'
import { Modal } from '../../ui/Modal'

/** 서버는 사례 번호·증상 없이 참고 본문만 줄 수 있다. 제공되지 않은 정보를 만들어 채우지 않는다. */
export function LegacyCasePreview({ legacy, onClose }: { legacy: LegacyCase; onClose: () => void }) {
  const symptom = legacy.symptom.trim()
  const content = legacy.solution.trim()
  return (
    <Modal title={`과거 처리 사례${legacy.no ? ` · ${legacy.no}` : ''}`} onClose={onClose}>
      <p className="small muted">도입 이전 처리 이력 · 읽기 전용</p>
      <div className="card w">
        <b>{legacy.title || '과거 처리 사례 참고'}</b>
        {!symptom && !content && <p className="small muted" role="status">이 답변에서 참고한 과거 사례의 상세 내용이 제공되지 않았어요.</p>}
        <dl className="dl" style={{ marginTop: 8 }}>
          {symptom && <><dt>증상</dt><dd>{symptom}</dd></>}
          {content && <><dt>{symptom ? '해결 방법' : '참고 내용'}</dt><dd><Markdown text={content} /></dd></>}
          <dt>활용 원칙</dt>
          <dd>현재 가이드·정책과 충돌하지 않을 때만 참고하고, 충돌하면 가이드를 우선해요.</dd>
        </dl>
      </div>
      <div className="acts"><button type="button" className="btn pri" onClick={onClose}>닫기</button></div>
    </Modal>
  )
}
