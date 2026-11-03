/**
 * 출처 미리보기 창: 제목·넓게/좁게·✕ 는 위에 고정, 본문만 스크롤, 넓게/좁게 전환.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SourcePreview } from '../src/ui/SourcePreview'

const source = { docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드', version: 'v2', section: '3.3', excerpt: ['### 조치 방법', '1. 재시작합니다.', '2. 다시 연결합니다.'].join('\n') }

describe('출처 미리보기 창', () => {
  it('위에 닫기(✕)가 있고, 아래쪽 닫기 버튼은 없으며, 본문은 따로 스크롤된다', async () => {
    const onClose = vi.fn()
    render(<SourcePreview source={source} onClose={onClose} />)
    const dlg = screen.getByRole('dialog')
    expect(dlg.querySelector('.mh')).toContainElement(screen.getByRole('button', { name: '닫기' }))
    expect(dlg.querySelector('.mbody')).toHaveTextContent('조치 방법')
    expect(dlg.querySelector('.mbody')).not.toContainElement(screen.getByRole('button', { name: '닫기' }))
    expect(screen.getAllByRole('button', { name: '닫기' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '닫기' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('넓게/좁게 버튼으로 창 폭을 바꾼다', async () => {
    render(<SourcePreview source={source} demo onClose={() => {}} />)
    const dlg = screen.getByRole('dialog')
    expect(dlg).toHaveClass('msrc')
    expect(dlg).not.toHaveClass('big')
    expect(screen.getByText('출처 미리보기 (시연)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '창 넓게' }))
    expect(dlg).toHaveClass('big')
    await userEvent.click(screen.getByRole('button', { name: '창 좁게' }))
    expect(dlg).not.toHaveClass('big')
  })
})
