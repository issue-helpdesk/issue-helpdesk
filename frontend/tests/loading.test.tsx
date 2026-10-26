/**
 * 로그인 상태 확인 화면: 빨리 끝나면 보이지 않고, 0.3초가 지나도 끝나지 않을 때만 나타난다.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LoadingScreen } from '../src/ui/LoadingScreen'

describe('로그인 상태 확인 화면', () => {
  it('처음에는 아무것도 그리지 않고, 0.3초 뒤에 확인 중이라고 알린다', async () => {
    render(<LoadingScreen />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('로그인 상태를 확인하고 있어요'), { timeout: 1500 })
    expect(screen.getByText('잠시만 기다려 주세요')).toBeInTheDocument()
  })
})
