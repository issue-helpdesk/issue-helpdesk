/**
 * 문의에 "새 답변" 점을 켤지 정하는 보조 기록 (서버 모드).
 * 서버 알림(NT)은 담당자 배정·처리 완료뿐이라 AI 가 새로 답한 것은 알려 주지 않는다. 그래서 문의 목록(IQ-02)이 주는
 * 마지막 AI 답변 ID(lastAiMessageId)가, 내가 마지막으로 확인한 값과 다르면 새 답변으로 본다 (docs/api/06 R-45).
 * ID 는 같은지만 본다(크기 비교는 뜻이 없다). 사용자 글·상태 변경·AI 처리 실패로는 값이 바뀌지 않아서 점이 켜지지 않는다.
 * 이 브라우저에만 기록하므로 다른 기기에는 따로 쌓인다.
 */
const KEY = (employeeNo: string) => `itssue.inquiryAiSeen.${employeeNo}`

/** 아직 아무 답변도 확인하지 않은 문의의 기록 값 (AI 답변이 하나라도 있으면 점이 켜진다) */
const NONE = 0

function read(employeeNo: string): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(KEY(employeeNo)) ?? '{}') as Record<string, number>
  } catch {
    return {}
  }
}
function write(employeeNo: string, rec: Record<string, number>) {
  try {
    localStorage.setItem(KEY(employeeNo), JSON.stringify(rec))
  } catch {
    /* 저장할 수 없는 환경(사생활 보호 창 등)이면 점만 못 켠다 */
  }
}

/** 이 문의의 AI 답변을 이 ID 까지 확인했다고 기록한다 (대화 화면을 열거나 새 내용이 그려질 때). 답변이 없으면(null) 기록하지 않는다 */
export function markInquirySeen(employeeNo: string, id: number, lastAiMessageId: number | null | undefined) {
  if (lastAiMessageId == null) return
  const rec = read(employeeNo)
  if (rec[id] === lastAiMessageId) return
  rec[id] = lastAiMessageId
  write(employeeNo, rec)
}

/**
 * 이 브라우저에서 보낸 문의의 답이, 그 문의 화면을 떠나 있는 동안 도착했을 때: 아직 아무것도 확인하지 않았다고 기록한다.
 * (그래야 처음 보는 문의를 "본 것"으로 치는 규칙에 걸리지 않고 새 답변 점이 켜진다)
 */
export function markInquiryUnseen(employeeNo: string, id: number) {
  const rec = read(employeeNo)
  if (rec[id] !== undefined) return
  rec[id] = NONE
  write(employeeNo, rec)
}

/**
 * 마지막으로 확인한 뒤에 새 AI 답변이 저장됐는지. 이 브라우저에서 처음 보는 문의는 "본 것"으로 기록만 하고 점을 켜지 않는다
 * (처음 쓰는 브라우저에서 모든 문의에 점이 켜지지 않게). AI 답변이 없는 문의(null)에는 점이 없다.
 */
export function hasUnseenUpdate(employeeNo: string, id: number, lastAiMessageId: number | null | undefined): boolean {
  if (lastAiMessageId == null) return false
  const rec = read(employeeNo)
  if (rec[id] === undefined) {
    rec[id] = lastAiMessageId
    write(employeeNo, rec)
    return false
  }
  return rec[id] !== lastAiMessageId
}
