/**
 * 비밀번호 초기화 창 (로그인 화면).
 *
 * 사번을 받고 휴대폰 인증으로 직접 초기화하는 흐름의 첫 단계다. 시연에서는 실제 문자를 보내지 않는다.
 * 등록된 사번인지는 알려 주지 않고 "등록된 사번이면 보내 드려요"라고만 안내한다. (계정 존재 여부를 노출하지 않는다)
 * 입력 오류는 토스트가 아니라 입력칸 바로 아래에 남기고 입력과 연결한다.
 */
import { useState, type FormEvent } from 'react'
import { SERVICEDESK } from '../../core/config'
import { Modal } from '../../ui/Modal'

export function ForgotModal({ onClose }: { onClose: () => void }) {
  const [employeeNo, setEmployeeNo] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!employeeNo.trim()) {
      setError('사번을 입력해 주세요.')
      return
    }
    setSent(true)
  }

  if (sent) {
    return (
      <Modal key="sent" title="인증 문자를 보냈어요" onClose={onClose}>
        <p style={{ lineHeight: '24px' }}>
          등록된 사번이면 휴대폰으로 인증 문자를 보내 드려요. 인증을 마치면 새 비밀번호를 설정할 수 있고, 잠긴 계정이면 잠금도 함께 풀려요.
        </p>
        <p className="hint">시연: 이 화면은 실제 문자를 보내지 않아요.</p>
        <div className="acts">
          <button type="button" className="btn pri" onClick={onClose}>
            확인
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal key="ask" title="비밀번호 초기화" onClose={onClose}>
      <form onSubmit={onSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <p className="small muted">사번과 휴대폰 인증으로 직접 초기화해요. 새 비밀번호는 인증 뒤에 설정해요.</p>
        <div className="field">
          <label htmlFor="m-fid">사번</label>
          <input
            className="inp"
            id="m-fid"
            autoComplete="username"
            placeholder="예) EMP-1001"
            value={employeeNo}
            onChange={(e) => {
              setEmployeeNo(e.target.value)
              if (error) setError('')
            }}
            aria-invalid={!!error}
            aria-describedby={error ? 'm-fid-err' : undefined}
          />
          {error && (
            <div className="ferr" id="m-fid-err" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="acts">
          <button type="button" className="btn sec" onClick={onClose}>
            취소
          </button>
          <button type="submit" className="btn pri">
            휴대폰으로 인증하기
          </button>
        </div>
        <p className="hint">휴대폰이 바뀌었거나 인증이 안 되면 서비스데스크 {SERVICEDESK}로 연락해 주세요.</p>
      </form>
    </Modal>
  )
}
