/**
 * 정렬 열 머리: 서버가 정렬을 받지 않는 열은 버튼 없이 글자만 보인다 (plain).
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SortTh } from '../src/ui/SortTh'

const wrap = (el: React.ReactNode) => render(<table><thead><tr>{el}</tr></thead></table>)

describe('SortTh', () => {
  it('기본은 눌러서 정렬하는 버튼이다', () => {
    wrap(<SortTh col="a" label="제목" sort={null} onSort={() => {}} />)
    expect(screen.getByRole('button', { name: '제목' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader')).toHaveAttribute('aria-sort', 'none')
  })

  it('plain 이면 버튼 없이 글자만 보인다', () => {
    wrap(<SortTh plain col="a" label="제목" sort={null} onSort={() => {}} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByRole('columnheader', { name: '제목' })).not.toHaveAttribute('aria-sort')
  })
})
