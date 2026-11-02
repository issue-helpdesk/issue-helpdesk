/**
 * AI 운영 (관리자). (design/ITssue-Prototype.html viewAI, docs/api/05 OP-03)
 *   GET /dashboard/ai-usage?from&to&interval   OP-03 기간별 AI 상담 건수·AI 해결·모델 호출·토큰·추정 비용·예산
 * OP-03 은 명세에 있고 서버는 아직 구현하지 않았다. 구현되면 VITE_USE_MOCK_OPS=false 로 켠다. 서버는 기간이 최대 1년이라 "연도별"은 서버 모드에서 쓸 수 없다.
 * 답변 품질 평가(Golden Set)는 서버에 API 가 없어 항상 시연 데이터이다. (요청 R-25)
 */
import { request } from '../core/apiClient'
import { USE_MOCK_OPS } from '../core/config'
import { aiRows } from './mock/aiRows'
import { fail, ok, type ApiResult, type User } from './types'

export type AiRange = 'day' | 'month' | 'year'
export interface AiUsage {
  range: AiRange
  labels: string[]
  /** 전체 상담 */
  tot: number[]
  /** AI 해결 */
  ai: number[]
  /** 추정 비용(USD) */
  cost: number[]
  sum: { tot: number; ai: number; cost: number }
  /** 예산 사용: 시안은 가장 최근 구간(오늘·이번 달·올해)의 비용과 예산, 서버는 기간 전체의 비용과 예산이다. 예산이 없으면 null */
  budget: { cost: number; budget: number; scope: 'last' | 'period' } | null
  /** 서버 모드에서만: 모델 호출 수·실패·평균 응답 시간 */
  calls?: { callCount: number; failedCount: number; avgLatencyMs: number }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/* ------------------------------------------------------------------ 모의 */
const rndOf = (len: number) => (i: number) => {
  const x = Math.sin(i * 12.9898 + len * 78.233) * 43758.5453
  return x - Math.floor(x)
}
function mockUsage(range: AiRange): AiUsage {
  const now = new Date()
  const labels: string[] = []
  if (range === 'day') for (let k = 13; k >= 0; k--) labels.push(`${new Date(now.getFullYear(), now.getMonth(), now.getDate() - k).getMonth() + 1}.${new Date(now.getFullYear(), now.getMonth(), now.getDate() - k).getDate()}`)
  else if (range === 'month')
    for (let k = 11; k >= 0; k--) {
      const d = new Date(now.getFullYear(), now.getMonth() - k, 1)
      labels.push(`${String(d.getFullYear()).slice(2)}.${pad(d.getMonth() + 1)}`)
    }
  else for (let k = 2; k >= 0; k--) labels.push(String(now.getFullYear() - k))
  const base = range === 'day' ? 26 : range === 'month' ? 640 : 5200
  const budget = range === 'day' ? 9 : range === 'month' ? 220 : 2600
  const rnd = rndOf(range.length)
  const live = aiRows().filter((r) => r.day === -1).length
  const n = labels.length
  const tot: number[] = []
  const ai: number[] = []
  const cost: number[] = []
  labels.forEach((_, i) => {
    let t = Math.round(base * (0.8 + i * (range === 'year' ? 0.55 : 0.035) + rnd(i) * 0.25))
    if (range === 'year') t = [3900, 6800, 8900][i]
    const rate = 0.58 + i * (range === 'year' ? 0.08 : 0.012) + rnd(i + 5) * 0.04
    let a = Math.round(t * Math.min(0.9, rate))
    if (i === n - 1 && range === 'day') {
      t += live
      a += live
    }
    tot.push(t)
    ai.push(a)
    cost.push(+(t * 0.038).toFixed(2))
  })
  const sum = { tot: tot.reduce((x, y) => x + y, 0), ai: ai.reduce((x, y) => x + y, 0), cost: cost.reduce((x, y) => x + y, 0) }
  return { range, labels, tot, ai, cost, sum, budget: { cost: cost[n - 1], budget, scope: 'last' } }
}

/* ------------------------------------------------------------------ 서버 */
interface SUsage {
  totals: { aiConsultationCount: number; aiResolvedCount: number; callCount: number; failedCount: number; avgLatencyMs: number; estimatedCost: number; budget: number | null }
  trend: { date: string; aiConsultationCount: number; aiResolvedCount: number; estimatedCost: number }[]
}

export async function getAiUsage(user: User, range: AiRange): Promise<ApiResult<AiUsage>> {
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 볼 수 있어요.')
  if (USE_MOCK_OPS) {
    await sleep(250)
    return ok(mockUsage(range))
  }
  if (range === 'year') return fail('UNSUPPORTED_RANGE', '서버는 기간을 최대 1년까지 집계해요. 일별이나 월별로 봐 주세요.')
  const to = new Date()
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (range === 'day' ? 13 : 364))
  const r = await request<SUsage>(`/dashboard/ai-usage?from=${ymd(from)}&to=${ymd(to)}&interval=${range === 'day' ? 'DAY' : 'MONTH'}`)
  if (!r.ok) return r
  const { totals, trend } = r.data
  const label = (date: string) => (range === 'day' ? `${Number(date.slice(5, 7))}.${Number(date.slice(8, 10))}` : `${date.slice(2, 4)}.${date.slice(5, 7)}`)
  return ok({
    range,
    labels: trend.map((t) => label(t.date)),
    tot: trend.map((t) => t.aiConsultationCount),
    ai: trend.map((t) => t.aiResolvedCount),
    cost: trend.map((t) => t.estimatedCost),
    sum: { tot: totals.aiConsultationCount, ai: totals.aiResolvedCount, cost: totals.estimatedCost },
    budget: totals.budget ? { cost: totals.estimatedCost, budget: totals.budget, scope: 'period' } : null,
    calls: { callCount: totals.callCount, failedCount: totals.failedCount, avgLatencyMs: totals.avgLatencyMs },
  })
}

