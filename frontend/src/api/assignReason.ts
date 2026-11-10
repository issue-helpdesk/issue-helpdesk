/**
 * 담당자 배정 처리 이력의 실패 사유를 읽기 쉽게 바꾼다.
 * 서버(실행기)는 실패 때 "Jira 배정 실행 실패: <코드>" 한 줄을 남기는데, 코드(assignment_source_unconfirmed 등)는 운영자가 읽기 어렵고
 * 화면 표기는 ITSM 으로 통일했다. 모르는 코드는 코드를 그대로 두고 앞 문구만 ITSM 으로 바꾼다.
 */
import { cleanServerText } from './errorText'

const WHY: Record<string, string> = {
  assignment_source_unconfirmed: '재배정 요청 당시 확인한 담당자와 다른 담당자가 ITSM 시스템에 지정되어 있어 반영하지 않았어요. 최신 담당자를 확인한 뒤 다시 요청해 주세요.',
  stale_assignment: '더 최근의 배정이 있어서 이 배정은 반영하지 않았어요.',
  stale_classification: '더 최근의 분류 변경이 있어 이전 요청은 반영하지 않았어요.',
  'superseded:reclassify': '분류 변경으로 이전 배정 요청을 대체했어요.',
  reservation_mismatch: '배정 요청 이후 접수의 담당 정보가 바뀌어서 반영하지 않았어요.',
  assignment_not_allowed: '지금 접수 상태에서는 배정할 수 없어요.',
  jira_status_not_assignable: 'ITSM 티켓이 종결됐거나 알 수 없는 상태라 배정할 수 없어요.',
  result_unknown: 'ITSM에 반영됐는지 확인하지 못했어요. 운영자가 ITSM에서 확인해 주세요.',
  unknown_assignee: 'ITSM 담당자 계정을 확인할 수 없어요.',
  incomplete_jira_assignment: 'ITSM 티켓의 상태·담당자 조회가 불완전해요.',
  invalid_job: '배정 요청 내용이 올바르지 않아요.',
  auth: 'ITSM 인증에 실패했어요. 연동 계정을 확인해 주세요.',
  not_found: 'ITSM에서 티켓이나 담당자를 찾지 못했어요.',
  rate_limited: 'ITSM 요청이 너무 많아 잠시 막혔어요. 잠시 뒤 다시 시도해 주세요.',
  invalid_fields: 'ITSM이 담당자 값을 받아들이지 않았어요.',
}

export function friendlyAssignReason(reason: string): string {
  if (WHY[reason]) return WHY[reason]
  const m = /^Jira 배정 실행 실패:\s*(\S+)\s*$/.exec(reason)
  if (!m) return cleanServerText(reason)
  const why = WHY[m[1]]
  return why ? `ITSM 배정 실행 실패 · ${why}` : `ITSM 배정 실행 실패: ${m[1]}`
}
