/**
 * 출처 미리보기 창 (공통 UI). 가이드 제목·위치와 근거 본문(마크다운)을 보여 준다.
 * 본문이 없으면(서버가 아직 본문을 주지 않는 화면) 그 사실을 알려 준다.
 */
import type { GuideSource } from '../api/chatTypes'
import { sourceFull } from '../core/format'
import { Markdown } from './Markdown'
import { Modal } from './Modal'

export function SourcePreview({ source, demo, onClose }: { source: GuideSource; demo?: boolean; onClose: () => void }) {
  return (
    <Modal title={sourceFull(source)} onClose={onClose}>
      <p className="small muted">출처 미리보기{demo ? ' (시연)' : ''}</p>
      <div className="card w">
        {source.section && <b>{source.section}</b>}
        {source.excerpt ? <Markdown text={source.excerpt} /> : <p className="small muted" style={{ marginTop: 6 }}>이 화면에서는 가이드 본문을 아직 받아 오지 못해요. 위치만 확인해 주세요.</p>}
      </div>
      <div className="acts">
        <button type="button" className="btn pri" onClick={onClose}>
          닫기
        </button>
      </div>
    </Modal>
  )
}
