/**
 * 시연용 대화 엔진 (design/ITssue-Prototype.html 의 "대화 엔진"을 옮긴 것).
 * 실제 AI·Jira·Slack 호출 없이 정해진 규칙으로만 답하므로 같은 입력에는 항상 같은 답이 나온다.
 * 실제 API(VITE_USE_MOCK=false)에서는 쓰이지 않으며, 같은 일을 백엔드가 한다.
 *
 * 흐름 (PRD 4.2~4.9)
 *   첫 메시지 → 부족한 정보(시스템·증상·시점·영향·시도)를 하나씩 확인 → 긴급 징후가 있으면 바로 담당자 연결 제안
 *   → Guide 우선 검색 → 부족하면 도입 이전 처리 이력 → 둘 다 없으면 지원 범위 밖
 *   → 해결 확인(해결 / 미해결) → 접수 초안 확인·수정 → 접수(RCPT 번호) → Jira·담당자 배정 진행
 */
import { nowIso } from '../../core/format'
import { hasMask, MASK_NOTICE, maskSensitive } from '../../core/mask'
import { CATEGORIES, FALLBACK_GROUP } from '../catalog'
import { detectInquiryType } from './inquiryTypes'
import {
  IDLE_TEXT,
  type CategoryCode,
  type IdleKind,
  type ChatBlock,
  type ChatReply,
  type DraftEdit,
  type GuideSource,
  type Inquiry,
  type LegacyCase,
  type Urgency,
  type RejudgedField,
  type ReplyRequest,
  type Ticket,
} from '../chatTypes'
import {
  later,
  mockConfig,
  nextIts,
  nextRcpt,
  notify,
  push,
  createRecord,
  removeRecord,
  type IntakeKey,
  type StoreRecord,
} from './chatStore'

/* ------------------------------------------------------------------ 규칙(정규식) */
export const RE = {
  /** 보안 사고 의심 */
  sec: /(피싱|악성|랜섬|해킹|도용|탈취|도난|분실|유출|의심.{0,6}(메일|링크|파일|접속)|(링크|첨부).{0,8}(눌렀|열었|클릭))/,
  /** 여러 사용자 */
  multi: /(전사|전체 직원|전 직원|여러 부서|다른 팀도|모든 팀|(?:[2-9]\d|\d{3,})\s*명|다들)/,
  /** 광범위한 대응이 필요한 규모 */
  wide: /(전사|전체 직원|전 직원|여러 부서|(?:[2-9]\d|\d{3,})\s*명|다수)/,
  /** 업무 중단 */
  stop: /(중단|불가|못 ?해|안 ?돼|먹통|접속.*안|전혀)/,
  /** 외부 전송이 제한된 문서와 관련된 질의 (시연) */
  rest: /(보안 예외|USB|반출|예외 신청)/,
}

/** 문장에서 분류를 짐작한다. 알 수 없으면 null (지원 범위 밖 후보) */
export function detectCategory(t: string): CategoryCode | null {
  if (RE.sec.test(t)) return 'SEC'
  if (/(VPN|와이파이|Wi-?Fi|인터넷|네트워크|사내망|랜선)/i.test(t)) return 'NET'
  if (/(권한)/.test(t)) return 'ACS'
  if (/(프린터|복합기|인쇄|노트북|PC|마우스|키보드|모니터|화면)/i.test(t)) return 'HW'
  if (/(설치|프로그램|라이선스|소프트웨어|Excel|엑셀|PDF)/i.test(t)) return 'SW'
  if (/(ERP|전자결재|근태|인사|포털|메신저|서버|DB)/i.test(t)) return 'SYS'
  if (/(계정|잠[겼금]|로그인|비밀번호|패스워드|SSO|MFA|OTP)/i.test(t)) return 'ACC'
  return null
}

/** 긴급도 P1~P4 와 판단 근거 (PRD 4.5). "급하다"는 표현만으로는 올리지 않는다. */
export function calcUrgency(text: string): { urgency: Urgency; urgencyReasons: string[] } {
  const why: string[] = []
  let urgency: Urgency = 'P3'
  const sec = RE.sec.test(text)
  const multi = RE.multi.test(text)
  const stop = RE.stop.test(text)
  if (sec) {
    urgency = 'P2'
    why.push('보안 사고 의심은 최소 P2')
    if (RE.wide.test(text)) {
      urgency = 'P1'
      why.push('다수 사용자·광범위한 보안 대응 필요')
    }
  } else if (multi && stop) {
    urgency = 'P1'
    why.push('여러 사용자의 업무 중단 정황')
  } else if (/(전면|모두 중단|업무.{0,6}(불가|중단)|아무것도 못|아예)/.test(text) && !/(대체|가능)/.test(text)) {
    urgency = 'P2'
    why.push('개인 업무 전면 중단')
  } else if (/(문의|신청|궁금|알려|방법)/.test(text) && !stop) {
    urgency = 'P4'
    why.push('현재 업무 지장 없는 문의·사전 신청')
  } else {
    why.push('개인 업무 일부 지장, 대체 방법 있음')
  }
  if (/(급해|빨리|급합니다)/.test(text)) why.push('"급하다"는 표현만으로 상향하지 않음')
  return { urgency, urgencyReasons: why }
}

