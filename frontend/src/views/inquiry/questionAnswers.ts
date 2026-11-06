/**
 * AI 추가 질문(선택칩·입력)에 대한 답을 모으고 한 번에 보낼 글로 묶는다 (docs/api/02 Question).
 * 질문마다 선택지 하나를 고르거나 직접 입력하며, 표시된 질문은 모두 답해야 보낼 수 있다. 빈칸은 자동으로 채우지 않는다.
 */
import type { ChatQuestion } from '../../api/chatTypes'

/** 한 질문의 답: 선택지를 골랐는지(option) 직접 입력인지(text). 선택과 입력은 따로 기억해 오가도 쓴 글이 사라지지 않는다 */
export interface QAnswer {
  mode: 'option' | 'text'
  option: string
  text: string
}

/** 서버가 상황 질문에 붙이는 이름 */
export const SITUATION_LABEL = '상황'
/** 상황 질문의 직접 입력 버튼 이름은 고정이다 */
export const OTHER_SITUATION = '그 밖의 상황'

/** 선택지가 있고 직접 입력도 받는 질문의 "직접 입력으로 바꾸기" 버튼 이름 */
export const directLabel = (q: ChatQuestion) => (q.label === SITUATION_LABEL ? OTHER_SITUATION : '직접 입력')

/** 입력칸을 보이는지: 선택지가 없으면 항상(옛 질문의 allowText=false 로 막지 않는다), 선택지가 있으면 직접 입력을 골랐을 때 */
export const showsInput = (q: ChatQuestion, a: QAnswer | undefined) => q.options.length === 0 || a?.mode === 'text'

/** 직접 입력 버튼을 보이는지: 선택지가 있고 직접 입력도 받을 때만 */
export const canType = (q: ChatQuestion) => q.options.length > 0 && q.allowText

/** 이 질문의 답 (한 줄로 정리). 아직 안 골랐거나 비어 있으면 빈 글 */
export function valueOf(q: ChatQuestion, a: QAnswer | undefined): string {
  if (!a) return ''
  const v = q.options.length === 0 || a.mode === 'text' ? a.text : a.option
  return v.replace(/\s*\n\s*/g, ' ').trim()
}

export const isAnswered = (q: ChatQuestion, a: QAnswer | undefined) => valueOf(q, a) !== ''
export const allAnswered = (qs: ChatQuestion[], answers: (QAnswer | undefined)[]) => qs.every((q, k) => isAnswered(q, answers[k]))
export const unansweredCount = (qs: ChatQuestion[], answers: (QAnswer | undefined)[]) => qs.filter((q, k) => !isAnswered(q, answers[k])).length

/** 줄 앞에 붙는 이름: 서버 label, 옛 질문처럼 label 이 없으면 질문 글 */
export const labelOf = (q: ChatQuestion) => (q.label && q.label.trim() ? q.label.trim() : q.text)

/**
 * 한 번에 보낼 글: 질문마다 "이름: 답" 줄, 채팅 입력창에 쓴 글이 있으면 마지막에 "추가 내용: 글".
 * 추가 내용이 없으면 그 줄은 없다.
 */
export function buildAnswerText(qs: ChatQuestion[], answers: (QAnswer | undefined)[], extra: string): string {
  const lines = qs.map((q, k) => `${labelOf(q)}: ${valueOf(q, answers[k])}`)
  const more = extra.replace(/\s*\n\s*/g, ' ').trim()
  if (more) lines.push(`추가 내용: ${more}`)
  return lines.join('\n')
}
