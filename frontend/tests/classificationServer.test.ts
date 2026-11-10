import { afterEach,beforeEach,expect,it,vi } from 'vitest'
import { findStaffTicket } from '../src/api/mock/staffTickets'
const base={...findStaffTicket(5004)!}
const type={id:27,code:'ACC-01',name:'비밀번호 만료·초기화',categoryCode:'ACC' as const,defaultGroup:{id:1,name:'서비스데스크'},isActive:true}
const json=(data:unknown)=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}})
beforeEach(()=>{vi.resetModules();vi.stubEnv('VITE_USE_MOCK_TICKET','false');vi.stubEnv('VITE_SERVER_INTAKE','true')})
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals()})
it('서버 RF 후보와 분류 API를 사용하고 별도 수동배정 요청을 보내지 않는다',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(json({items:[type]})).mockResolvedValueOnce(json({...base,category:{code:'ACC',name:'계정·로그인'},assignStatus:'PENDING'}));vi.stubGlobal('fetch',fetch)
 const api=await import('../src/api/classification')
 expect(await api.listClassificationTypes()).toMatchObject({ok:true,data:[type]})
 expect(await api.saveClassification(base,type,'계정 문제 확인')).toMatchObject({ok:true})
 expect(String(fetch.mock.calls[0][0])).toContain('/inquiry-types?isActive=true')
 expect(String(fetch.mock.calls[1][0])).toContain('/tickets/5004/classification')
 expect(fetch.mock.calls[1][1].method).toBe('PUT')
 expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({inquiryTypeId:27,reason:'계정 문제 확인'})
 expect(fetch).toHaveBeenCalledTimes(2)
})
it('서버 쓰기 미설정이면 준비 중으로 안내하고 저장 요청을 보내지 않는다',async()=>{
 vi.stubEnv('VITE_SERVER_INTAKE','false');const fetch=vi.fn();vi.stubGlobal('fetch',fetch)
 const api=await import('../src/api/classification')
 expect(await api.saveClassification(base,type,'계정 문제 확인')).toMatchObject({ok:false,error:{code:'NOT_IMPLEMENTED'}})
 expect(fetch).not.toHaveBeenCalled()
})
it('RDY가 아니면 서버로 분류 변경을 보내지 않는다',async()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);const api=await import('../src/api/classification')
 expect(await api.saveClassification({...base,workStatus:'WIP'},type,'변경')).toMatchObject({ok:false,error:{code:'TICKET_INVALID_TRANSITION'}})
 expect(fetch).not.toHaveBeenCalled()
})

it('운영 카드가 서버의 미분류와 열린 재분류 요청을 구분한다',async()=>{
 const page=(items:unknown[])=>({items,page:1,size:100,totalCount:items.length,totalPages:1})
 const missing={...base,id:8039,category:null,assignee:null,assignStatus:'NEEDS_ADMIN',needsAdmin:true,jiraSyncStatus:'SYNCED'}
 const report={...base,id:8005,classificationReportOpen:true}
 const fetch=vi.fn().mockResolvedValueOnce(json(page([missing]))).mockResolvedValueOnce(json(page([report])));vi.stubGlobal('fetch',fetch)
 const {getOpsSnapshot}=await import('../src/api/ops')
 const admin=(await import('../src/api/mock/accounts')).MOCK_ACCOUNTS.find(u=>u.serviceRole==='ADMIN')!
 const result=await getOpsSnapshot(admin)
 expect(result).toMatchObject({ok:true,data:{unclassified:[{id:8039}],assign:[],reclassification:[{id:8005}]}})
 expect(String(fetch.mock.calls[1][0])).toContain('classificationReportOpen=true')
})
