/**
 * 등록 설정 확인 창 (공통 UI). 가이드를 올리거나 해결 사례 제안을 승인해 초안으로 등록하기 직전에,
 * 열람 범위와 외부 AI 전송 정책을 한 번 더 눈으로 확인하고 고르게 한다. 버튼 색은 가이드 목록의 표와 같다
 * (열람 범위: 전 직원=하늘·담당자 이상=보라·관리자만=짙은 중립색, 외부 AI 전송: 허용=초록·마스킹 후 허용=노랑·금지=빨강).
 */
import { useState } from 'react'
import { GUIDE_SCOPES, GUIDE_TXS, type GuideScope, type GuideTx } from '../api/guides'
import { Modal } from './Modal'

const SCOPE_CLS: Record<GuideScope, string> = { '전 직원': 'info', '담당자 이상': 'prog', '관리자만': 'adm' }
const TX_CLS: Record<GuideTx, string> = { 허용: 'ok', '마스킹 후 허용': 'warn', 금지: 'urg' }

export function PolicyModal({
  initialScope,
  initialTx,
  intro,
  confirmLabel,
  busy = false,
  onConfirm,
  onClose,
}: {
  initialScope: GuideScope
  initialTx: GuideTx
  /** 창 맨 위 설명 */
  intro: string
  confirmLabel: string
  busy?: boolean
  onConfirm: (scope: GuideScope, tx: GuideTx) => void
  onClose: () => void
}) {
  const [scope, setScope] = useState(initialScope)
  const [tx, setTx] = useState(initialTx)
  return (
    <Modal title="등록 설정을 확인해 주세요" variant="form" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {intro}
      </p>
      <div className="polg">
        <div>
          <div className="asl">열람 범위</div>
          <div className="seg tx" role="group" aria-label="열람 범위">
            {GUIDE_SCOPES.slice()
              .reverse()
              .map((k) => (
                <button key={k} type="button" className={scope === k ? `on ${SCOPE_CLS[k]}` : ''} aria-pressed={scope === k} onClick={() => setScope(k)}>
                  {k}
                </button>
              ))}
          </div>
        </div>
        <div>
          <div className="asl">외부 AI 전송</div>
          <div className="seg tx" role="group" aria-label="외부 AI 전송">
            {GUIDE_TXS.slice()
              .reverse()
              .map((k) => (
                <button key={k} type="button" className={tx === k ? `on ${TX_CLS[k]}` : ''} aria-pressed={tx === k} onClick={() => setTx(k)}>
                  {k}
                </button>
              ))}
          </div>
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        초안으로 등록하고 검색 준비를 시작합니다. 현행 전환 전에는 사용자 답변에 사용되지 않습니다.
      </p>
      <div className="acts">
        <button type="button" className="btn sec" disabled={busy} onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy} onClick={() => onConfirm(scope, tx)}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
