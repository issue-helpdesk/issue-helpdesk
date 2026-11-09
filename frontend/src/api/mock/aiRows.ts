/**
 * 시연용 "AI 처리" 상담 목록 (design/ITssue-Prototype.html aiRows 와 같은 규칙).
 * 티켓이 만들어지지 않고 AI 안내로 끝난 문의다. 문의자가 직접 해결한 건(문의 저장소)과 최근 7일의 가상 상담을 합친다.
 * 서버에서는 문의 목록(IQ-02)을 displayStatus 로 걸러서 받는다. (사용한 가이드는 목록 응답에 없다)
 */
import type { CategoryCode } from '../chatTypes'
import type { Assessment } from '../assessments'
import { allRecords } from './chatStore'

export type AiKind = 'ok' | 'pend' | 'unr'

export interface AiRow {
  id: string
  /** 서버 문의 번호 (서버 모드의 상세 패널이 판단 이력·사용한 가이드를 읽을 때 쓴다). 모의 시연 건은 null */
  inquiryId: number | null
  /** 문의자 (이름 · 사번). 모르면 빈 글자 */
  user: string
  title: string
  categoryCode: CategoryCode | null
  /** 사용한 가이드 (문서 코드 제목 버전). 없으면 '-' */
  guide: string
  /** 참고한 과거 처리 사례 본문 (시연용). 없으면 비어 있다 */
  cases?: string[]
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
/** 시연용 과거 처리 사례 본문 (분류별). 서버는 사례를 문서 코드 없이 본문만 준다 */
const CASES: Record<string, string[]> = {
  NET: ['VPN 클라이언트를 재설치한 뒤 정상 접속을 확인함', '인증서를 갱신하자 연결 끊김이 해소됨'],
  ACC: ['계정 잠금을 해제하고 비밀번호를 재설정해 로그인 확인'],
  SW: ['소프트웨어 센터에서 최신 설치 파일을 받아 다시 설치함', '관리자 권한으로 실행해 설치 오류가 해소됨'],
  HW: ['프린터 서버 주소를 다시 추가하자 출력이 정상화됨'],
}
const NAMES = ['박서연 · EMP-1049', '김민수 · EMP-1003', '최하은 · EMP-1156', '이도윤 · EMP-1082', '정다은 · EMP-1300', '한지우 · EMP-1064']
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
        inquiryId: r.inquiry.id,
        user: '',
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
        inquiryId: null,
        user: NAMES[n % NAMES.length],
        title: ts[n % ts.length],
        categoryCode: c as CategoryCode,
        guide: GUIDES[c] ?? GUIDES.SYS,
        // 세 건에 한 건은 과거 처리 사례도 참고한 것으로 보여 준다 (사례가 있는 분류만)
        cases: n % 3 === 0 ? CASES[c] : undefined,
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

/**
 * 시연용 AI 판단 이력: 구분에 맞춰 만든다. 해결 확인 대기는 "추가 질문 → 답변", 미연결 종료는 "추가 질문 → 담당자 연결 제안",
 * AI 해결은 "답변" 한 번이다. (서버 모드는 GET /inquiries/{id}/assessments 가 준다)
 */
export function mockJudgments(r: AiRow): Assessment[] {
  const n = Number(r.id.replace(/\D/g, '')) || 0
  const make = (i: number, over: Partial<Assessment> & { conf?: number }, at: number): Assessment => {
    const action = over.action ?? 'ANSWER'
    return {
      id: n * 10 + i,
      inquiryId: r.inquiryId ?? n,
      facts: { summary: r.title },
      missingItems: [],
      urgentSignal: false,
      categoryCode: r.categoryCode,
      inquiryTypeId: null,
      urgency: 'P3',
      urgencyReason: null,
      action,
      aiOutput: { urgencySuggested: 'P3', categoryCode: r.categoryCode ?? undefined, action, confidence: over.conf ?? 0.88 },
      overrideReasons: [],
      createdAt: new Date(at).toISOString(),
      ...over,
    }
  }
  if (r.kind === 'ok') return [make(1, {}, r.at)]
  const first = make(1, { action: 'ASK_MORE', missingItems: r.kind === 'pend' ? ['occurred_at', 'tried_actions'] : ['impact'], conf: 0.76 }, r.at - 3 * 60_000)
  return r.kind === 'pend' ? [first, make(2, {}, r.at)] : [first, make(2, { action: 'ESCALATE', conf: 0.69 }, r.at)]
}
