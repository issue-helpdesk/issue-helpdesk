/**
 * 시연용 가상 계정 (design/ITssue-Prototype.html 과 같은 데이터).
 * 실제 사용자 정보가 아니며, 비밀번호 'demo' 는 시연용 공개 값이다.
 * 실제 API 로 전환(VITE_USE_MOCK=false)하면 쓰이지 않는다.
 */
import type { User } from '../types'

/** 모든 가상 계정의 공통 비밀번호 */
export const MOCK_PASSWORD = 'demo'

export const MOCK_ACCOUNTS: User[] = [
  { id: 'HS1001', name: '김서연', dept: '개발1팀', role: 'user', status: '승인' },
  { id: 'HS1107', name: '김담당', dept: '네트워크팀', role: 'staff', status: '승인' },
  { id: 'HS0912', name: '최관리', dept: '서비스데스크', role: 'admin', status: '승인' },
  { id: 'HS1003', name: '박민수', dept: '영업1팀', role: 'user', status: '승인' },
  { id: 'HS1004', name: '이지은', dept: '디자인팀', role: 'user', status: '승인' },
  { id: 'HS2210', name: '신입사원', dept: '연구소', role: 'user', status: '승인 대기' },
  { id: 'HS1488', name: '박과장', dept: '영업2팀', role: 'user', status: '이용 제한' },
]

/** 로그인 화면의 "시연용 바로 로그인" 버튼 목록 */
export const MOCK_QUICK_LOGINS: { id: string; label: string }[] = [
  { id: 'HS1001', label: '문의자' },
  { id: 'HS1107', label: '담당자' },
  { id: 'HS0912', label: '관리자' },
  { id: 'HS2210', label: '승인 대기 계정' },
  { id: 'HS1488', label: '이용 제한 계정' },
]
