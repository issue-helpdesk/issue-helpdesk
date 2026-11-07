/**
 * 해결 사례 → 가이드 초안 (관리자 가이드 관리의 두 번째 탭) 시연 데이터와 모의 상태 전환.
 * 서버에는 아직 이 기능이 없다(docs/api/06 R-23). 화면·버튼·상태 전환만 모의로 보여 주고, 서버 연결 없이 이 파일 안에서 바뀐다.
 *
 * 흐름: 주 1회 AI가 아직 가이드에 반영하지 않은 해결 사례를 분석해 비슷한 사례를 묶어 제안한다 → 관리자가 검토·수정하고
 * 열람 범위·외부 AI 전송 정책을 골라 승인하면 "현행이 아닌 초안 버전"으로 등록되고 검색 준비가 시작된다 →
 * 검색 준비가 끝나면 관리자가 따로 현행으로 바꾼다 (자동 현행 전환은 없다).
 * 화면에 보이는 상태 이름은 표시용이며 서버 상태값이 아니다.
 */
import type { CategoryCode } from '../chatTypes'
import type { GuideScope, GuideTx } from '../guides'

export type CaseKind = 'amend' | 'new'
export type CaseState = 'review' | 'preparing' | 'failed' | 'ready' | 'live' | 'dropped'

export const CASE_KIND_LABEL: Record<CaseKind, string> = { amend: '기존 가이드 보강', new: '신규 가이드' }
export const CASE_STATE_LABEL: Record<CaseState, string> = {
  review: '검토 중',
  preparing: '검색 준비 중',
  failed: '검색 준비 실패',
  ready: '검색 준비 완료',
  live: '현행',
  dropped: '가이드화 안 함',
}
/** 상태 배지 색 (StateBadge 의 tone) */
export const CASE_STATE_TONE: Record<CaseState, string> = { review: 'need', preparing: 'warn', failed: 'urg', ready: 'ok', live: 'info', dropped: 'recv' }

export interface CaseTicket {
  no: string
  summary: string
  /** 담당자가 적은 최종 처리 결과 */
  result: string
}

export interface CaseItem {
  id: string
  cat: CategoryCode
  topic: string
  kind: CaseKind
  state: CaseState
  tickets: CaseTicket[]
  /** 기존 가이드 보강일 때: 대상 문서와 AI가 초안을 만든 기준 버전, 반영할 위치 */
  target?: { docCode: string; title: string; baseVersion: string; latestVersion: string; section: string }
  /** 기존 가이드 보강일 때: 반영 위치의 기존 내용 */
  before?: string
  /** 기존 가이드 보강일 때: 추가·수정할 항목 한 줄 요약 */
  change?: string
  /** AI 제안문(수정·추가할 내용) 또는 신규 가이드 본문. 관리자가 편집한다 */
  after: string
  /** 신규 가이드일 때 제목 */
  title?: string
  /** 기준 버전이 바뀌었을 때 최신 가이드 내용과 그에 맞춘 제안문 (시연용) */
  latest?: { before: string; after: string }
  /** AI가 이렇게 판단한 이유와 확인할 경고 */
  reason: string
  warnings: string[]
  scope: GuideScope
  tx: GuideTx
  /** 승인·등록한 문서와 버전 */
  registered?: { docCode: string; version: string }
  failReason?: string
  dropReason?: string
  /** 마지막으로 임시 저장한 시각 */
  savedAt?: string
}

const t = (no: string, summary: string, result: string): CaseTicket => ({ no, summary, result })

