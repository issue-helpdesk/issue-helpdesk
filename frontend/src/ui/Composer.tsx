/**
 * 문의 입력창 (공통 UI). 새 문의 화면과 이후 대화 화면에서 함께 쓴다.
 *
 * - Enter 로 전송하고 Shift+Enter 는 줄바꿈이다.
 * - 한글 조합 중에는 Enter 로 전송하지 않는다. (디자인 가이드)
 * - 입력 높이는 내용에 따라 늘어나며 최대 140px 까지다.
 */
import { useEffect, useRef, type KeyboardEvent } from 'react'
import { Icon } from './Icon'

interface Props {
  value: string
  onChange: (v: string) => void
  /** 전송 버튼·Enter 를 눌렀을 때 */
  onSend: () => void
  placeholder?: string
  /** 전송 중에는 입력과 버튼을 막는다 (중복 전송 방지) */
  disabled?: boolean
  /** 버튼으로만 고르는 단계: 글을 보낼 수 없고 면을 흐리게 보여 준다 */
  locked?: boolean
  /** 보내려다 막힌 이유: 입력창이 빨갛게 바뀌고 입력창 아래에 빨간 안내가 잠깐 보인다 */
  error?: string
}

export function Composer({ value, onChange, onSend, placeholder = '메시지를 입력해 주세요.', disabled = false, locked = false, error = '' }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // 내용 길이에 맞춰 입력창 높이를 조절한다
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.classList.toggle('grown', el.scrollHeight > 72)
    el.style.height = `${Math.min(140, el.scrollHeight)}px`
  }, [value])

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (value.trim()) onSend()
    }
  }

  return (
    <>
    <div className={`composer${locked ? ' off' : ''}${error ? ' err' : ''}`}>
      <textarea
        ref={ref}
        rows={1}
        value={value}
        placeholder={placeholder}
        aria-label="메시지 입력"
        aria-invalid={!!error}
        disabled={disabled || locked}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <button className="btn ico pri" type="button" aria-label="보내기" disabled={disabled || locked || !value.trim()} onClick={onSend}>
        <Icon name="send" />
      </button>
    </div>
    {error && (
      <div className="errtx cmperr" role="alert">
        {error}
      </div>
    )}
    </>
  )
}
