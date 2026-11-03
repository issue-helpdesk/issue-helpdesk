/**
 * 입력창: Alt+Enter·Shift+Enter 는 줄바꿈, Enter 는 전송.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from '../src/ui/Composer'

function Host({ onSend }: { onSend: () => void }) {
  const [v, setV] = useState('')
  return <Composer value={v} onChange={setV} onSend={onSend} />
}

describe('입력창 줄바꿈', () => {
  it('Alt+Enter 로 줄을 바꾸고 Enter 로 보낸다', async () => {
    const onSend = vi.fn()
    render(<Host onSend={onSend} />)
    const box = screen.getByLabelText('메시지 입력')
    await userEvent.type(box, '첫 줄{Alt>}{Enter}{/Alt}둘째 줄')
    expect(box).toHaveValue('첫 줄\n둘째 줄')
    expect(onSend).not.toHaveBeenCalled()
    await userEvent.type(box, '{Enter}')
    expect(onSend).toHaveBeenCalledTimes(1)
  })
})