/* ------------------------------------------------------------------ 확인 질문 */
const QUESTIONS: Record<IntakeKey, { ask: string; chips: string[] }> = {
  targetSystem: { ask: '어느 시스템이나 프로그램에서 문제가 발생했나요?', chips: ['VPN', '사내 로그인(SSO)', '업무용 프로그램', '프린터'] },
  summary: { ask: '어떤 작업을 할 때 어떤 증상이 나타나나요? 오류 문구가 있으면 함께 알려 주세요.', chips: ['접속할 때 인증 오류가 나요', '작업 중에 계속 끊겨요'] },
  onset: { ask: '언제부터 발생했나요? 정확히 모르면 모른다고 알려 주세요.', chips: ['오늘 오전부터요', '어제부터요', '방금부터요'] },
  businessImpact: {
    ask: '영향받는 인원과 업무 중단 정도를 알려 주세요. 쓸 수 있는 대체 방법이 있나요?',
    chips: ['저만 안 되고 메일 업무는 가능해요', '저만 안 되고 업무가 모두 중단됐어요', '팀원 여러 명이 같은 증상이에요'],
  },
  triedActions: { ask: '이미 시도한 조치가 있나요? 아직 없다면 그대로 알려 주세요.', chips: ['재접속과 재시작을 해봤어요', '아직 시도하지 않았어요'] },
}
const ORDER: IntakeKey[] = ['targetSystem', 'summary', 'onset', 'businessImpact', 'triedActions']

/* ------------------------------------------------------------------ Guide 요약 (guides 기준) */
export interface GuideEntry {
  /** 문서 코드와 제목 (예: IT-NET-001 VPN 접속 장애 대응 가이드) */
  guide: string
  version: string
  section: string
  steps: string[]
}
export const GUIDES: Record<CategoryCode, GuideEntry> = {
  NET: {
    guide: 'IT-NET-001 VPN 접속 장애 대응 가이드',
    version: 'v2',
    section: '3.1',
    steps: ['VPN 클라이언트를 최신 버전으로 업데이트하거나 다시 설치합니다.', 'PC를 재부팅한 뒤 VPN에 다시 연결합니다.', '공용 Wi-Fi라면 휴대폰 핫스팟에 연결해 다시 시도합니다.'],
  },
  ACC: {
    guide: 'IT-ACC-001 사내 SSO 로그인 오류 대응 가이드',
    version: 'v2',
    section: '3.2',
    steps: [
      '10분을 기다리면 잠금이 자동으로 풀립니다. 급하면 [지금 잠금 해제 (본인 인증)]를 누릅니다.',
      '비밀번호를 잊었다면 IT-ACC-002 3.4의 셀프 초기화를 합니다. 잠김도 함께 풀립니다.',
      '다시 잠기면 [자격 증명 관리자]의 예전 비밀번호 항목을 지우고 휴대폰 메일 앱·VPN·메신저의 저장 비밀번호도 바꿉니다. 비밀번호와 인증번호는 대화에 입력하지 마세요.',
    ],
  },
  SW: {
    guide: 'IT-SW-001 업무용 SW 설치 가이드',
    version: 'v2',
    section: '3.1',
    steps: [
      '사내 IT 포털에 사번으로 로그인해 [소프트웨어 센터]를 엽니다.',
      '프로그램 이름을 검색해 무료·회사 구매 프로그램은 [설치]를 누릅니다. 관리자 비밀번호는 필요 없습니다.',
      '[설치 요청]이 보이는 유료 프로그램은 IT-SW-002 3.1에 따라 라이선스를 신청합니다.',
    ],
  },
  HW: {
    guide: 'IT-HW-003 프린터·복합기 이용 가이드',
    version: 'v2',
    section: '3.1',
    steps: ['복합기 화면에 오류가 있는지 확인합니다.', 'PC [설정] > [프린터 및 스캐너]에서 인쇄 대기열을 열어 문서를 모두 취소합니다.', 'PC를 재부팅한 뒤 다시 인쇄합니다.'],
  },
  ACS: {
    guide: 'IT-ACS-001 사내 시스템 접근권한 신청 가이드',
    version: 'v2',
    section: '3.1',
    steps: ['그룹웨어에 로그인해 [IT 요청] > [권한 신청]을 엽니다.', '대상 시스템·메뉴(폴더 위치), 필요한 작업, 신청 이유와 사용 기간을 적고 팀장 승인을 요청합니다.'],
  },
  SYS: {
    guide: 'IT-SYS-001 그룹웨어·ERP 이용 오류 대응 가이드',
    version: 'v2',
    section: '3.1',
    steps: ['첨부파일을 붙인 문서에서 생기는 오류라면 파일 이름의 특수문자(#, %, & 등)를 지우거나 바꿉니다.', '파일을 다시 첨부하고 다시 시도합니다.', '오류 코드가 표시되면 기록해 둡니다.'],
  },
  // 정보보안 분류는 일반 Guide 안내 대신 긴급 흐름으로 가며, 안내가 필요할 때를 위해 시스템 가이드로 대신한다
  SEC: {
    guide: 'IT-SYS-001 그룹웨어·ERP 이용 오류 대응 가이드',
    version: 'v2',
    section: '3.1',
    steps: ['첨부파일을 붙인 문서에서 생기는 오류라면 파일 이름의 특수문자(#, %, & 등)를 지우거나 바꿉니다.', '파일을 다시 첨부하고 다시 시도합니다.', '오류 코드가 표시되면 기록해 둡니다.'],
  },
}

