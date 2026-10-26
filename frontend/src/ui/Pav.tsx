/**
 * 잇슈 프로필 이미지 (대화의 답변 아바타, 대화 화면 상단 이미지).
 * 접수 전은 기본, 담당자에게 넘어가 처리 중이면 "처리 중 잇슈", 해결 완료면 "완료 잇슈"로 바뀐다.
 * 이미지는 장식이 아니라 상태를 함께 전하므로 이름(aria-label)을 붙인다.
 */
import done from '../assets/mascot/pose-done.webp'
import base from '../assets/mascot/pose-base.webp'
import handoff from '../assets/mascot/pose-handoff.webp'

export type Pose = 'base' | 'handoff' | 'done'

const IMG: Record<Pose, string> = { base, handoff, done }
const POSE_LABEL: Record<Pose, string> = { base: '잇슈', handoff: '처리 중 잇슈', done: '완료 잇슈' }

export function Pav({ pose = 'base', size = 40 }: { pose?: Pose; size?: number }) {
  return (
    <span className="pav" role="img" aria-label={POSE_LABEL[pose]} style={{ width: size, height: size }}>
      <img src={IMG[pose]} alt="" width={size} height={size} />
    </span>
  )
}
