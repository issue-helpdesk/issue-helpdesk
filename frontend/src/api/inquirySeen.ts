/**
 * 문의에 "새 답변" 점을 켤지 정하는 보조 기록 (서버 모드).
 * 서버 알림(NT)은 담당자 배정·처리 완료뿐이라 AI 가 새로 답한 것은 알려 주지 않는다. 그래서 문의의 마지막 변경 시각(updatedAt)이
 * 내가 마지막으로 본 시각보다 늦으면 새 답변으로 본다. 이 브라우저에만 기록하므로 다른 기기에는 따로 쌓인다.
 * 서버가 AI 응답 알림을 주면(docs/api/06 R-45) 이 파일은 필요 없다.
 */
const KEY = (employeeNo: string) => `itssue.inquirySeen.${employeeNo}`

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

/** 이 문의를 이 시각까지 봤다고 기록한다 (대화 화면을 열거나 새 내용이 그려질 때) */
export function markInquirySeen(employeeNo: string, id: number, updatedAt: string) {
  const at = Date.parse(updatedAt)
  if (Number.isNaN(at)) return
  const rec = read(employeeNo)
  if ((rec[id] ?? 0) >= at) return
  rec[id] = at
  write(employeeNo, rec)
}

/**
 * 마지막으로 본 뒤에 문의가 바뀌었는지. 이 브라우저에서 처음 보는 문의는 "본 것"으로 기록만 하고 점을 켜지 않는다
 * (처음 쓰는 브라우저에서 모든 문의에 점이 켜지지 않게).
 */
export function hasUnseenUpdate(employeeNo: string, id: number, updatedAt: string): boolean {
  const at = Date.parse(updatedAt)
  if (Number.isNaN(at)) return false
  const rec = read(employeeNo)
  if (rec[id] === undefined) {
    rec[id] = at
    write(employeeNo, rec)
    return false
  }
  return at > rec[id] + 1000
}