function seed(): CaseItem[] {
  return [
    {
      id: 'c1',
      cat: 'NET',
      topic: '재택 VPN 연결 후 인터넷이 끊김 (공유기 설정)',
      kind: 'amend',
      state: 'review',
      tickets: [
        t('RCPT-0101', '집에서 VPN을 켜면 인터넷이 끊겨요', '공유기의 VPN 패스스루를 켜니 정상 연결됨'),
        t('RCPT-0115', '재택 VPN 접속 후 웹페이지가 안 열려요', '공유기 VPN 패스스루 설정 변경 후 해결'),
        t('RCPT-0122', 'VPN 연결하면 인터넷이 먹통이에요', '패스스루를 켜고 공유기 펌웨어도 함께 업데이트'),
        t('RCPT-0127', '자택에서 VPN만 쓰면 외부 사이트가 안 돼요', 'VPN 패스스루 설정을 켜서 해결'),
        t('RCPT-0133', '재택 중 VPN 후 인터넷 끊김', '공유기 패스스루 설정 변경'),
        t('RCPT-0140', 'VPN 켜면 인터넷이 안 됩니다', '패스스루 설정 확인 후 켬, 정상'),
        t('RCPT-0146', '집 공유기 때문인지 VPN이 이상해요', '패스스루 설정 변경으로 해결'),
      ],
      target: { docCode: 'IT-NET-001', title: 'VPN 접속 장애 대응 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.3 집에서 VPN이 자주 끊김' },
      change: '3번 조치 추가: 공유기 VPN 패스스루 설정 확인',
      before: '1. VPN 앱을 완전히 종료한 뒤 다시 실행합니다.\n2. 같은 증상이 계속되면 PC를 재시작한 뒤 다시 연결합니다.',
      after:
        '1. VPN 앱을 완전히 종료한 뒤 다시 실행합니다.\n2. 같은 증상이 계속되면 PC를 재시작한 뒤 다시 연결합니다.\n3. VPN을 연결하면 인터넷이 끊기는 경우에는 담당자가 공유기의 VPN 패스스루 설정을 확인합니다. 공유기 설정은 담당자 안내에 따라 변경해 주세요.\n\n해결 확인: VPN을 연결한 뒤에도 인터넷 페이지가 열리면 해결된 것입니다.',
      reason: '현행 3.3 항목은 앱 재실행과 PC 재시작만 다루고, 공유기 설정은 없어요. 같은 해결 방법이 7건에서 반복돼 기존 항목에 추가하도록 제안했어요.',
      warnings: ['RCPT-0122는 펌웨어 업데이트도 함께 진행했어요. 제안문에는 넣지 않았어요.', '원인은 처리 결과로 추정한 내용이라 담당자 확인이 필요해요.'],
      scope: '전 직원',
      tx: '허용',
    },
    {
      id: 'c2',
      cat: 'SYS',
      topic: '사내 메신저 알림이 오지 않음',
      kind: 'new',
      state: 'review',
      tickets: [
        t('RCPT-0201', '사내 메신저 알림이 안 와요', '알림 설정에서 방해 금지 시간대를 해제해 해결'),
        t('RCPT-0208', '메신저 메시지가 늦게 보여요', '방해 금지 모드가 켜져 있어서 해제'),
        t('RCPT-0213', '메신저 알림음이 안 울려요', '앱 알림 권한을 허용으로 변경'),
        t('RCPT-0219', '메신저에서 멘션 알림이 없어요', '알림 설정 > 멘션 알림을 켬'),
        t('RCPT-0226', '메신저 알림이 가끔만 와요', '방해 금지 시간대 해제 후 정상'),
      ],
      title: '사내 메신저 알림이 오지 않을 때',
      after:
        '#### 이런 경우\n\n- 사내 메신저의 새 메시지·멘션 알림이 오지 않습니다.\n\n#### 조치 방법\n\n1. 메신저 설정에서 방해 금지 시간대가 켜져 있으면 해제합니다.\n2. 기기의 앱 알림 권한이 허용인지 확인합니다.\n3. 설정의 멘션 알림이 켜져 있는지 확인합니다.\n\n**해결 확인**\n\n- 다른 사람이 보낸 메시지의 알림이 바로 오면 해결된 것입니다.\n\n**해결되지 않으면**\n\n- ITssue 챗봇에 알려 주세요.',
      reason: '같은 분류의 현행 가이드에 메신저 알림 항목이 없어서 새 가이드로 제안했어요. 원인 칸은 근거가 부족해 비웠어요.',
      warnings: ['담당자만 할 수 있는 조치가 섞여 있지 않은지 확인해 주세요.'],
      scope: '전 직원',
      tx: '허용',
    },
    {
      id: 'c3',
      cat: 'ACC',
      topic: '계정 잠금 해제 뒤에도 SSO 재로그인이 안 됨',
      kind: 'amend',
      state: 'review',
      tickets: [
        t('RCPT-0301', '계정 잠금 풀었는데 SSO가 계속 실패해요', '브라우저 쿠키 삭제 후 다시 로그인'),
        t('RCPT-0309', '잠금 해제 후에도 로그인 오류가 나요', '저장된 세션을 지우고 재로그인'),
        t('RCPT-0317', '잠금 풀렸다는데 SSO 로그인 안 됨', '쿠키와 캐시 삭제 후 정상'),
        t('RCPT-0324', '계정 잠금 해제 직후 로그인 실패', '브라우저를 완전히 종료하고 다시 접속'),
      ],
      target: { docCode: 'IT-ACC-001', title: '사내 SSO 로그인 오류 대응 가이드', baseVersion: 'v1', latestVersion: 'v2', section: '3.2 비밀번호를 바꾼 뒤 계정이 잠김' },
      change: '3번 조치 추가: 쿠키·저장된 세션 삭제 후 재접속',
      before: '1. 비밀번호를 바꾼 뒤에는 휴대폰 메일 앱의 저장된 비밀번호를 먼저 바꿉니다.\n2. 잠금이 풀리면 다시 로그인합니다.',
      after:
        '1. 비밀번호를 바꾼 뒤에는 휴대폰 메일 앱의 저장된 비밀번호를 먼저 바꿉니다.\n2. 잠금이 풀리면 다시 로그인합니다.\n3. 잠금을 풀었는데도 로그인이 안 되면 브라우저의 쿠키와 저장된 세션을 지운 뒤 다시 접속합니다.',
      latest: {
        before: '1. 비밀번호를 바꾼 뒤에는 휴대폰 메일 앱과 PC 자격 증명 관리자의 저장된 비밀번호를 먼저 바꿉니다.\n2. 잠금이 풀리면 브라우저를 완전히 종료한 뒤 다시 로그인합니다.',
        after:
          '1. 비밀번호를 바꾼 뒤에는 휴대폰 메일 앱과 PC 자격 증명 관리자의 저장된 비밀번호를 먼저 바꿉니다.\n2. 잠금이 풀리면 브라우저를 완전히 종료한 뒤 다시 로그인합니다.\n3. 그래도 로그인이 안 되면 브라우저의 쿠키와 저장된 세션을 지운 뒤 다시 접속합니다.',
      },
      reason: '현행 항목에는 잠금 해제 뒤 세션을 지우는 안내가 없어요. 4건이 같은 방법으로 해결됐어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
    },
    {
      id: 'c4',
      cat: 'HW',
      topic: '프린터 드라이버 설치 후에도 인쇄가 안 됨',
      kind: 'amend',
      state: 'preparing',
      tickets: [t('RCPT-0401', '프린터를 추가했는데 인쇄가 안 돼요', '기본 프린터 지정 후 정상'), t('RCPT-0409', '드라이버 설치 후 인쇄 대기만 떠요', '인쇄 대기열을 비우고 기본 프린터로 지정'), t('RCPT-0415', '새 프린터 인쇄가 안 나와요', '기본 프린터 변경')],
      target: { docCode: 'IT-HW-003', title: '프린터·복합기 이용 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.2 프린터를 추가했는데 인쇄가 안 됨' },
      change: '2·3번 조치 추가: 인쇄 대기열 비우기, 기본 프린터 지정',
      before: '1. 설정에서 프린터 목록에 장치가 보이는지 확인합니다.',
      after: '1. 설정에서 프린터 목록에 장치가 보이는지 확인합니다.\n2. 인쇄 대기열에 멈춘 작업이 있으면 모두 삭제합니다.\n3. 사용할 프린터를 기본 프린터로 지정한 뒤 다시 인쇄합니다.',
      reason: '대기열과 기본 프린터 안내가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      registered: { docCode: 'IT-HW-003', version: 'v3' },
    },
    {
      id: 'c5',
      cat: 'ACS',
      topic: '공용 폴더 접근 권한 신청 방법',
      kind: 'new',
      state: 'failed',
      tickets: [t('RCPT-0501', '공용 폴더에 들어갈 수 없어요', '권한 신청서를 제출하고 팀장 승인 후 반영'), t('RCPT-0507', '공용 폴더 접근 권한이 필요해요', '신청서 제출, 팀장 승인'), t('RCPT-0514', '공용 폴더 권한 요청', '권한 신청 후 팀장 승인으로 반영')],
      title: '공용 폴더 접근 권한을 신청할 때',
      after: '#### 조치 방법\n\n1. 권한 신청서에 폴더 경로와 사용 목적을 적어 제출합니다.\n2. 팀장 승인이 끝나면 담당자가 권한을 반영합니다.\n\n**해결 확인**\n\n- 신청한 폴더가 열리면 해결된 것입니다.',
      reason: '접근권한 가이드에 공용 폴더 항목이 없어 새 가이드로 제안했어요.',
      warnings: [],
      scope: '담당자 이상',
      tx: '마스킹 후 허용',
      registered: { docCode: 'IT-ACS-004', version: 'v1' },
      failReason: '문서 변환 중 오류가 나서 검색 준비를 마치지 못했어요. 같은 버전으로 다시 시도할 수 있어요.',
    },
    {
      id: 'c6',
      cat: 'HW',
      topic: '노트북 화면 깜빡임',
      kind: 'amend',
      state: 'ready',
      tickets: [
        t('RCPT-0601', '노트북 화면이 깜빡여요', '그래픽 드라이버를 최신으로 업데이트'),
        t('RCPT-0606', '모니터 연결 후 화면 깜빡임', '디스플레이 주사율을 60Hz로 변경'),
        t('RCPT-0611', '화면이 가끔 깜빡입니다', '그래픽 드라이버 업데이트'),
        t('RCPT-0618', '노트북 화면 플리커', '주사율 변경 후 정상'),
        t('RCPT-0622', '외부 모니터가 깜빡여요', '케이블 교체와 주사율 변경'),
        t('RCPT-0629', '화면 깜빡임이 계속돼요', '그래픽 드라이버 업데이트'),
      ],
      target: { docCode: 'IT-HW-001', title: '업무 PC 기본 장애 대응 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.4 화면이 깜빡이거나 꺼짐' },
      change: '2·3번 조치 추가: 주사율 60Hz로 변경, 그래픽 드라이버 업데이트',
      before: '1. 연결 케이블이 느슨하지 않은지 확인합니다.',
      after: '1. 연결 케이블이 느슨하지 않은지 확인합니다.\n2. 디스플레이 설정에서 주사율을 60Hz로 바꿉니다.\n3. 같은 증상이 계속되면 그래픽 드라이버를 최신으로 업데이트합니다.',
      reason: '주사율과 드라이버 안내가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      registered: { docCode: 'IT-HW-001', version: 'v3' },
    },
    {
      id: 'c7',
      cat: 'SYS',
      topic: '메일함 용량 초과 시 정리 방법',
      kind: 'amend',
      state: 'live',
      tickets: [t('RCPT-0701', '메일을 못 받아요', '보관함 용량을 비우고 정상'), t('RCPT-0705', '메일함이 가득 찼다고 나와요', '오래된 첨부 메일 삭제'), t('RCPT-0712', '메일 수신이 안 돼요', '용량 초과로 첨부 메일 정리'), t('RCPT-0718', '메일함 용량 초과 안내', '보관함 정리'), t('RCPT-0724', '메일이 안 들어와요', '용량 초과 해소 후 수신')],
      target: { docCode: 'IT-SYS-001', title: '그룹웨어·ERP 이용 오류 대응 가이드', baseVersion: 'v2', latestVersion: 'v3', section: '3.3 메일을 받지 못함' },
      change: '2번 조치 추가: 오래된 첨부 메일 삭제와 휴지통 비우기',
      before: '1. 받은 편지함이 가득 찼는지 확인합니다.',
      after: '1. 받은 편지함이 가득 찼는지 확인합니다.\n2. 첨부 파일이 큰 오래된 메일부터 삭제하고 휴지통도 비웁니다.',
      reason: '용량 정리 안내가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      registered: { docCode: 'IT-SYS-001', version: 'v3' },
    },
    {
      id: 'c8',
      cat: 'NET',
      topic: '3층 무선 공유기 재부팅',
      kind: 'amend',
      state: 'dropped',
      tickets: [t('RCPT-0801', '3층에서 와이파이가 안 돼요', '3층 공유기를 재부팅'), t('RCPT-0807', '3층 무선 연결 끊김', '공유기 전원 재부팅')],
      target: { docCode: 'IT-NET-002', title: '사내 네트워크 장애 대응 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.1 사내 Wi-Fi가 끊김' },
      change: '2번 조치 추가: 해당 층 무선 공유기 재부팅',
      before: '1. 다른 위치에서 같은 증상이 있는지 확인합니다.',
      after: '1. 다른 위치에서 같은 증상이 있는지 확인합니다.\n2. 해당 층의 무선 공유기를 재부팅합니다.',
      reason: '한 층의 공유기를 재부팅한 일회성 조치로 보여요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      dropReason: '특정 층의 일회성 조치라서 가이드로 만들 필요가 없다고 판단했어요.',
    },
  ]
}

