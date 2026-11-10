import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LegacyCasePreview } from '../src/views/inquiry/LegacyCasePreview'

describe('과거 처리 사례 안내', () => {
  it('서버 참고 본문을 표시하고 시연 문구·빈 증상 항목을 만들지 않는다', () => {
    render(<LegacyCasePreview legacy={{ no: 'LEG-0042', title: '과거 처리 사례 참고', symptom: '', solution: '### 처리 내용\n인쇄 대기열을 비운 뒤 정상 출력됐어요.' }} onClose={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: '과거 처리 사례 · LEG-0042' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '처리 내용' })).toBeInTheDocument()
    expect(screen.getByText('참고 내용')).toBeInTheDocument()
    expect(screen.queryByText('증상')).not.toBeInTheDocument()
    expect(screen.queryByText(/시연용 가상 데이터/)).not.toBeInTheDocument()
  })

  it('번호·본문이 없으면 불필요한 구분점이나 빈 항목 대신 안내한다', () => {
    render(<LegacyCasePreview legacy={{ no: '', title: '', symptom: '', solution: '' }} onClose={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: '과거 처리 사례' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('상세 내용이 제공되지 않았어요')
    expect(screen.queryByText('해결 방법')).not.toBeInTheDocument()
  })

  it('증상·해결 방법이 제공된 사례는 구분해 표시한다', () => {
    render(<LegacyCasePreview legacy={{ no: 'LEG-1', title: '인쇄 오류', symptom: '인쇄 대기열에서 멈춤', solution: '대기열 초기화' }} onClose={vi.fn()} />)
    expect(screen.getByText('증상')).toBeInTheDocument()
    expect(screen.getByText('해결 방법')).toBeInTheDocument()
  })
})
