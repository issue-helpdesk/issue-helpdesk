/**
 * 시연용 "AI 처리" 상담 목록 (design/ITssue-Prototype.html aiRows 와 같은 규칙).
 * 티켓이 만들어지지 않고 AI 안내로 끝난 문의다. 문의자가 직접 해결한 건(문의 저장소)과 최근 7일의 가상 상담을 합친다.
 * 서버에서는 문의 목록(IQ-02)을 displayStatus 로 걸러서 받는다. (사용한 가이드는 목록 응답에 없다)
 */
import type { CategoryCode } from '../chatTypes'
import { allRecords } from './chatStore'

export type AiKind = 'ok' | 'pend' | 'unr'

export interface AiRow {
  id: string
  title: string
  categoryCode: CategoryCode | null
  /** 사용한 가이드 (문서 코드 제목 버전). 없으면 '-' */
  guide: string
  kind: AiKind
  /** 시점 표시 (오늘, 3일 전) */
  when: string
  /** 며칠 전 (직접 해결한 건은 -1: 항상 목록에 있다) */
  day: number
  /** 시각 정렬용 */
  at: number
}

const TITLES: Record<string, string[]> = {
  ACC: ['계정 잠금 해제 방법', '비밀번호 변경 주기 문의', 'MFA 재등록 방법'],
  NET: ['VPN 인증 실패 안내', '재택 Wi-Fi 연결 점검'],
  SW: ['프로그램 설치 위치 문의', '라이선스 할당 확인'],
  HW: ['복합기 연결 방법', '모니터 해상도 설정'],
  SYS: ['전자결재 접속 오류 안내', '근태 화면 캐시 삭제'],
  ACS: ['폴더 권한 신청 절차'],
}
const GUIDES: Record<string, string> = {
  NET: 'IT-NET-001 VPN 접속 장애 대응 가이드 v2',
  ACC: 'IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2',
  SW: 'IT-SW-001 업무용 SW 설치 가이드 v2',
  HW: 'IT-HW-003 프린터·복합기 이용 가이드 v2',
  ACS: 'IT-ACS-001 사내 시스템 접근권한 신청 가이드 v2',
  SYS: 'IT-SYS-001 그룹웨어·ERP 이용 오류 대응 가이드 v2',
}
/** 최근 7일(오늘부터) 하루별 상담 건수 */
const PER_DAY = [38, 41, 44, 36, 47, 40, 33]
const DAY = 86_400_000

export function aiRows(now = Date.now()): AiRow[] {
  const live: AiRow[] = allRecords()
    .filter((r) => r.inquiry.status === 'AI_RESOLVED')
    .map((r) => {
      const src = [...r.inquiry.messages].reverse().find((m) => m.sources?.length)?.sources?.[0]
      return {
        id: `INQ-${r.inquiry.id}`,
        title: r.inquiry.title,
        categoryCode: r.inquiry.categoryCode ?? 'ACC',
        guide: src ? [src.docCode, src.title, src.version].filter(Boolean).join(' ') : '-',
        kind: 'ok' as const,
        when: '방금',
        day: -1,
        at: Date.parse(r.inquiry.updatedAt) || now,
      }
    })
  const cats = Object.keys(TITLES)
  const out: AiRow[] = []
  let n = 0
  PER_DAY.forEach((cnt, d) => {
    for (let k = 0; k < cnt; k++) {
      const c = cats[(n * 3 + d) % cats.length]
      const ts = TITLES[c]
      out.push({
        id: `AI-${2000 + n}`,
        title: ts[n % ts.length],
        categoryCode: c as CategoryCode,
        guide: GUIDES[c] ?? GUIDES.SYS,
        kind: n % 15 === 7 ? 'unr' : n % 7 === 2 ? 'pend' : 'ok',
        when: d === 0 ? '오늘' : `${d}일 전`,
        day: d,
        at: now - d * DAY - k * 60_000,
      })
      n++
    }
  })
  return [...live, ...out]
}
