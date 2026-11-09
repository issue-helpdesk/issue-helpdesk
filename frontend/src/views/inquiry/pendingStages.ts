/**
 * 새 문의의 답변을 기다린 시간(초)에 따른 문구.
 * 서버가 알려 주는 진행 단계를 받는 것이 아니라 경과 시간만으로 바꾸므로, 검색·정리 같은 구체적인 단계 이름이나 "평소보다"처럼
 * 기준이 필요한 말은 쓰지 않는다.
 */
const WAIT_STAGES: { from: number; label: string }[] = [
  { from: 0, label: '문의를 처리하고 있어요.' },
  { from: 10, label: '답변을 준비하고 있어요. 잠시만 기다려 주세요.' },
  { from: 25, label: '답변 준비에 시간이 걸리고 있어요.' },
]
/** first: 0초 구간의 문구 (답변을 만드는 중인 대화 화면에서는 "답변을 준비하고 있어요"로 시작한다) */
export const stageLabel = (sec: number, first?: string) => {
  const s = [...WAIT_STAGES].reverse().find((x) => sec >= x.from)!
  return s.from === 0 && first ? first : s.label
}
