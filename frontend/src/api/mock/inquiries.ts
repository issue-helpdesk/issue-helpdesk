/**
 * 시연용 문의 목록 (design/ITssue-Prototype.html 의 문의자 김서연 화면 데이터 일부).
 * 사번(HS1001)의 문의만 있으며, 다른 계정은 빈 목록이다.
 */
import type { InquirySummary } from '../types'

export const MOCK_INQUIRIES: Record<string, InquirySummary[]> = {
  HS1001: [
    { id: 'INQ-S1', title: 'VPN 연결이 자주 끊겨요', stateLabel: '처리 중', stateKind: 'progress', unread: 1, when: '어제' },
    { id: 'INQ-S2', title: '계정 잠금 해제 방법', stateLabel: 'AI 해결', stateKind: 'ai', unread: 0, when: '3일 전' },
    { id: 'INQ-U0', title: 'VPN 인증서 갱신이 필요한가요', stateLabel: '미확인', stateKind: 'warn', unread: 0, when: '6일 전' },
    { id: 'INQ-T0', title: '노트북 화면 깜빡임', stateLabel: '해결 완료', stateKind: 'resolved', unread: 0, when: '8일 전' },
  ],
}
