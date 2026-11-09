/**
 * 가이드 열람 범위 배지 (공통 UI). 세 범위를 색으로도 구분한다: 전 직원=하늘, 담당자 이상=보라, 관리자만=짙은 중립색.
 * 같은 표에 나오는 상태 색(현행·준비 완료=초록, 마스킹 후 전송=노랑, 외부 전송 금지=빨강)과 겹치지 않게 골랐다. 의미는 글자가 전한다.
 */
import type { GuideScope } from '../api/guides'
import { StateBadge } from './StateBadge'

const TONE: Record<GuideScope, string> = { '전 직원': 'info', '담당자 이상': 'prog', '관리자만': 'adm' }

export function ScopeBadge({ scope }: { scope: GuideScope }) {
  return <StateBadge tone={TONE[scope]} label={scope} />
}
