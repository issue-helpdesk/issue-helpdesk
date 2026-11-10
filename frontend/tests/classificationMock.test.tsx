import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { classificationReport, requestClassificationMock, rejectClassificationMock, changeClassificationMock, classificationPending, confirmClassificationMock, missingCategoryMockTickets } from '../src/api/mock/classificationMock'
import { findStaffTicket } from '../src/api/mock/staffTickets'

describe('프론트 목 모드 재분류 흐름',()=>{
 it('미분류 예시를 분류하면 해당 그룹에 자동배정된다',()=>{
   expect(missingCategoryMockTickets().some(t=>t.id===5039)).toBe(true)
   changeClassificationMock(5039,'NET','계정 문의를 검토해 분류 지정')
   expect(classificationPending(5039)).toBe(true)
   expect(findStaffTicket(5039)?.assignStatus).toBe('PENDING')
   const t=confirmClassificationMock(5039)
   expect(classificationPending(5039)).toBe(false)
   expect(t.group?.name).toBe('네트워크팀')
   expect(t.assignStatus).toBe('ASSIGNED')
   expect(t.assignee).not.toBeNull()
 })
 it('열린 요청 중복과 반려 후 재요청을 막고 반려 사유를 유지한다',()=>{
   requestClassificationMock(5004,'계정 인증 오류 확인 요청',{code:'ACC-01',name:'계정 인증'})
   expect(classificationReport(5004)?.suggestedInquiryType).toEqual({code:'ACC-01',name:'계정 인증'})
   expect(()=>requestClassificationMock(5004,'중복')).toThrow('이미')
   rejectClassificationMock(5004,'현재 분류를 유지합니다.')
   expect(classificationReport(5004)?.resolution).toBe('현재 분류를 유지합니다.')
   expect(()=>requestClassificationMock(5004,'다시 요청')).toThrow('반려')
 })
 it('관리자 운영 현황에서 미분류를 지정하면 모달이 닫히고 자동배정된다',async()=>{
   tokenStore.set('mock.EMP-1178')
   render(<MemoryRouter initialEntries={['/ops']}><AuthProvider><App /></AuthProvider></MemoryRouter>)
   await userEvent.click(await screen.findByRole('button',{name:'분류 지정'}))
   const section=await screen.findByRole('region',{name:'재분류와 담당자 지정'})
   await userEvent.click(within(section).getByRole('button',{name:'분류 지정'}))
   let modal=screen.getByRole('dialog')
   await userEvent.click(within(modal).getByRole('combobox'))
   await userEvent.click(screen.getAllByRole('option',{name:/VPN·네트워크/})[0])
   await userEvent.type(within(modal).getByLabelText('분류 지정 사유 (필수)'),'분류를 확인했어요.')
   await userEvent.click(within(modal).getByRole('button',{name:'분류 지정'}))
   await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
   expect(findStaffTicket(5039)?.assignStatus).toBe('ASSIGNED')
   expect(findStaffTicket(5039)?.assignee).not.toBeNull()
   expect(screen.queryByText('배정 확인 이어하기')).toBeNull()
   expect(screen.queryByText('현재 담당자 유지하고 완료')).toBeNull()

 })
})