export const toSource = (g: GuideEntry): GuideSource => {
  const [docCode, ...rest] = g.guide.split(' ')
  return { docCode, title: rest.join(' '), version: g.version, section: g.section, excerpt: g.steps.join(' ') }
}

/** Guide 에 없는 증상을 보여 주기 위한 시연용 과거 처리 이력 (읽기 전용) */
const LEGACY_CASE: LegacyCase = {
  no: 'LEG-0132',
  title: '노트북 화면 깜빡임 (도입 이전 처리 이력)',
  symptom: '노트북 화면이 깜빡이고 켜지지 않음',
  solution: '디스플레이 케이블 재연결, 드라이버 재설치',
}

/** 시연용 담당 그룹 ID (support_groups.id) */
export const GROUP_ID: Record<string, number> = {
  서비스데스크: 1,
  엔드포인트지원팀: 2,
  네트워크팀: 3,
  시스템인프라팀: 4,
  업무시스템팀: 5,
  정보보안팀: 6,
}

/** 그룹 이름으로 groupId·groupName 짝을 만든다 */
export const groupOf = (groupName: string) => ({ groupId: GROUP_ID[groupName] ?? null, groupName })

/** 분류와 문장으로 세부 유형 코드·이름 짝을 만든다 (판단하지 못하면 둘 다 null) */
const typeOf = (cat: CategoryCode | null, text: string) => {
  const t = detectInquiryType(cat, text)
  return { inquiryTypeCode: t?.code ?? null, inquiryTypeName: t?.name ?? null }
}

/** 담당 그룹별 시연용 담당자 후보 (design 프로토타입의 담당자 이름 일부, id 는 users.id 자리) */
const STAFF_BY_GROUP: Record<string, { id: number; name: string }[]> = {
  서비스데스크: [
    { id: 101, name: '서댕댕' },
    { id: 102, name: '박고양' },
  ],
  엔드포인트지원팀: [
    { id: 201, name: '문오리' },
    { id: 202, name: '배두루' },
  ],
  네트워크팀: [
    { id: 2, name: '김담당' },
    { id: 302, name: '전다랑' },
  ],
  시스템인프라팀: [
    { id: 401, name: '구쿼카' },
    { id: 402, name: '어라마' },
  ],
  업무시스템팀: [
    { id: 501, name: '설해달' },
    { id: 502, name: '마수리' },
  ],
  정보보안팀: [
    { id: 601, name: '기곰이' },
    { id: 602, name: '반토끼' },
  ],
}

/* ------------------------------------------------------------------ 보조 함수 */
const p = (text: string, muted = false): ChatBlock => ({ type: 'p', text, muted: muted || undefined })

/** 대화 전체에서 문의자가 쓴 말과 수집한 정보를 하나의 문장으로 모은다 (분류·긴급도 판단용) */
function allText(rec: StoreRecord): string {
  const it = rec.internal.intake
  const users = rec.inquiry.messages.filter((m) => m.role === 'user').map((m) => m.text ?? '')
  const vals = [it.targetSystem, it.summary, it.onset, it.businessImpact, it.triedActions, it.extra].filter((v): v is string => typeof v === 'string')
  return users.join(' ') + ' ' + vals.join(' ')
}


/** 답변을 준비하는 동안 점 세 개를 보여 주고, 시간이 지나면 실제 답변으로 바꾼다 */
function typing(rec: StoreRecord, label: string, then: () => void) {
  const m = push(rec.inquiry, { role: 'assistant', typing: { label } })
  notify()
  later(mockConfig.typingMs, () => {
    rec.inquiry.messages = rec.inquiry.messages.filter((x) => x.id !== m.id)
    then()
    notify()
  })
}

/** 지금까지 달린 빠른 응답 버튼을 모두 잠근다 (한 번 응답하면 지난 버튼은 쓸 수 없다) */
function lockReplies(inq: Inquiry, keepId?: number) {
  inq.messages.forEach((m) => {
    if (m.replies && m.id !== keepId) m.locked = true
  })
}

/** 긴급 건을 접수 없이 끝낼 때 보여 주는 행동 안내 */
const URGENT_GUIDE = '긴급 징후가 있었어요. 의심스러운 링크·첨부파일은 더 열지 마시고, 계정 정보는 어디에도 입력하지 마세요. 문제가 계속되면 IT 헬프데스크 내선 1000으로 연락해 주세요.'

const yesNo = (): { replies: ChatReply[] } => ({
  replies: [
    { label: '해결', action: 'resolved', primary: true },
    { label: '미해결', action: 'unresolved' },
  ],
})

const connectReplies = (): ChatReply[] => [
  { label: '담당자 연결', action: 'connect-yes', primary: true },
  { label: '미연결 (종료)', action: 'connect-no' },
]

