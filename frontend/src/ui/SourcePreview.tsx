/**
 * 출처 미리보기 창 (공통 UI). 가이드 제목·위치와 근거 본문(마크다운)을 보여 준다.
 * 제목·넓게/좁게·✕ 는 위에 고정하고 본문만 스크롤한다. 본문의 `[그림] 설명` 줄은 서버가 준 그림(images)과 짝지어 실제 그림으로 보여 준다.
 * 본문이 없으면 그 사실을 알려 준다: 문서만 직접 지정한 FAQ 출처(위치도 없음)는 본문이 없는 게 정상이라고 안내한다.
 */
import type { GuideSource } from '../api/chatTypes'
import { sourceFull } from '../core/format'
import { Markdown } from './Markdown'
import { Modal } from './Modal'

export function SourcePreview({ source, demo, onClose }: { source: GuideSource; demo?: boolean; onClose: () => void }) {
  return (
    <Modal title={sourceFull(source)} sub={`출처 미리보기${demo ? ' (시연)' : ''}`} variant="src" onClose={onClose}>
      {source.section && <h4 className="msrc-sec">{source.section}</h4>}
      {source.excerpt ? (
        <Markdown text={source.excerpt} images={source.images} />
      ) : source.documentId !== undefined && !source.section ? (
        <p className="small muted">문서만 연결한 출처라서 보여 줄 본문이 없어요. 어느 부분인지는 가이드 문서에서 확인해 주세요.</p>
      ) : (
        <p className="small muted">이 화면에서는 가이드 본문을 아직 받아 오지 못해요. 위치만 확인해 주세요.</p>
      )}
    </Modal>
  )
}
