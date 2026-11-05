/**
 * 가이드 적재 실패 알림 창 (관리자). 업로드·다시 시도한 가이드의 검색 준비(적재)가 실패하면, 관리자가 어느 화면에 있어도
 * 이 창이 한 번 뜬다. 토스트는 지나가 버려서 놓치기 쉬워 창으로 알린다. 창을 닫아도 사이드바와 가이드 목록의 점은 해결될 때까지 남는다.
 * (api/guideWatch.ts 가 추적한 결과를 보여 준다)
 */
import { useEffect, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { breakSentences, getIngestFailures, isFailureListOpen, markFailuresSeen, setFailureListOpen, startIngestPolling, watchFailureList, watchIngest } from '../api/guideWatch'
import { useAuth } from '../core/session'
import { Icon } from './Icon'
import { Modal } from './Modal'
import { Pav } from './Pav'

export function GuideIngestAlert() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const failures = useSyncExternalStore(watchIngest, getIngestFailures)
  // 가이드 관리의 "실패 목록 보기"로 연 창: 이미 본 실패도 모두 보여 준다
  const listOpen = useSyncExternalStore(watchFailureList, isFailureListOpen)
  // 추적 중인 버전의 결과를 몇 초마다 확인한다 (관리자만)
  useEffect(() => (user ? startIngestPolling(user) : undefined), [user])

  if (user?.serviceRole !== 'ADMIN') return null
  const fresh = listOpen ? failures : failures.filter((f) => !f.seen)
  if (!fresh.length) return null
  const first = fresh[0]
  const close = () => {
    setFailureListOpen(false)
    markFailuresSeen()
  }
  return (
    <Modal title="가이드 적재에 실패했어요" variant="choice" role="alertdialog" dismissible={false} closeButton onClose={close} lead={<Pav size={84} />}>
      <p>
        검색 준비(적재)가 실패한 가이드가 {fresh.length}개 있어요.
        <br />이 가이드는 현행으로 바꿀 수 없어요.
      </p>
      <ul className="gia">
        {fresh.map((f) => (
          <li key={f.versionId}>
            <b>
              {f.docCode} {f.title} · {f.version}
            </b>
            <span>
              <Icon name="alert" />
              <em>{breakSentences(f.error || '실패 사유를 받지 못했어요')}</em>
            </span>
          </li>
        ))}
      </ul>
      <div className="acts">
        <button type="button" className="btn sec" onClick={close}>
          {listOpen ? '닫기' : '나중에 볼게요'}
        </button>
        <button
          type="button"
          className="btn pri"
          onClick={() => {
            close()
            navigate(`/guides?doc=${encodeURIComponent(first.docCode)}`)
          }}
        >
          가이드 관리에서 보기
        </button>
      </div>
    </Modal>
  )
}
