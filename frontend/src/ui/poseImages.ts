/** 잇슈 모습별 이미지와 이름 (프로필 이미지·접수 진행 카드가 함께 쓴다) */
import base from '../assets/mascot/pose-base.webp'
import done from '../assets/mascot/pose-done.webp'
import handoff from '../assets/mascot/pose-handoff.webp'

export type Pose = 'base' | 'handoff' | 'done'

export const POSE_IMG: Record<Pose, string> = { base, handoff, done }
export const POSE_LABEL: Record<Pose, string> = { base: '잇슈', handoff: '처리 중 잇슈', done: '완료 잇슈' }