/* ------------------------------------------------------------------ 정보 수집 */
function absorb(rec: StoreRecord, text: string, initial: boolean) {
  const it = rec.internal.intake
  const cat = rec.inquiry.categoryCode
  if (!it.targetSystem && cat && cat !== 'SEC') it.targetSystem = CATEGORIES[cat].targetSystem
  // 문장 단위로 나눠 각 항목에 해당하는 말을 찾는다
  const parts = text
    .split(/(?<=[.!?。])\s+|(?<=요)\s+(?=[가-힣])/)
    .map((x) => x.trim())
    .filter(Boolean)
  parts.forEach((s, n) => {
    if (!it.summary && n === 0 && s.length >= 6 && /(오류|실패|잠|불가|안 ?돼|안 ?되|끊|멈|느려|중단|못|없어|필요|실행|화면|설치|인쇄|접속|신청|눌렀)/.test(s)) it.summary = s
    if (!it.onset && /(오늘|어제|방금|오전|오후|부터|\d+\s*시|\d+\s*분\s*전|그제)/.test(s)) it.onset = s
    if (!it.businessImpact && /(저만|본인|팀원|전체|여러|\d+\s*명|업무.{0,6}(가능|불가|중단|어려)|대체)/.test(s)) it.businessImpact = s
    if (!it.triedActions && /(재시작|재접속|재부팅|해봤|해 봤|시도.{0,4}(없|안)|아직.{0,4}(안|않))/.test(s)) it.triedActions = s
  })
  // 방금 물어본 항목에 대한 답이면 그대로 받아 둔다
  const pending = rec.internal.pending
  if (!initial && pending && !it[pending] && text.trim().length >= 2) it[pending] = text
}

const missing = (rec: StoreRecord) => ORDER.filter((k) => !rec.internal.intake[k])

function askNext(rec: StoreRecord) {
  const miss = missing(rec)
  if (!miss.length) {
    doAnswer(rec)
    return
  }
  const k = miss[0]
  const { inquiry, internal } = rec
  internal.pending = k
  inquiry.step = 'collect'
  const chips = k === 'targetSystem' && inquiry.categoryCode ? [CATEGORIES[inquiry.categoryCode].targetSystem] : QUESTIONS[k].chips
  const blocks: ChatBlock[] = []
  if (!internal.intake.asked) blocks.push(p('정확히 안내해 드리려고 몇 가지만 확인할게요.'))
  blocks.push(p(QUESTIONS[k].ask))
  push(inquiry, { role: 'assistant', blocks, replies: chips.map((c) => ({ label: c, action: 'quick', arg: c })) })
  internal.intake.asked = true
}

/** 긴급 징후(보안 사고 의심, 여러 사용자의 업무 중단)는 일반 검색을 기다리지 않고 담당자 연결부터 제안한다 */
function urgentFlow(rec: StoreRecord) {
  const { inquiry, internal } = rec
  inquiry.step = 'offer'
  inquiry.categoryCode = inquiry.categoryCode ?? 'SEC'
  internal.urgent = true
  const pr = calcUrgency(allText(rec))
  const sec = RE.sec.test(allText(rec))
  const blocks: ChatBlock[] = [p('**긴급 대응이 필요한 징후**가 확인되었어요. 일반 검색과 답변을 기다리지 않고 담당자 연결을 먼저 제안해요.')]
  if (sec) blocks.push(p('의심스러운 링크·첨부파일은 더 열지 마시고, 계정 정보는 어디에도 입력하지 마세요.'))
  blocks.push({ type: 'urgent', groupName: CATEGORIES[inquiry.categoryCode].groupName, urgency: pr.urgency, urgencyReasons: pr.urgencyReasons })
  blocks.push(p('실제 사고 여부와 필요한 조치는 담당자가 확인해요. 연결하면 현재 확인된 내용으로 초안을 만들고, 확인하신 뒤에만 접수돼요.', true))
  push(inquiry, { role: 'assistant', blocks, replies: connectReplies() })
}

/** 근거 검색과 안내. 순서는 Guide 우선 → 부족하면 과거 이력 → 둘 다 없으면 지원 범위 밖 (PRD 4.4) */
function doAnswer(rec: StoreRecord) {
  const { inquiry, internal } = rec
  inquiry.step = 'answering'
  const text = allText(rec)
  typing(rec, '근거를 찾고 있어요', () => {
    // 외부 모델로 보낼 수 없는 문서와 관련된 질의는 AI 가 답하지 않는다
    if (RE.rest.test(text)) {
      inquiry.step = 'offer'
      push(inquiry, {
        role: 'assistant',
        blocks: [p('관련 가이드를 찾았지만 **외부 모델로 전송할 수 없는 문서**라서 이 문의는 AI가 안내할 수 없어요. 열람 권한과 외부 전송 허용은 따로 확인하고 있어요.'), p('담당자에게 연결해 드릴 수 있어요.')],
        replies: connectReplies(),
      })
      return
    }
    const cat = inquiry.categoryCode
    if (!cat) {
      inquiry.step = 'offer'
      push(inquiry, {
        role: 'assistant',
        blocks: [
          p('이 문의는 지원하는 7개 분류로 확정하기 어려워 **지원 범위 밖**으로 보여요. Guide와 과거 처리 이력 모두에서 답에 쓸 만한 근거를 찾지 못했어요. 근거 없이 임의로 안내하지 않을게요.'),
          p('서비스데스크에서 확인할 수 있도록 담당자 연결을 제안해요.'),
        ],
        replies: connectReplies(),
      })
      return
    }
    const guide = GUIDES[cat]
    // 시연: HW 분류에서 프린터·복합기 외 증상은 Guide 에 없다고 보고 과거 이력을 확인한다
    const guideHit = !(cat === 'HW' && !/(프린터|복합기|인쇄)/.test(text))
    if (!guideHit) {
      inquiry.step = 'answered'
      push(inquiry, {
        role: 'assistant',
        blocks: [
          p('**Guide에서는 정확한 안내를 찾지 못해** 도입 이전 처리 이력을 확인했어요. 비슷한 사례에서는 아래 방법으로 해결됐어요.'),
          { type: 'ol', items: ['모니터·도킹스테이션 케이블을 다시 연결합니다.', '디스플레이 드라이버를 다시 설치합니다.'] },
          p('**과거 처리 사례 참고** · 현재 Guide·정책과 다를 수 있어요. 해결되지 않으면 담당자에게 연결해 드려요.', true),
          p('이 방법으로 해결되었나요?'),
        ],
        legacy: LEGACY_CASE,
        ...yesNo(),
      })
      return
    }
    internal.guideLabel = `${guide.guide} ${guide.version}`
    if (cat === 'ACS') {
      // 권한은 AI 가 부여하지 않는다. 신청 절차만 안내한다
      inquiry.step = 'offer'
      push(inquiry, {
        role: 'assistant',
        blocks: [
          p('접근권한은 아래 절차로 신청해요.'),
          { type: 'ol', items: guide.steps },
          p('권한을 실제로 부여하거나 바꾸는 일은 담당자와 승인자의 업무라서 AI가 대신할 수 없어요. ITssue 접수가 승인 절차를 대신하지도 않아요.'),
        ],
        sources: [toSource(guide)],
        replies: [
          { label: '신청 방법을 확인했어요', action: 'resolved', primary: true },
          { label: '담당자 연결', action: 'connect-yes' },
        ],
      })
      return
    }
    inquiry.step = 'answered'
    push(inquiry, {
      role: 'assistant',
      blocks: [p(`확인한 내용을 보면 **${CATEGORIES[cat].name}** 문의로 보여요. 먼저 아래 순서로 해 보세요.`), { type: 'ol', items: guide.steps }, p('이 방법으로 해결되었나요?')],
      sources: [toSource(guide)],
      ...yesNo(),
    })
  })
}