/* ------------------------------------------------------------------ 저장소 (모의) */
let store: CaseItem[] = seed()
let snapshot = store
const listeners = new Set<() => void>()
const timers = new Map<string, ReturnType<typeof setTimeout>>()
let failNext = new Set<string>()

const emit = () => {
  snapshot = [...store]
  listeners.forEach((f) => f())
}
export const subscribeCases = (f: () => void) => {
  listeners.add(f)
  return () => {
    listeners.delete(f)
  }
}
export const getCases = () => snapshot

/** 시연: 승인한 초안의 검색 준비는 이 시간(ms) 뒤에 끝난다 */
export const PREPARE_DELAY_MS = 4000

const patch = (id: string, f: (c: CaseItem) => CaseItem) => {
  store = store.map((c) => (c.id === id ? f(c) : c))
  emit()
}
const find = (id: string) => store.find((c) => c.id === id)
const nextVersionOf = (v: string) => `v${(Number(v.replace(/\D/g, '')) || 1) + 1}`

function startPrepare(id: string) {
  clearTimeout(timers.get(id))
  timers.set(
    id,
    setTimeout(() => {
      timers.delete(id)
      const c = find(id)
      if (!c || c.state !== 'preparing') return
      if (failNext.has(id)) {
        failNext.delete(id)
        patch(id, (x) => ({ ...x, state: 'failed', failReason: '문서 변환 중 오류가 나서 검색 준비를 마치지 못했어요. 같은 버전으로 다시 시도할 수 있어요.' }))
      } else patch(id, (x) => ({ ...x, state: 'ready', failReason: undefined }))
    }, PREPARE_DELAY_MS),
  )
}

