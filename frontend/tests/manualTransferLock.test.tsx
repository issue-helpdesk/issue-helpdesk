/**
 * 담당자용 매뉴얼은 외부 AI 전송이 금지로 고정된다 (서버 DC-07·09, `DOCUMENT_MANUAL_TRANSFER_FIXED`).
 * 등록 설정 창은 매뉴얼이면 전송 칸을 고를 수 없게 하고 이유를 보이며, 새 현행 전환 오류 문구가 사전에 있다.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { displayMessage } from '../src/api/errorText'
import { PolicyModal } from '../src/ui/PolicyModal'

const NOTE = '담당자용 매뉴얼은 외부 AI 전송이 금지로 고정돼요.'
const open = (txLockedNote?: string) => render(<PolicyModal initialScope="담당자 이상" initialTx="금지" txLockedNote={txLockedNote} intro="확인해 주세요" confirmLabel="올리기" onConfirm={vi.fn()} onClose={vi.fn()} />)

describe('등록 설정 창', () => {
  it('매뉴얼이면 외부 AI 전송을 금지 밖으로 고를 수 없고 이유를 보인다 (열람 범위는 바꿀 수 있다)', () => {
    open(NOTE)
    const tx = screen.getByRole('group', { name: '외부 AI 전송' })
    expect(tx.querySelector('button[aria-pressed="true"]')).toHaveTextContent('금지')
    expect(screen.getByRole('button', { name: '허용' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '마스킹 후 허용' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '금지' })).toBeEnabled()
    expect(screen.getByText(NOTE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전 직원' })).toBeEnabled()
  })

  it('가이드이면 외부 AI 전송을 자유롭게 고른다', () => {
    open()
    expect(screen.getByRole('button', { name: '허용' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '마스킹 후 허용' })).toBeEnabled()
    expect(screen.queryByText(NOTE)).toBeNull()
  })
})

describe('현행 전환·정책 변경 오류 문구', () => {
  it('새로 생긴 세 코드의 문구가 사전에 있다', () => {
    expect(displayMessage('DOCUMENT_VERSION_ORPHANED', '서버 문구')).toBe('연결된 해결 사례 제안이 없는 초안 버전이라 현행으로 전환할 수 없어요.')
    expect(displayMessage('DOCUMENT_VERSION_OUTDATED', '서버 문구')).toMatch(/지금 현행에 반영된 해결 사례가 사라져요/)
    expect(displayMessage('DOCUMENT_MANUAL_TRANSFER_FIXED', '서버 문구')).toMatch(/금지에서 바꿀 수 없어요/)
  })
})
