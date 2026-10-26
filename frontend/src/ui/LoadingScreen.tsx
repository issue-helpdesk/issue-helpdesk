/**
 * 로그인 상태 확인 화면. 새로고침 직후 저장된 로그인 정보를 서버에서 확인하는 동안 화면 전체에 보여 준다.
 *
 * 확인이 빨리 끝나면 깜빡이지 않도록 0.3초가 지나도 끝나지 않을 때만 나타난다.
 * 잇슈가 가볍게 둥실거리고 점 세 개가 물결친다(움직임 줄이기에서는 모두 멈춘다). 읽어 주는 안내(role="status")로도 알린다.
 */
import { useEffect, useState } from 'react'
import { POSE_IMG } from './poseImages'

const DELAY_MS = 300

export function LoadingScreen() {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShow(true), DELAY_MS)
    return () => clearTimeout(t)
  }, [])
  if (!show) return null
  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="ld">
        <div className="m">
          <img src={POSE_IMG.base} alt="" />
        </div>
        <div>
          <p>
            로그인 상태를 확인하고 있어요{' '}
            <span className="dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          </p>
          <small>잠시만 기다려 주세요</small>
        </div>
      </div>
    </div>
  )
}