/* ------------------------------------------------------------------ 대화 진입점 */
/** 새 문의를 만들고 첫 메시지를 처리한다 */
export function startInquiry(owner: string, ownerName: string, text: string): Inquiry {
  // 제목에도 비밀번호·인증번호 원문이 남지 않게 먼저 가린다
  const safe = maskSensitive(text).text
  const title = safe.length > 22 ? `${safe.slice(0, 22)}…` : safe
  const rec = createRecord(owner, ownerName, title)
  handle(rec, text, true)
  return rec.inquiry
}

/** 문의자가 메시지를 보낸다. 접수 이후라면 담당자에게 가는 추가 메시지가 된다. */
export function handle(rec: StoreRecord, raw: string, initial: boolean) {
  const { inquiry, internal } = rec
  inquiry.idleWarned = null // 문의자가 글을 보내면 삭제 안내 띠를 거둔다
  inquiry.paused = false
  // 비밀번호·인증번호로 보이는 값은 대화·초안·로그에 넣기 전에 가린다
  const masked = maskSensitive(raw)
  const text = masked.text
  push(inquiry, { role: 'user', text })
  inquiry.updatedAt = nowIso()
  if (masked.hit || hasMask(text)) {
    internal.sens = true
    push(inquiry, { role: 'sys', text: MASK_NOTICE })
  }

  if (inquiry.step === 'draft') {
    push(inquiry, { role: 'assistant', blocks: [p('초안의 내용을 바꾸려면 아래 초안에서 **수정**을 눌러 고쳐 주세요. 변경 내용은 접수 전에 다시 확인해 드려요.')] })
    return
  }
  if (inquiry.step === 'offer' || inquiry.step === 'answered') {
    internal.intake.extra = (internal.intake.extra ? internal.intake.extra + ' ' : '') + text
    absorb(rec, text, false)
    lockReplies(inquiry)
    push(inquiry, {
      role: 'assistant',
      blocks: [p('추가 내용을 기록했어요. 해결되지 않았다면 담당자 연결을 도와드릴게요.')],
      replies: connectReplies(),
    })
    return
  }
  // 수집 단계: 분류와 정보를 갱신하고, 긴급 징후가 있으면 바로 연결을 제안한다
  const c = detectCategory(text)
  if (c && !inquiry.categoryCode) inquiry.categoryCode = c
  if (RE.sec.test(text) && inquiry.categoryCode !== 'SEC') inquiry.categoryCode = 'SEC'
  absorb(rec, text, initial)
  internal.pending = null
  lockReplies(inquiry)
  const all = allText(rec)
  if (RE.sec.test(all) || (RE.multi.test(all) && RE.stop.test(all))) {
    urgentFlow(rec)
    return
  }
  askNext(rec)
}

