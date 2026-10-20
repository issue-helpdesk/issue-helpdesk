/**
 * 시연용 FAQ 데이터 (design/ITssue-Prototype.html 과 같은 내용, 출처는 guides 실제 문서 기준).
 * 실제 API(GET /faqs)로 전환(VITE_USE_MOCK=false)하면 쓰이지 않는다.
 */
import type { Faq } from '../types'
import { guideSource } from './sources'

export const MOCK_FAQS: Faq[] = [
  {
    id: 'FAQ-001',
    categoryCode: 'NET',
    question: 'VPN에 연결할 수 없다고 나와요.',
    answer: 'VPN 클라이언트를 최신 버전으로 업데이트하고 PC를 재부팅한 뒤 다시 연결해 보세요. 공용 Wi-Fi라면 휴대폰 핫스팟으로 시도해 보세요.',
    sources: [guideSource('IT-NET-001 VPN 접속 장애 대응 가이드 v2 · 3.1')],
  },
  {
    id: 'FAQ-002',
    categoryCode: 'ACC',
    question: '계정이 잠겼어요. 어떻게 해야 하나요?',
    answer: '5회 연속 실패하면 잠기며 10분 후 자동으로 해제돼요. 급하면 [지금 잠금 해제 (본인 인증)]를 누르고, 비밀번호를 잊었다면 셀프 초기화를 이용해 주세요.',
    sources: [guideSource('IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3.2')],
  },
  {
    id: 'FAQ-003',
    categoryCode: 'SW',
    question: '업무용 프로그램은 어디서 설치하나요?',
    answer: '사내 IT 포털의 소프트웨어 센터에서 설치해요. [설치 요청]이 보이는 유료 프로그램은 라이선스를 신청해야 해요.',
    sources: [guideSource('IT-SW-001 업무용 SW 설치 가이드 v2 · 3.1')],
  },
  {
    id: 'FAQ-004',
    categoryCode: 'HW',
    question: '복합기 인쇄가 되지 않아요.',
    answer: '복합기 화면의 오류를 확인하고, 인쇄 대기열의 문서를 모두 취소한 뒤 PC를 재부팅해 다시 인쇄해 보세요.',
    sources: [guideSource('IT-HW-003 프린터·복합기 이용 가이드 v2 · 3.1')],
  },
  {
    id: 'FAQ-005',
    categoryCode: 'ACS',
    question: '폴더 접근권한은 어떻게 신청하나요?',
    answer: '그룹웨어 [IT 요청] > [권한 신청]에서 신청하고 팀장 승인을 받아야 해요. ITssue 접수가 승인 절차를 대신하지는 않아요.',
    sources: [guideSource('IT-ACS-001 사내 시스템 접근권한 신청 가이드 v2 · 3.1')],
  },
]

/** 분류 코드별 이름 (PRD 3.1 의 7개 Category) */
export const CATEGORY_NAME: Record<string, string> = {
  ACC: '계정·로그인',
  ACS: '접근권한',
  NET: 'VPN·네트워크',
  SW: 'SW·라이선스',
  HW: 'HW·업무 PC',
  SYS: '사내 시스템',
  SEC: '정보보안',
}
