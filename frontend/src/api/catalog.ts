/**
 * 분류·긴급도·담당 그룹 기준 값 (PRD 4.3~4.5, 설계서).
 * 화면(초안 카드)과 시연용 대화 엔진이 함께 쓴다. 실제 API 에서는 서버가 계산한 값을 그대로 받는다.
 */
import type { CategoryCode, Priority, TicketStatus } from './chatTypes'

export interface CategoryInfo {
  /** 화면에 보일 이름 */
  name: string
  /** 기본 담당 그룹 */
  group: string
  /** 대상 시스템 표시 */
  system: string
}

export const CATEGORIES: Record<CategoryCode, CategoryInfo> = {
  ACC: { name: '계정·로그인', group: '서비스데스크', system: '사내 계정·SSO' },
  ACS: { name: '접근권한', group: '업무시스템팀', system: '시스템·폴더 권한' },
  NET: { name: 'VPN·네트워크', group: '네트워크팀', system: 'VPN·네트워크' },
  SW: { name: 'SW·라이선스', group: '엔드포인트지원팀', system: '업무용 소프트웨어' },
  HW: { name: 'HW·업무 PC', group: '엔드포인트지원팀', system: 'PC·주변기기' },
  SYS: { name: '사내 시스템', group: '업무시스템팀', system: 'ERP·전자결재·인사/근태' },
  SEC: { name: '정보보안', group: '정보보안팀', system: '메일·보안' },
}

/** 분류를 확정하지 못했을 때 보내는 곳 */
export const FALLBACK_GROUP = '서비스데스크'

export const PRIORITY_LABEL: Record<Priority, string> = { P1: '긴급', P2: '높음', P3: '보통', P4: '낮음' }

/** Ticket 상태 이름과 상태 배지 색 */
export const TICKET_STATUS: Record<TicketStatus, { label: string; tone: string }> = {
  RDY: { label: '처리 대기', tone: 'recv' },
  WIP: { label: '처리 중', tone: 'prog' },
  FIN: { label: '해결 확인 대기', tone: 'need' },
  CLS: { label: '해결 완료', tone: 'ok' },
}