/** 빠른 응답 버튼 */
export function applyReply(rec: StoreRecord, req: ReplyRequest) {
  rec.inquiry.idleWarned = null
  rec.inquiry.paused = false
  const { inquiry } = rec
  const msg = inquiry.messages.find((m) => m.id === req.messageId)
  if (!msg?.replies || msg.locked) return // 이미 응답했거나 지난 단계의 버튼
  lockReplies(inquiry)
  msg.locked = true
  switch (req.action) {
    case 'noop':
      return
    case 'quick':
      handle(rec, req.arg ?? '', false)
      return
    case 'resolved':
      push(inquiry, { role: 'user', text: '해결' })
      inquiry.status = 'AI_RESOLVED'
      inquiry.step = 'closed'
      push(inquiry, { role: 'assistant', blocks: [p('다행이에요! 이 문의는 **AI 해결**로 기록했어요. 다른 문제가 생기면 새 문의를 시작해 주세요.')] })
      return
    case 'unresolved': {
      push(inquiry, { role: 'user', text: '미해결' })
      inquiry.step = 'offer'
      const group = CATEGORIES[inquiry.categoryCode ?? 'ACC'].groupName
      push(inquiry, {
        role: 'assistant',
        blocks: [p(`담당자 확인이 필요해 보여요. **${group}**에 연결할까요?`), p('연결하면 지금까지의 문의와 시도한 조치를 정리한 **접수 초안**을 먼저 보여드려요. 초안을 확인하기 전에는 접수되지 않아요.')],
        replies: connectReplies(),
      })
      return
    }
    case 'connect-no':
      push(inquiry, { role: 'user', text: '미연결 (종료)' })
      inquiry.status = 'CLOSED_UNRESOLVED'
      inquiry.step = 'closed'
      push(inquiry, { role: 'assistant', blocks: [p('담당자 연결 없이 상담을 종료했어요. 이 문의는 **미해결 종료**로 남고, 해결된 것으로 기록하지 않아요. 문의 내역에서 언제든 다시 열 수 있어요.'), ...(rec.internal.urgent ? [p(URGENT_GUIDE)] : [])] })
      return
    case 'connect-yes':
      push(inquiry, { role: 'user', text: '담당자 연결' })
      buildDraft(rec)
      return
  }
}

/* ------------------------------------------------------------------ 접수 초안 · 접수 */
function buildDraft(rec: StoreRecord) {
  const { inquiry, internal } = rec
  const pr = calcUrgency(allText(rec))
  const cat = inquiry.categoryCode
  const it = internal.intake
  inquiry.draft = {
    title: `${cat ? CATEGORIES[cat].targetSystem : 'IT'} 지원 문의`,
    categoryCode: cat,
    targetSystem: it.targetSystem ?? (cat ? CATEGORIES[cat].targetSystem : '확인 필요'),
    summary: it.summary ?? inquiry.messages.find((m) => m.role === 'user')?.text ?? '',
    occurredAt: it.onset ?? '확인 필요',
    businessImpact: it.businessImpact ?? (internal.urgent ? '긴급 징후 확인 · 추가 확인은 담당자가 진행' : '확인 필요'),
    triedActions: it.triedActions ?? '확인 필요',
    aiSummary: internal.guideLabel ? `${internal.guideLabel} 안내 후에도 해결되지 않음` : internal.urgent ? '긴급 징후로 안내 없이 연결' : 'AI 안내 없음',
    urgency: pr.urgency,
    urgencyReasons: pr.urgencyReasons,
    ...groupOf(cat ? CATEGORIES[cat].groupName : FALLBACK_GROUP),
    ...typeOf(cat, allText(rec)),
  }
  inquiry.step = 'draft'
  inquiry.draftState = 'view'
  inquiry.draftNote = ''
  push(inquiry, { role: 'assistant', blocks: [p('지금까지 확인한 내용을 정리했어요. 맞는지 확인하고, 필요하면 수정해 주세요.')], card: 'draft' })
}

/** 초안을 고치면 분류·긴급도를 다시 판단하고 그 결과를 알린다 */
export function saveDraft(rec: StoreRecord, edit: DraftEdit) {
  const { inquiry, internal } = rec
  const d = inquiry.draft
  if (!d || inquiry.draftState !== 'view' || inquiry.step !== 'draft') return
  const beforeP = d.urgency
  const beforeCat = d.categoryCode
  const beforeType = d.inquiryTypeCode ?? null
  const beforeGroup = d.groupName
  // 고친 글에 비밀번호·인증번호가 있으면 저장하기 전에 가린다
  const clean = (v: string | undefined) => (v ?? '').trim() && maskSensitive((v ?? '').trim()).text
  d.summary = clean(edit.summary) || d.summary
  d.occurredAt = clean(edit.occurredAt) || d.occurredAt
  d.businessImpact = clean(edit.businessImpact) || d.businessImpact
  d.triedActions = clean(edit.triedActions) || d.triedActions
  const txt = `${d.summary} ${d.occurredAt} ${d.businessImpact} ${d.triedActions}`
  const c = detectCategory(txt)
  if (c && c !== d.categoryCode && RE.sec.test(txt)) {
    d.categoryCode = c
    Object.assign(d, groupOf(CATEGORIES[c].groupName))
  }
  const pr = calcUrgency(`${txt} ${internal.urgent ? '의심' : ''} ${allText(rec)}`)
  d.urgency = pr.urgency
  d.urgencyReasons = pr.urgencyReasons
  Object.assign(d, typeOf(d.categoryCode, `${txt} ${allText(rec)}`))
  // 값이 바뀐 항목만 기록해 화면이 "다시 판단됨"을 붙이게 한다
  const rejudged: RejudgedField[] = []
  if (d.categoryCode !== beforeCat) rejudged.push('category')
  if ((d.inquiryTypeCode ?? null) !== beforeType) rejudged.push('inquiryType')
  if (d.urgency !== beforeP) rejudged.push('urgency')
  if (d.groupName !== beforeGroup) rejudged.push('group')
  d.rejudged = rejudged
  const changed = beforeP !== d.urgency || beforeCat !== d.categoryCode
  inquiry.draftNote = changed
    ? `수정한 내용을 반영해 ${beforeP !== d.urgency ? `긴급도를 ${beforeP}에서 ${d.urgency}(으)로` : ''}${beforeCat !== d.categoryCode ? ` 분류를 ${d.categoryCode ?? ''}(으)로` : ''} 다시 판단했어요. 변경된 내용으로 다시 확인해 주세요.`
    : '수정 내용을 반영했어요. 최종 접수 전에 한 번 더 확인해 주세요.'
}

