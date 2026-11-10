/** 로그인 성공 후 신규 보안 알림을 한 번 안내한다. 상태 변경 요청은 보내지 않는다. */
import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { countSecurityAlerts } from '../api/security'
import { getIngestFailures, watchIngest } from '../api/guideWatch'
import { useAuth } from '../core/session'
import { Modal } from './Modal'
import { Pav } from './Pav'

export function SecurityLoginNotice({ blocked = false }: { blocked?: boolean }) {
  const { user, loginSequence } = useAuth()
  const navigate = useNavigate()
  const [notice, setNotice] = useState<{ sequence: number; count: number } | null>(null)
  const [dismissed, setDismissed] = useState(0)
  const failures = useSyncExternalStore(watchIngest, getIngestFailures)
  const userId = user?.id
  const admin = user?.serviceRole === 'ADMIN'
  const forced = !!user?.passwordChangeRequired

  useEffect(() => {
    if (!user || !admin || forced || !loginSequence) return
    let alive = true
    countSecurityAlerts(user).then((counts) => {
      if (alive && counts?.신규) setNotice({ sequence: loginSequence, count: counts.신규 })
    })
    return () => { alive = false }
    // 세션 갱신으로 user 객체가 바뀌어도 같은 로그인에서 다시 조회하지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, admin, forced, loginSequence])

  if (!admin || forced || blocked || failures.some((f) => !f.seen) || !notice || notice.sequence !== loginSequence || dismissed === loginSequence) return null
  const close = () => setDismissed(loginSequence)
  return (
    <Modal title="새 보안·감사 알림이 있어요" variant="choice" lead={<div className="security-notice-lead"><Pav size={84} /><span className="security-notice-label">보안·감사 알림</span></div>} onClose={close} closeButton>
      <p>아직 확인을 시작하지 않은 신규 알림이 <b className="security-notice-count">{notice.count}건</b> 있어요.</p>
      <p className="small muted">검토가 필요한 신호이며, 보안 사고나 위반이 확정된 것은 아니에요.</p>
      <div className="acts">
        <button type="button" className="btn sec" onClick={close}>나중에 볼게요</button>
        <button type="button" className="btn pri" onClick={() => { close(); navigate('/security?status=NEW') }}>신규 알림 확인</button>
      </div>
    </Modal>
  )
}