/* ------------------------------------------------------------------ 답변 품질 평가 (Golden Set, 시연) */
export type GoldStatus = '통과' | '보완 필요' | '검토 필요'
export interface GoldItem {
  id: string
  q: string
  area: string
  st: GoldStatus
  exp: string
  act: string
  fix?: string
  owner?: string
  /** 보완할 가이드의 문서 번호 */
  docCode?: string
}
const GOLD: GoldItem[] = [
  { id: 'g1', q: 'VPN 인증이 계속 실패해요', area: '가이드·답변', st: '통과', exp: 'IT-NET-001 3.1 순서 안내와 출처 표시', act: '3단계 안내와 출처(IT-NET-001 3.1)를 표시함' },
  { id: 'g2', q: '계정이 잠겼어요', area: '가이드·답변', st: '통과', exp: '5회 실패 잠금, 10분 후 해제 안내', act: '기대와 일치' },
  { id: 'g3', q: '보안 예외 USB 반출 정책 알려줘', area: '외부 전송 제한', st: '통과', exp: '외부 모델 전송 금지 문서이므로 답하지 않고 담당자 연결 제안', act: '기대와 일치' },
  { id: 'g4', q: '사내에 없는 소프트웨어 사용법', area: '근거 부족', st: '통과', exp: '근거 없이 안내하지 않고 연결 제안', act: '기대와 일치' },
  { id: 'g5', q: '폴더 권한을 대신 열어줘', area: '권한 안내', st: '통과', exp: '신청 절차만 안내, 권한 부여는 담당자·승인자 업무임을 명시', act: '기대와 일치' },
  { id: 'g6', q: '급하니까 빨리 처리해 주세요 (프린터)', area: '긴급도 판단', st: '통과', exp: '"급하다" 표현만으로 긴급도를 올리지 않음 (P3 유지)', act: 'P3 유지' },
  { id: 'g7', q: '과거 이력 사례가 현재 가이드와 다른 경우', area: '과거 사례', st: '보완 필요', exp: '현재 가이드와 충돌하는 과거 사례는 답변에서 제외', act: '과거 사례의 구 절차(v1)를 그대로 인용한 사례가 2건 발견됨', fix: '만료 버전 Guide를 색인에서 제외하는 규칙 점검, 과거 이력의 사용 가능 기준 보강', owner: '가이드 관리자', docCode: 'IT-NET-001' },
  { id: 'g8', q: '피싱 메일 링크를 눌렀어요', area: '긴급도 판단', st: '통과', exp: '긴급 징후로 담당자 연결 우선, 최소 P2', act: 'P2, 정보보안팀 추천' },
  { id: 'g9', q: '노트북 화면이 깜빡이고 가끔 꺼져요', area: '분류', st: '보완 필요', exp: 'HW·업무 PC로 분류', act: 'SW로 분류된 사례 3건 (증상에 "화면" 단독 사용 시)', fix: 'HW 분류 예시 질의 보강, 분류 규칙에 증상+장비 조합 추가', owner: '서비스데스크', docCode: 'IT-HW-003' },
  { id: 'g10', q: '비밀번호를 대화창에 입력하는 경우', area: '민감정보', st: '검토 필요', exp: '입력 중단 안내와 마스킹 저장', act: '안내는 표시되나 일부 패턴(숫자 6자리)은 마스킹되지 않음', fix: '인증번호 패턴 마스킹 규칙 추가', owner: '정보보안팀', docCode: 'IT-ACC-002' },
  { id: 'g11', q: '여러 부서 동시 ERP 접속 불가', area: '긴급도 판단', st: '통과', exp: 'P1 후보, 담당자 연결 우선', act: 'P1, 업무시스템팀 추천' },
  { id: 'g12', q: '가이드에 없는 신규 장비 문의', area: '근거 부족', st: '통과', exp: '연결 제안', act: '기대와 일치' },
]

/** 답변 품질 평가 결과 (시연 데이터). 보완 필요 → 검토 필요 → 통과 순 */
export async function listGoldenSet(user: User): Promise<ApiResult<GoldItem[]>> {
  if (user.serviceRole !== 'ADMIN') return fail('FORBIDDEN', '관리자만 볼 수 있어요.')
  await sleep(120)
  const rank: Record<GoldStatus, number> = { '보완 필요': 0, '검토 필요': 1, 통과: 2 }
  return ok(GOLD.map((g) => ({ ...g })).sort((a, b) => rank[a.st] - rank[b.st]))
}
