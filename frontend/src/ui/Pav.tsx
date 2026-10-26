/**
 * 잇슈 프로필 이미지 (대화의 답변 아바타, 대화 화면 상단 이미지).
 * 접수 전은 기본, 담당자에게 넘어가 처리 중이면 "처리 중 잇슈", 해결 완료면 "완료 잇슈"로 바뀐다.
 * 이미지는 장식이 아니라 상태를 함께 전하므로 이름(aria-label)을 붙인다.
 */
import { POSE_IMG, POSE_LABEL, type Pose } from './poseImages'

export function Pav({ pose = 'base', size = 40 }: { pose?: Pose; size?: number }) {
  return (
    <span className="pav" role="img" aria-label={POSE_LABEL[pose]} style={{ width: size, height: size }}>
      <img src={POSE_IMG[pose]} alt="" width={size} height={size} />
    </span>
  )
}
