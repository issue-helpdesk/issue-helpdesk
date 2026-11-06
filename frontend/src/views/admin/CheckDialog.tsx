/**
 * ITSM 확인·재시도 창 (관리자). 운영 현황의 카드와 접수 상세 패널(어느 화면에서 열든)이 같이 쓴다.
 * 연동(생성)이나 상태 변경을 ITSM에서 확인하지 못한 접수를, 사유를 적고 다시 확인·재처리한다 (api/ops.ts, TK-11·12).
 */
import { useState } from 'react'
import type { TicketSummary } from '../../api/ticketTypes'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'
import { UrgencyChip } from '../staff/QueueView'

/** 확인이 필요한 이유 한 줄 */
export const linkWhy = (t: TicketSummary) => (t.transitionStatus === 'NEEDS_ADMIN' ? 'ITSM 동기화 확인 필요' : t.jiraSyncStatus === 'NEEDS_ADMIN' ? 'ITSM 생성 요청 응답 시간 초과 · 생성 여부 확인 필요' : 'ITSM 생성 결과 확인 중')

const WORK_LABEL = { RDY: '처리 대기', WIP: '처리 중', FIN: '해결 확인 대기', CLS: '해결 완료' } as const

export function CheckDialog({ t, busy, err, onClose, onDetail, onGo }: { t: TicketSummary; busy: boolean; err: string; onClose: () => void; onDetail?: () => void; onGo: (kind: 'link' | 'trn', reason: string) => void }) {
  const trn = t.transitionStatus === 'NEEDS_ADMIN'
  const [why, setWhy] = useState('')
  const [whyErr, setWhyErr] = useState('')
  const to = t.requestedWorkStatus ? WORK_LABEL[t.requestedWorkStatus] : '요청한 상태'
  const now = t.workStatus ? WORK_LABEL[t.workStatus] : '이전 상태'
  const verifying = t.jiraSyncStatus === 'VERIFYING'
  const submit = () => {
    const w = why.trim()
    if (!w) return setWhyErr('재처리 사유를 입력해 주세요.')
    onGo(trn ? 'trn' : 'link', w)
  }
  return (
    <Modal title={trn ? 'ITSM 상태 확인' : 'ITSM 생성 확인'} onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        접수 <span className="mono">{t.receiptNo}</span> · {t.jiraKey ? <>ITSM <b className="mono">{t.jiraKey}</b></> : 'ITSM 티켓 없음'} · {t.group?.name ?? '-'} · <UrgencyChip u={t.urgency} />
      </p>
      <div className="mdl-issue">
        <div className="stlist" aria-label="확인이 필요한 내용">
          <div className={`sx live ${trn || !verifying ? 'tn-urg' : 'tn-warn'}`}>
            <span className="mk">
              <Icon name="alert" />
            </span>
            <span className="l">{trn ? '상태 변경' : 'ITSM 연동'}</span>
            <span className="vb">
              <span className={`sbd ${trn || !verifying ? 'tn-urg' : 'tn-warn'}`}>
                <i />
                {trn ? 'ITSM 동기화 필요' : verifying ? '생성 여부 확인 중' : 'ITSM 생성 확인 필요'}
              </span>
            </span>
            <span className="sxs">{trn ? `${now} → ${to} 변경이 ITSM에 반영됐는지 확인하지 못함` : linkWhy(t)}</span>
          </div>
        </div>
      </div>
      <p className="mdl-how">
        {trn ? (
          <>
            ITSM에서 현재 상태를 먼저 읽어 와요. 이미 <b>{to}</b>이면 다시 요청하지 않고 완료로 처리하고, 아직 <b>{now}</b>이면 <b>{to}</b>로 바꾸는 요청을 다시 보내요.
          </>
        ) : (
          <>
            ITSM에서 접수번호 <b className="mono">{t.receiptNo}</b>로 만든 티켓이 있는지 먼저 찾아요. 있으면 그 티켓을 연결하고, 없을 때만 새로 만들어요. (중복 생성 방지)
          </>
        )}
      </p>
      <div className="field">
        <label htmlFor="ops-why">
          재처리 사유 <span className="muted">(필수)</span>
        </label>
        <textarea id="ops-why" className={`ta${whyErr ? ' err' : ''}`} maxLength={500} value={why} placeholder="예) ITSM 장애 복구 후 재처리" aria-invalid={!!whyErr} aria-describedby={whyErr ? 'ops-why-e' : undefined} onChange={(e) => { setWhy(e.target.value); setWhyErr('') }} />
        {whyErr && (
          <div className="ferr" id="ops-why-e" role="alert">
            {whyErr}
          </div>
        )}
        <div className="wcnt">
          <span className="hint">처리 이력과 감사 기록에 남아요.</span>
          <span className="hint">
            <b>{why.length}</b>/500
          </span>
        </div>
      </div>
      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          닫기
        </button>
        {onDetail && (
          <button type="button" className="btn sec" onClick={onDetail}>
            상세
          </button>
        )}
        <button type="button" className="btn pri" disabled={busy} onClick={submit}>
          {trn ? 'ITSM 상태 확인·다시 반영' : 'ITSM 생성 확인·재시도'}
        </button>
      </div>
    </Modal>
  )
}
