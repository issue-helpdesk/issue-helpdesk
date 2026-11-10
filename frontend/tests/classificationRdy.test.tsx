import { render,screen,within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { expect,it } from 'vitest'
import App from '../src/App'
import { AuthProvider } from '../src/core/session'
import { tokenStore } from '../src/core/tokenStore'
import { classificationReport,requestClassificationMock,rejectClassificationMock,changeClassificationMock } from '../src/api/mock/classificationMock'
import { findStaffTicket,mutateSeed } from '../src/api/mock/staffTickets'
import { changeTicketStatus } from '../src/api/tickets'
import { MOCK_ACCOUNTS } from '../src/api/mock/accounts'
function show(who:string,path:string){tokenStore.set('mock.'+who);render(<MemoryRouter initialEntries={[path]}><AuthProvider><App/></AuthProvider></MemoryRouter>)}
it('요청은 RDY를 유지하며 WIP·FIN 요청과 재분류를 거절한다',()=>{
 requestClassificationMock(5004,'재분류 요청')
 expect(findStaffTicket(5004)?.workStatus).toBe('RDY')
 expect(findStaffTicket(5004)?.displayStatus).toBe('assigned')
 for(const id of [5002,5009]){expect(()=>requestClassificationMock(id,'요청')).toThrow('처리 대기');expect(()=>changeClassificationMock(id,'ACC','변경')).toThrow('처리 대기')}
})
it('검토 전 처리 시작·완료를 목 API에서도 차단한다',async()=>{
 const user=MOCK_ACCOUNTS.find(u=>u.employeeNo==='EMP-1004')!
 expect((await changeTicketStatus(user,5005,{workStatus:'WIP'})).ok).toBe(false)
 mutateSeed(5005,t=>{t.workStatus='WIP'})
 expect((await changeTicketStatus(user,5005,{workStatus:'FIN',resolutionNote:'결과'})).ok).toBe(false)
})
it('담당자에게 처리 시작은 비활성이고 재분류 기록은 처리 이력에 보인다',async()=>{
 show('EMP-1004','/queue/5005')
 expect(await screen.findByRole('button',{name:'처리 시작'})).toBeDisabled()
 expect(screen.queryByText('재분류 이력')).toBeNull()
 expect(screen.queryByRole('button',{name:'처리 완료'})).toBeNull()
 const history=await screen.findByRole('heading',{name:'처리 이력'})
 expect(history.parentElement).toHaveTextContent('재분류 요청')
})
it.each([5002,5009])('관리자 %s WIP·FIN에는 분류·담당자 영역을 표시하지 않는다',async id=>{
 show('EMP-1178','/tickets/'+id)
 await screen.findByRole('complementary',{name:'티켓 상세'})
 await screen.findByText(findStaffTicket(id)!.summary,{selector:'.dh h2'})
 expect(screen.queryByRole('region',{name:'재분류와 담당자 지정'})).toBeNull()
 expect(screen.queryByRole('button',{name:'분류·담당자 변경'})).toBeNull()
})
it('관리자 요청 건에는 세 버튼을 분리하고 검토 모달 안에는 반려가 없다',async()=>{
 show('EMP-1178','/tickets/5005')
 const section=await screen.findByRole('region',{name:'재분류와 담당자 지정'})
 for(const name of ['재분류 검토','재분류 반려','담당자 변경'])expect(within(section).getByRole('button',{name})).toBeInTheDocument()
 await userEvent.click(within(section).getByRole('button',{name:'재분류 검토'}))
 expect(within(screen.getByRole('dialog')).queryByRole('button',{name:/반려/})).toBeNull()
})
it('반려 후에는 RDY를 유지하면서 재요청만 금지한다',()=>{
 rejectClassificationMock(5005,'현재 분류 유지')
 expect(findStaffTicket(5005)?.workStatus).toBe('RDY')
 expect(classificationReport(5005)?.status).toBe('REJECTED')
 expect(()=>requestClassificationMock(5005,'재요청')).toThrow('반려')
})

it('담당자 변경에서 분류부터 변경 탭을 열고 분류 색상과 자동배정 안내를 본다',async()=>{
 show('EMP-1178','/tickets/5004')
 const section=await screen.findByRole('region',{name:'재분류와 담당자 지정'})
 await userEvent.click(within(section).getByRole('button',{name:'담당자 변경'}))
 await userEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'분류부터 변경'}))
 const modal=screen.getByRole('dialog')
 await userEvent.click(await within(modal).findByRole('combobox'))
 const option=screen.getAllByRole('option',{name:/계정·로그인/})[0]
 expect(option.querySelector('.c-ACC')).not.toBeNull()
 await userEvent.click(option)
 expect(within(modal).getByText(/새 그룹에서 담당자를 자동배정/)).toBeInTheDocument()
 expect(within(modal).getByRole('button',{name:'재분류 지정'})).toBeEnabled()
})
