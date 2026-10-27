/**
 * "비밀번호를 잊으셨나요?" 안내 창 (로그인 화면).
 *
 * 비밀번호는 사용자가 직접 초기화할 수 없다. 서비스데스크에 임시 비밀번호 발급을 요청하면
 * 관리자가 발급하고(US-05), 받은 임시 비밀번호로 로그인하면 새 비밀번호를 정하게 된다. 그래서 입력칸 없이 안내만 한다.
 * 문구는 문서에 없는 안내라 제안이다. (디자인 가이드 문구 사전)
 */
import { SERVICEDESK } from '../../core/config'
import { Icon } from '../../ui/Icon'
import { Modal } from '../../ui/Modal'

export function ForgotModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="비밀번호를 잊으셨나요?" onClose={onClose}>
      <p style={{ margin: 0, lineHeight: '24px' }}>
        보안을 위해 비밀번호는 직접 초기화할 수 없어요. 서비스데스크에 <b>임시 비밀번호 발급</b>을 요청해 주세요.
      </p>
      <div className="alert info">
        <Icon name="shield" />
        <div>
          요청할 때 <b>사번</b>과 <b>이름</b>을 알려 주세요.
          <br />
          받은 임시 비밀번호로 로그인하면 바로 새 비밀번호를 정할 수 있어요. 잠긴 계정이면 잠금도 함께 풀려요.
        </div>
      </div>
      <div className="small muted">서비스데스크 {SERVICEDESK}</div>
      <div className="acts">
        <button type="button" className="btn pri" onClick={onClose}>
          확인
        </button>
      </div>
    </Modal>
  )
}