/** 접수하지 않고 종료한다 */
export function cancelDraft(rec: StoreRecord) {
  const { inquiry } = rec
  if (inquiry.step !== 'draft') return
  push(inquiry, { role: 'user', text: '미접수 (종료)' })
  inquiry.status = 'CLOSED_UNRESOLVED'
  inquiry.step = 'closed'
  inquiry.draftState = 'cancel'
  push(inquiry, { role: 'sys', text: '접수하지 않고 종료했어요' })
  // 긴급 건을 접수 없이 끝내면 행동 안내를 함께 보여 준다 (docs/09 3.4). 보안 신호 기록은 서버가 한다.
  if (rec.internal.urgent) push(inquiry, { role: 'assistant', blocks: [p(URGENT_GUIDE)] })
}

/** 초안을 확인했으니 접수한다. 저장에 실패하면 접수 완료로 안내하지 않는다. */
export function confirmDraft(rec: StoreRecord) {
  const { inquiry } = rec
  const d = inquiry.draft
  if (!d || inquiry.step !== 'draft' || inquiry.draftState !== 'view') return
  if (mockConfig.saveFail) {
    push(inquiry, { role: 'sys', text: '접수 저장 실패' })
    push(inquiry, { role: 'assistant', blocks: [p('접수를 완료하지 못했어요.')], card: 'savefail' })
    return
  }
  inquiry.draftState = 'confirmed'
  push(inquiry, { role: 'user', text: '접수' })
  const t: Ticket = {
    receiptNo: nextRcpt(),
    jiraKey: null,
    title: d.title,
    categoryCode: d.categoryCode,
    urgency: d.urgency,
    groupId: d.groupId,
    groupName: d.groupName,
    assigneeId: null,
    assigneeName: null,
    workStatus: null,
    assignStatus: 'PENDING',
    jiraSyncStatus: 'PENDING',
    createdAt: nowIso(),
    resolutionNote: '',
    needReply: false,
  }
  inquiry.ticket = t
  inquiry.status = 'RECEIVED'
  inquiry.step = 'submitted'
  push(inquiry, {
    role: 'assistant',
    blocks: [p(`접수되었어요. 접수번호는 **${t.receiptNo}** 입니다. 담당자 연결을 진행하고 있어요. 진행 상황은 아래 카드에서 바로 볼 수 있어요.`)],
    card: 'ticket',
  })
  runPipeline(rec)
}

/* ------------------------------------------------------------------ 접수 이후 진행 (시연용 타이머) */
const wait = (ms: number) => ms * mockConfig.pipelineScale

/**
 * Jira Ticket 생성(업무 상태 RDY) → 담당자 배정(배정 상태 ASSIGNED) → (자동 진행이 켜져 있으면) 처리 시작 → 처리 결과 등록.
 * 업무 상태는 Jira 생성 직후 RDY 가 되고, 배정 여부는 배정 상태가 따로 나타낸다. (docs/07.API_계약서.md 상태 전환)
 */
function runPipeline(rec: StoreRecord) {
  const t = rec.inquiry.ticket
  if (!t) return
  later(wait(1000), () => {
    t.jiraKey = nextIts()
    t.jiraSyncStatus = 'SYNCED'
    t.workStatus = 'RDY'
    notify()
    later(wait(1000), () => {
      assign(rec)
      notify()
      if (mockConfig.autoRun) {
        later(wait(2600), () => {
          if (t.workStatus !== 'RDY') return
          setStatus(rec, 'WIP')
          notify()
          later(wait(3200), () => {
            if (t.workStatus !== 'WIP') return
            registerResult(rec)
            notify()
          })
        })
      }
    })
  })
}

/** 담당 그룹의 후보 중 한 명을 배정한다 */
function assign(rec: StoreRecord) {
  const { inquiry } = rec
  const t = inquiry.ticket
  if (!t) return
  const cand = STAFF_BY_GROUP[t.groupName] ?? STAFF_BY_GROUP[FALLBACK_GROUP]
  t.assigneeId = cand[0].id
  t.assigneeName = cand[0].name
  t.assignStatus = 'ASSIGNED'
  inquiry.status = 'HANDED_OFF'
  inquiry.updatedAt = nowIso()
}

/** 상태를 바꾸고, 문의자가 이 문의를 보고 있지 않다면 새 답변 표시를 올린다 */
function setStatus(rec: StoreRecord, status: Ticket['workStatus']) {
  const t = rec.inquiry.ticket
  if (!t) return
  t.workStatus = status
  if (status === 'FIN') t.finishedAt = nowIso()
  rec.inquiry.updatedAt = nowIso()
  if (status === 'WIP' || status === 'FIN') rec.inquiry.unread += 1
}

