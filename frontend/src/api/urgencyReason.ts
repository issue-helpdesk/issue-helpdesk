/**
 * 서버는 긴급도를 세부 유형의 기본값에서 시작해 정할 때 사유를 "세부 유형 NET-04 기본 긴급도"로 저장한다.
 * 규칙의 내부 이름이라 문의자에게는 뜻이 없어서 문의자 화면에서는 숨긴다 (담당자·관리자는 근거로 본다).
 */
export const isRuleUrgencyReason = (reason: string | null | undefined): boolean => !!reason && /^세부 유형 \S+ 기본 긴급도/.test(reason)

/**
 * 서버·AI 가 쓴 사유 글 속의 긴급도 코드(P1~P4)를 화면에서 쓰는 이름(긴급·높음·보통·낮음)으로 바꿔 보여 준다.
 * 예) "기본 긴급도 P1에서 시작해요" → "기본 긴급도 긴급에서 시작해요". 서버 글은 그대로 두고 화면에서만 바꾼다.
 */
const URGENCY_NAME: Record<string, string> = { '1': '긴급', '2': '높음', '3': '보통', '4': '낮음' }
export const urgencyReasonText = (text: string): string => text.replace(/(?<![A-Za-z0-9])P([1-4])(?![A-Za-z0-9])/g, (_, n: string) => URGENCY_NAME[n])
