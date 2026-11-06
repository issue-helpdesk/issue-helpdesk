/**
 * AI 추가 질문 (선택칩·입력). AI 본문 아래에 질문과 선택지를 순서대로 보여 주고, 질문마다 하나를 고르게 한다.
 * - 누르는 즉시 보내지 않는다. 표시된 질문을 모두 답해야 "답변 보내기"가 켜지고, 채팅 입력창의 글은 "추가 내용"으로 함께 간다.
 * - 선택지가 없으면 입력칸, 선택지가 있고 직접 입력도 받으면 "직접 입력" 버튼(상황 질문은 "그 밖의 상황")으로 입력칸을 연다.
 * - open=false 인 지난 질문은 읽기 전용이다.
 */
import { useId } from 'react'
import type { ChatQuestion } from '../../api/chatTypes'
import { allAnswered, canType, directLabel, labelOf, showsInput, unansweredCount, type QAnswer } from './questionAnswers'

interface Props {
  questions: ChatQuestion[]
  open: boolean
  answers: (QAnswer | undefined)[]
  /** 요청 중이거나 이어가기 창이 떠 있을 때 */
  disabled: boolean
  /** 전송하려다 막혔을 때의 안내 (모든 질문에 답해야 한다) */
  error: string
  onChange: (index: number, answer: QAnswer) => void
  onSubmit: () => void
}

const blank: QAnswer = { mode: 'option', option: '', text: '' }

export function QuestionForm({ questions, open, answers, disabled, error, onChange, onSubmit }: Props) {
  const uid = useId()
  const lock = !open || disabled
  const left = unansweredCount(questions, answers)
  return (
    <div className={`qf${open ? '' : ' past'}`} role="group" aria-label={open ? '추가 질문' : '지난 추가 질문'}>
      {questions.map((q, k) => {
        const a = answers[k]
        const input = open && showsInput(q, a)
        return (
          <fieldset key={k} className="qf-q" disabled={lock}>
            <legend id={`${uid}-${k}`}>{q.text}</legend>
            {q.options.length > 0 && (
              <div className="qf-opts" role="radiogroup" aria-labelledby={`${uid}-${k}`}>
                {q.options.map((o) => {
                  const on = open && a?.mode !== 'text' && a?.option === o
                  return (
                    <button key={o} type="button" role="radio" aria-checked={on} className={`chip${on ? ' on' : ''}`} onClick={() => onChange(k, { ...(a ?? blank), mode: 'option', option: o })}>
                      {o}
                    </button>
                  )
                })}
                {open && canType(q) && (
                  <button type="button" role="radio" aria-checked={a?.mode === 'text'} className={`chip${a?.mode === 'text' ? ' on' : ''}`} onClick={() => onChange(k, { ...(a ?? blank), mode: 'text' })}>
                    {directLabel(q)}
                  </button>
                )}
              </div>
            )}
            {input && (
              <input
                className="inp qf-in"
                value={a?.text ?? ''}
                maxLength={300}
                placeholder={q.options.length ? `${directLabel(q)}을(를) 적어 주세요` : '내용을 적어 주세요'}
                aria-label={`${labelOf(q)} 직접 입력`}
                onChange={(e) => onChange(k, { ...(a ?? blank), mode: 'text', text: e.target.value })}
              />
            )}
          </fieldset>
        )
      })}
      {open && (
        <div className="qf-foot">
          <span className="small muted" id={`${uid}-hint`}>
            {left > 0 ? `${left}개 질문에 더 답하면 보낼 수 있어요.` : '아래 입력창에 쓴 글은 "추가 내용"으로 함께 가요.'}
          </span>
          <button type="button" className="btn pri sm" disabled={lock || !allAnswered(questions, answers)} aria-describedby={`${uid}-hint`} onClick={onSubmit}>
            답변 보내기
          </button>
        </div>
      )}
      {open && error && (
        <div className="errtx" role="alert">
          {error}
        </div>
      )}
    </div>
  )
}
