/**
 * 마크다운 글 입력칸 (공통 UI). 위의 "편집 / 미리보기" 선택으로 쓴 글이 실제 가이드에서 어떻게 보일지 바로 볼 수 있다.
 * 읽기 전용이면 편집칸 대신 글을 그대로 보여 주고, 미리보기는 계속 쓸 수 있다.
 */
import { useState } from 'react'
import { Markdown } from './Markdown'

export function MarkdownField({
  id,
  value,
  onChange,
  readOnly = false,
  tall = false,
  label,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  readOnly?: boolean
  tall?: boolean
  /** 편집칸의 접근성 이름 */
  label: string
}) {
  const [preview, setPreview] = useState(false)
  return (
    <div className="mdf">
      <div className="seg sm" role="group" aria-label="편집·미리보기 선택">
        <button type="button" className={!preview ? 'on' : ''} aria-pressed={!preview} onClick={() => setPreview(false)}>
          편집
        </button>
        <button type="button" className={preview ? 'on' : ''} aria-pressed={preview} onClick={() => setPreview(true)}>
          미리보기
        </button>
      </div>
      {preview ? (
        <div className={`mdp${tall ? ' tall' : ''}`} aria-label={`${label} 미리보기`} role="region">
          {value.trim() ? <Markdown text={value} /> : <p className="small muted">미리 볼 내용이 없어요.</p>}
        </div>
      ) : (
        <textarea id={id} aria-label={label} className={`ta cgta${tall ? ' tall' : ''}`} value={value} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  )
}
