/** 새 문의의 답변을 기다린 시간(초)에 따른 문구. 마지막은 오래 걸릴 때의 안내 */
const WAIT_STAGES: { from: number; label: string }[] = [
  { from: 0, label: '질문을 읽고 있어요' },
  { from: 4, label: '관련 가이드를 찾고 있어요' },
  { from: 10, label: '답변을 정리하고 있어요' },
  { from: 25, label: '평소보다 오래 걸리고 있어요. 조금만 더 기다려 주세요' },
]
export const stageLabel = (sec: number) => [...WAIT_STAGES].reverse().find((s) => sec >= s.from)!.label