function registerResult(rec: StoreRecord) {
  const t = rec.inquiry.ticket
  if (!t) return
  t.resolutionNote = t.categoryCode === 'NET' ? '인증 정보를 재동기화했습니다. VPN Client를 다시 실행하고 접속해 주세요.' : '원인을 확인하고 조치를 완료했습니다. 같은 작업을 다시 진행해 주세요.'
  setStatus(rec, 'FIN')
}

/** 시연: 담당자 처리를 한 단계 앞으로 진행한다 (RDY → WIP → FIN) */
export function advanceTicket(rec: StoreRecord) {
  const t = rec.inquiry.ticket
  if (!t?.workStatus || t.assignStatus !== 'ASSIGNED') return
  if (t.workStatus === 'RDY') setStatus(rec, 'WIP')
  else if (t.workStatus === 'WIP') registerResult(rec)
}

/** 문의자가 "해결"을 눌러 Ticket 을 종료한다 */
export function confirmResolved(rec: StoreRecord) {
  const t = rec.inquiry.ticket
  if (!t || t.workStatus !== 'FIN') return
  t.workStatus = 'CLS'
  t.closedAt = nowIso()
  rec.inquiry.status = 'HANDED_OFF'
  rec.inquiry.updatedAt = nowIso()
}

/** 문의자가 "미해결"과 남은 증상을 보내면 담당자가 다시 확인한다 */
export function denyResolved(rec: StoreRecord, reason: string) {
  const { inquiry } = rec
  const t = inquiry.ticket
  if (!t || t.workStatus !== 'FIN' || !reason.trim()) return
  // 지난 진행 카드는 그대로 남기고, 새 진행 카드를 아래에 붙인다
  const old = [...inquiry.messages].reverse().find((m) => m.card === 'ticket' && !m.ticketSnapshot)
  if (old) old.ticketSnapshot = { ...t }
  push(inquiry, { role: 'user', text: reason.trim(), kind: '미해결 사유' })
  t.workStatus = 'WIP'
  t.finishedAt = null
  t.resolutionNote = ''
  inquiry.updatedAt = nowIso()
  push(inquiry, { role: 'assistant', blocks: [p('다시 확인을 요청했어요. 담당자가 재확인하고 있어요. 아래 카드에서 새 진행 상황을 볼 수 있어요.')], card: 'ticket' })
}

/** 접수 이후 문의자가 남긴 추가 메시지: 담당자에게 전달된다 */
export function sendToStaff(rec: StoreRecord, text: string) {
  push(rec.inquiry, { role: 'user', text: maskSensitive(text).text, kind: '추가 메시지' })
  rec.inquiry.updatedAt = nowIso()
}

/**
 * 응답 없음 (docs/09 6.4, 2026-10-22 팀 결정). 시연에서는 시간을 기다리지 않고 단계별로 보여 준다.
 * 해결 확인(답변 뒤)은 5시간, 질문·연결 제안·초안은 2시간 뒤 한 번 안내하고, 안내 뒤에 대화를 삭제한다.
 * 접수된 건과 끝난 문의에는 쓰지 않는다. 시간·안내 시점은 서버의 환경값이다.
 */
function idleKind(inquiry: Inquiry): IdleKind | null {
  if (inquiry.ticket || inquiry.step === 'closed' || inquiry.step === 'submitted') return null
  return inquiry.step === 'answered' ? 'h5' : 'h2'
}

/** 삭제 안내를 한 번 보낸다. 입력창 위 띠로도 보여 준다. (실제로는 서버가 보내는 시스템 메시지) */
export function idleWarnInquiry(rec: StoreRecord) {
  const { inquiry } = rec
  const kind = idleKind(inquiry)
  if (!kind || inquiry.idleWarned) return
  inquiry.idleWarned = kind
  push(inquiry, { role: 'sys', text: IDLE_TEXT[kind] })
}

/** 안내 뒤 대화를 삭제한다. 보안·로그 대상(긴급·민감정보 입력)은 지우지 않고 문의자 화면에서만 숨긴다. */
export function idleDeleteInquiry(rec: StoreRecord) {
  const { inquiry, internal } = rec
  if (!idleKind(inquiry)) return
  if (internal.urgent || internal.sens) internal.hidden = true
  else removeRecord(inquiry.id)
}

/** 삭제 전에 돌아온 상태. 입력창을 잠그고 이어서 할지 새로 시작할지 고르게 한다. */
export function idleBackInquiry(rec: StoreRecord) {
  const { inquiry } = rec
  if (!idleKind(inquiry)) return
  inquiry.paused = true
}

/** "이어서 채팅하기": 같은 대화·같은 단계로 계속한다 */
export function resumeInquiry(rec: StoreRecord) {
  const { inquiry } = rec
  if (!inquiry.paused) return
  inquiry.paused = false
  inquiry.idleWarned = null
  push(inquiry, { role: 'sys', text: '같은 대화에서 이어서 진행해요.' })
}

/** 종료된 상담을 다시 연다 */
export function reopenInquiry(rec: StoreRecord) {
  const { inquiry } = rec
  if (inquiry.step !== 'closed') return
  inquiry.status = 'IN_PROGRESS'
  inquiry.step = 'offer'
  inquiry.draftState = 'view'
  lockReplies(inquiry)
  push(inquiry, {
    role: 'assistant',
    blocks: [p('상담을 다시 열었어요. 해결되지 않았다면 담당자 연결을 도와드릴게요.')],
    replies: connectReplies(),
  })
}