export interface CaseEdit {
  title?: string
  cat?: CategoryCode
  after: string
  scope: GuideScope
  tx: GuideTx
}
type Result = { ok: true } | { ok: false; message: string }
/** 값이 없는 칸(예: 기존 보강에는 제목·분류가 없다)은 기존 값을 덮어쓰지 않도록 뺀다 */
const defined = (e: CaseEdit): Partial<CaseItem> => Object.fromEntries(Object.entries(e).filter(([, v]) => v !== undefined)) as Partial<CaseItem>

/** 기준 버전이 현재 현행 버전과 다른지 (달라지면 등록·현행 전환을 막는다) */
export const baseChanged = (c: CaseItem) => !!c.target && c.target.baseVersion !== c.target.latestVersion

/** 임시 저장: 상태는 그대로 검토 중이다 */
export function saveCase(id: string, e: CaseEdit): void {
  patch(id, (c) => (c.state === 'review' ? { ...c, ...defined(e), savedAt: new Date().toISOString() } : c))
}

/** 승인하고 초안 등록: 현행이 아닌 새 버전으로 등록하고 검색 준비를 시작한다. 기준 버전이 바뀐 건은 막는다 */
export function approveCase(id: string, e: CaseEdit): Result {
  const c = find(id)
  if (!c) return { ok: false, message: '제안을 찾을 수 없어요.' }
  if (c.state !== 'review') return { ok: false, message: '이미 승인했거나 처리한 제안이에요.' }
  if (baseChanged(c)) return { ok: false, message: '기준 가이드가 바뀌어서 등록할 수 없어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.' }
  if (!e.after.trim()) return { ok: false, message: '가이드 내용을 입력해 주세요.' }
  if (c.kind === 'new' && !(e.title ?? c.title ?? '').trim()) return { ok: false, message: '가이드 제목을 입력해 주세요.' }
  const registered = c.target ? { docCode: c.target.docCode, version: nextVersionOf(c.target.latestVersion) } : { docCode: `IT-${e.cat ?? c.cat}-009`, version: 'v1' }
  patch(id, (x) => ({ ...x, ...defined(e), state: 'preparing', registered, savedAt: undefined }))
  startPrepare(id)
  return { ok: true }
}

