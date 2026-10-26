/**
 * 코드 값의 화면 표시 이름과 기준 값 (PRD 4.3~4.5, 06 테이블 설계서).
 * API 는 영문 코드 값을 그대로 주고, 한글 표시는 이 파일의 라벨표에서만 붙인다. (docs/07.API_계약서.md)
 * 화면(초안 카드)과 시연용 대화 엔진이 함께 쓴다. 실제 API 에서는 서버가 계산한 값을 그대로 받는다.
 */
import type { CategoryCode, InquiryStatus, Urgency, WorkStatus } from './chatTypes'

export interface CategoryInfo {
  /** 화면에 보일 이름 */
  name: string
  /** 기본 담당 그룹 이름 (시연용. 실제 화면은 API 의 groupName 을 표시한다) */
  groupName: string
  /** 대상 시스템 표시 */
  targetSystem: string
}

export const CATEGORIES: Record<CategoryCode, CategoryInfo> = {
  ACC: { name: '계정·로그인', groupName: '서비스데스크', targetSystem: '사내 계정·SSO' },
  ACS: { name: '접근권한', groupName: '업무시스템팀', targetSystem: '시스템·폴더 권한' },
  NET: { name: 'VPN·네트워크', groupName: '네트워크팀', targetSystem: 'VPN·네트워크' },
  SW: { name: 'SW·라이선스', groupName: '엔드포인트지원팀', targetSystem: '업무용 소프트웨어' },
  HW: { name: 'HW·업무 PC', groupName: '엔드포인트지원팀', targetSystem: 'PC·주변기기' },
  SYS: { name: '사내 시스템', groupName: '업무시스템팀', targetSystem: 'ERP·전자결재·인사/근태' },
  SEC: { name: '정보보안', groupName: '정보보안팀', targetSystem: '메일·보안' },
}

/** 분류를 확정하지 못했을 때 보내는 곳 */
export const FALLBACK_GROUP = '서비스데스크'

export const URGENCY_LABEL: Record<Urgency, string> = { P1: '긴급', P2: '높음', P3: '보통', P4: '낮음' }

/** 업무 상태 이름과 상태 배지 색 */
export const WORK_STATUS: Record<WorkStatus, { label: string; tone: string }> = {
  RDY: { label: '처리 대기', tone: 'recv' },
  WIP: { label: '처리 중', tone: 'prog' },
  FIN: { label: '해결 확인 대기', tone: 'need' },
  CLS: { label: '해결 완료', tone: 'ok' },
}

/** 문의 상태 이름 (inquiries.status) */
export const INQUIRY_STATUS_LABEL: Record<InquiryStatus, string> = {
  IN_PROGRESS: '진행 중',
  AI_RESOLVED: 'AI 해결',
  UNCONFIRMED: '미확인',
  CLOSED_UNRESOLVED: '미해결 종료',
  RECEIVED: '접수 완료',
  HANDED_OFF: '담당자 이관',
}

