/**
 * 비밀번호 규칙 (docs/api/01 1.5, AU-04).
 *
 * 서버가 최종 판단하지만, 화면도 같은 규칙으로 먼저 알려 주고 시연(mock)에서는 이 함수가 서버 역할을 한다.
 * 문구는 API 가 주는 reason 별 message 와 같게 둔다.
 */

/** 새 비밀번호 칸 아래에 항상 보여 주는 규칙 안내 */
export const PASSWORD_RULE = '8~64자, 영문 대·소문자·숫자·특수문자 중 3종류 이상을 섞어 주세요. 현재 비밀번호나 사번과 달라야 해요.'

export interface PasswordViolation {
  field: 'newPassword'
  reason: 'TOO_SHORT' | 'TOO_LONG' | 'INVALID_VALUE' | 'DUPLICATE'
  message: string
}

/** 새 비밀번호가 어긴 규칙을 모두 돌려준다. 어긴 것이 없으면 빈 배열 */
export function checkPassword(newPassword: string, currentPassword: string, employeeNo: string): PasswordViolation[] {
  const v: PasswordViolation[] = []
  const add = (reason: PasswordViolation['reason'], message: string) => v.push({ field: 'newPassword', reason, message })
  if (newPassword.length < 8) add('TOO_SHORT', '8자 이상 입력해 주세요.')
  if (newPassword.length > 64) add('TOO_LONG', '64자 이하로 입력해 주세요.')
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(newPassword)).length
  if (kinds < 3) add('INVALID_VALUE', '영문 대·소문자, 숫자, 특수문자 중 3종류 이상을 섞어 주세요.')
  if (newPassword === currentPassword || newPassword.toLowerCase() === employeeNo.toLowerCase()) {
    add('DUPLICATE', '현재 비밀번호나 사번과 다른 값을 입력해 주세요.')
  }
  return v
}