/** 비가이드화: 사유를 남기고 이 제안을 닫는다 */
export function dropCase(id: string, reason: string): Result {
  const c = find(id)
  if (!c || c.state !== 'review') return { ok: false, message: '검토 중인 제안만 가이드화 안 함으로 바꿀 수 있어요.' }
  if (!reason.trim()) return { ok: false, message: '사유를 입력해 주세요.' }
  patch(id, (x) => ({ ...x, state: 'dropped', dropReason: reason.trim() }))
  return { ok: true }
}

/** 검색 준비에 실패한 같은 버전을 다시 준비한다 (후보로 다시 돌리지 않는다) */
export function retryCase(id: string): Result {
  const c = find(id)
  if (!c || c.state !== 'failed') return { ok: false, message: '검색 준비에 실패한 건만 다시 시도할 수 있어요.' }
  patch(id, (x) => ({ ...x, state: 'preparing', failReason: undefined }))
  startPrepare(id)
  return { ok: true }
}

/** 현행 전환: 검색 준비가 끝난 뒤 관리자가 따로 실행한다. 기준 버전이 바뀐 건은 막는다 */
export function goLiveCase(id: string): Result {
  const c = find(id)
  if (!c || c.state !== 'ready') return { ok: false, message: '검색 준비가 끝난 건만 현행으로 바꿀 수 있어요.' }
  if (baseChanged(c)) return { ok: false, message: '기준 가이드가 바뀌어서 현행으로 바꿀 수 없어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.' }
  patch(id, (x) => ({ ...x, state: 'live' }))
  return { ok: true }
}

/** 기준 가이드가 바뀐 제안: 최신 내용에 맞춘 제안문으로 바꾸고 기준 버전을 최신으로 맞춘다 */
export function rebaseCase(id: string): Result {
  const c = find(id)
  if (!c || !c.target || !c.latest) return { ok: false, message: '최신 내용에 맞춘 제안이 없어요.' }
  patch(id, (x) => ({ ...x, after: x.latest!.after, before: x.latest!.before, target: { ...x.target!, baseVersion: x.target!.latestVersion } }))
  return { ok: true }
}

/** 시연: 다음에 승인하는 이 제안은 검색 준비가 실패한다 (테스트용) */
export function failNextPrepare(id: string) {
  failNext.add(id)
}

/** 처음 상태로 되돌린다 (테스트) */
export function resetCaseGuides() {
  timers.forEach((x) => clearTimeout(x))
  timers.clear()
  failNext = new Set()
  store = seed()
  emit()
}
