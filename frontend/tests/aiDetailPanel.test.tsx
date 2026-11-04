/**
 * 전체 문의 → AI 처리: 행을 누르면 오른쪽에 AI 처리 상세 패널이 열린다 (제목·요약·AI 판단 이력·사용한 가이드).
 * 추가 질문(ASK_MORE) 뒤에 다음 판단이 있으면 두 판단 사이에 "AI가 더 물어본 항목"이 화살표로 보이고,
 * 다른 행을 누르면 패널은 그대로 두고 안의 내용만 바뀐다. (모의 모드: 구분에 맞춘 시연 판단 이력)
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'

const SLOW = { timeout: 3000 }

function renderAdmin() {
  tokenStore.set('mock.EMP-1178')
  return render(
    <MemoryRouter initialEntries={['/tickets']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** 목록의 데이터 행 중 구분 글이 들어 있는 첫 행 */
const rowOf = (kind: string) => screen.getAllByRole('row').find((r) => r.closest('tbody') && (r.textContent ?? '').includes(kind))!

describe('AI 처리 상세 패널', () => {
  it('행을 누르면 열리고, 판단 사이에 화살표가 있으며, 다른 행을 누르면 내용만 바뀌고, 닫을 수 있다', async () => {
    renderAdmin()
    await userEvent.click(await screen.findByRole('button', { name: 'AI 처리' }, SLOW))
    await screen.findAllByRole('row', undefined, SLOW)
    expect(screen.queryByRole('complementary', { name: 'AI 처리 상세' })).toBeNull()

    // 해결 확인 대기: 추가 질문 → 답변, 두 판단 사이에 AI가 더 물어본 항목
    await userEvent.click(within(rowOf('해결 확인 대기')).getByRole('button'))
    const panel = await screen.findByRole('complementary', { name: 'AI 처리 상세' })
    expect(within(panel).getByText('AI 판단 이력')).toBeInTheDocument()
    expect(within(panel).getByText('판단 1')).toBeInTheDocument()
    expect(within(panel).getByText('판단 2')).toBeInTheDocument()
    expect(within(panel).getByText(/AI가 더 물어봤어요/).closest('.asc')).toHaveTextContent('발생 시점, 시도한 조치')
    // 사용한 가이드(목록에는 칼럼을 두지 않는다)
    expect(await within(panel).findByText(/^IT-[A-Z]+-\d+ v\d/, undefined, SLOW)).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: /사용한 가이드/ })).toBeNull()

    // 다른 행(AI 해결)을 누르면 패널은 하나 그대로이고 판단 1개, 화살표 없음
    await userEvent.click(within(rowOf('AI 해결')).getByRole('button'))
    await waitFor(() => expect(within(screen.getByRole('complementary', { name: 'AI 처리 상세' })).queryByText('판단 2')).toBeNull())
    expect(screen.getAllByRole('complementary', { name: 'AI 처리 상세' })).toHaveLength(1)
    expect(within(screen.getByRole('complementary', { name: 'AI 처리 상세' })).getByText('판단 1')).toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'AI 처리 상세' })).queryByText(/AI가 더 물어봤어요/)).toBeNull()

    // 미연결 종료: 추가 질문 → 담당자 연결, 화살표에 영향 범위
    await userEvent.click(within(rowOf('미연결 종료')).getByRole('button'))
    await waitFor(() => expect(within(screen.getByRole('complementary', { name: 'AI 처리 상세' })).getByText(/AI가 더 물어봤어요/).closest('.asc')).toHaveTextContent('영향 범위'))

    // 닫기
    await userEvent.click(within(screen.getByRole('complementary', { name: 'AI 처리 상세' })).getByRole('button', { name: '닫기' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'AI 처리 상세' })).toBeNull(), SLOW)
  })
})
