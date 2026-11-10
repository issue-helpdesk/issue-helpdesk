import { describe, expect, it } from 'vitest'
import { friendlyAssignReason } from '../src/api/assignReason'
import { toastMs } from '../src/ui/toastStore'

describe('배정 실패 사유 표시', () => {
  it('알려진 코드는 풀어 쓰고 Jira 는 ITSM 으로 쓴다', () => {
    const r = friendlyAssignReason('Jira 배정 실행 실패: assignment_source_unconfirmed')
    expect(r).toContain('ITSM 배정 실행 실패')
    expect(r).toContain('요청 당시 확인한 담당자와 다른 담당자')
    expect(r).not.toMatch(/Jira|assignment_source_unconfirmed/)
  })
  it('재배정이 반영되지 않은 원인을 접수 상태와 무관하게 안내한다 (요청 이후 담당 정보 변경)', () => {
    const r = friendlyAssignReason('Jira 배정 실행 실패: assignment_source_unconfirmed')
    expect(r).toContain('최신 담당자를 확인한 뒤 다시 요청')
    expect(r).not.toContain('담당자를 비운')
    expect(r).not.toContain('처리 중이라')
  })
  it('모르는 코드는 코드를 그대로 두고, 다른 문구의 Jira 만 ITSM 으로 바꾼다', () => {
    expect(friendlyAssignReason('Jira 배정 실행 실패: brand_new_code')).toBe('ITSM 배정 실행 실패: brand_new_code')
    expect(friendlyAssignReason('Jira 응답 시간 초과')).toBe('ITSM 시스템 응답 시간 초과')
    expect(friendlyAssignReason('전문 분야·업무량 기준 자동 배정')).toBe('전문 분야·업무량 기준 자동 배정')
  })
})

describe('토스트 시간', () => {
  it('짧은 문구는 3.5초, 긴 문구는 길이에 따라 늘고 7초를 넘지 않는다', () => {
    expect(toastMs('저장했어요.')).toBe(3500)
    expect(toastMs('가'.repeat(40))).toBeGreaterThan(3500)
    expect(toastMs('가'.repeat(40))).toBeLessThan(7000)
    expect(toastMs('가'.repeat(500))).toBe(7000)
  })
})
