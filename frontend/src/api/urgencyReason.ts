/**
 * 서버는 긴급도를 세부 유형의 기본값에서 시작해 정할 때 사유를 "세부 유형 NET-04 기본 긴급도"로 저장한다.
 * 규칙의 내부 이름이라 문의자에게는 뜻이 없어서 문의자 화면에서는 숨긴다 (담당자·관리자는 근거로 본다).
 */
export const isRuleUrgencyReason = (reason: string | null | undefined): boolean => !!reason && /^세부 유형 \S+ 기본 긴급도/.test(reason)
