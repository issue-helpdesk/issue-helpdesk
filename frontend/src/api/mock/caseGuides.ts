/**
 * 해결 사례 → 가이드 초안 (관리자 가이드 관리의 두 번째 탭) 시연 데이터와 모의 상태 전환.
 * 서버에는 아직 이 기능이 없다(docs/api/06 R-23). 화면·버튼·상태 전환만 모의로 보여 주고, 서버 연결 없이 이 파일 안에서 바뀐다.
 *
 * 흐름: 주 1회 AI가 아직 가이드에 반영하지 않은 해결 사례를 분석해 비슷한 사례를 묶어 제안한다 → 관리자가 검토·수정하고
 * 승인하면서 열람 범위·외부 AI 전송 정책을 고르면 "현행이 아닌 초안 버전"으로 가이드 목록에 등록되고 검색 준비가 시작된다 →
 * 검색 준비가 끝나면 관리자가 가이드 목록에서 열람 범위를 다시 확인하고 현행으로 바꾼다 (자동 현행 전환은 없다).
 * 승인한 제안의 상태(검색 준비 중·실패·완료·현행)는 가이드 목록의 그 버전 상태에서 그대로 읽어 온다.
 * 화면에 보이는 상태 이름은 표시용이며 서버 상태값이 아니다.
 */
import type { CategoryCode } from '../chatTypes'
import { mockRegisterCaseDraft, mockRetryCaseDraft, mockVersionState, type GuideReady, type GuideScope, type GuideTx } from '../guides'
import { subscribe as subscribeStore } from './chatStore'

/** amend=기존 가이드 보강, new=신규 가이드. manual·sec 는 서버 연결 화면에만 있다 (매뉴얼 후보·SEC 직접 검토: 초안을 등록하지 않고 직접 반영한다) */
export type CaseKind = 'amend' | 'new' | 'manual' | 'sec'
export type CaseState = 'review' | 'preparing' | 'failed' | 'ready' | 'live' | 'applied' | 'dropped'

export const CASE_KIND_LABEL: Record<CaseKind, string> = { amend: '기존 가이드 보강', new: '신규 가이드', manual: '매뉴얼 후보', sec: 'SEC 직접 검토' }
export const CASE_STATE_LABEL: Record<CaseState, string> = {
  review: '검토 필요',
  preparing: '검색 준비 중',
  failed: '검색 준비 실패',
  ready: '검색 준비 완료',
  live: '현행',
  applied: '반영 완료',
  dropped: '가이드화 안 함',
}
/** 구분 배지 색 (StateBadge 의 tone): 기존 가이드 보강=보라, 신규 가이드=하늘 */
export const CASE_KIND_TONE: Record<CaseKind, string> = { amend: 'prog', new: 'info', manual: 'recv', sec: 'urg' }
/** 상태 배지 색 (StateBadge 의 tone) */
export const CASE_STATE_TONE: Record<CaseState, string> = { review: 'asg', preparing: 'warn', failed: 'urg', ready: 'ok', live: 'info', applied: 'ok', dropped: 'recv' }

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
  /** 표시용 상태. 승인한 제안은 가이드 목록의 버전 상태에서 정해진다 */
  state: CaseState
  tickets: CaseTicket[]
  /** 근거 티켓 수 (서버 목록은 티켓 내용 없이 수만 준다) */
  ticketCount: number
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
  /** 승인·등록한 문서와 버전 (가이드 목록의 문서·버전과 같다) */
  registered?: { docId: number; versionId: number; docCode: string; version: string }
  failReason?: string
  dropReason?: string
  /** 마지막으로 임시 저장한 시각 */
  savedAt?: string
  /** 서버 연결 화면에서만 쓴다 */
  server?: ServerCaseInfo
}

/** 서버(GC) 묶음에서 온 값 */
export interface ServerCaseInfo {
  /** 서버가 판단한 종류 이름 (항목 추가·변경·새 가이드·매뉴얼 후보·SEC 직접 검토) */
  judgmentLabel: string
  /** 기준 버전이 지금 현행과 다른지 (서버 판단) */
  baseChanged: boolean
  /** 초안 수정 저장 때 함께 보내는 번호 */
  draftRevision: number
  /** 초안이 있는지 (매뉴얼 후보는 없다) */
  hasDraft: boolean
  /** 상세(근거 티켓·초안)를 불러왔는지 */
  detail: boolean
  rejectReason?: string
  reviewedBy?: string
  reviewedAt?: string
}

/** 시연 이력: 이미 승인해서 가이드 목록에 등록돼 있는 것처럼 보이게 할 버전 */
interface SeedRegister {
  docCode: string
  ready: GuideReady
  current?: boolean
  error?: string
}
type Rec = Omit<CaseItem, 'state' | 'failReason' | 'ticketCount'> & { seed?: SeedRegister }

const t = (no: string, summary: string, result: string): CaseTicket => ({ no, summary, result })

function seed(): Rec[] {
  return [
    {
      id: 'c1',
      cat: 'NET',
      topic: '재택 VPN 연결 후 인터넷이 끊김 (공유기 설정)',
      kind: 'amend',
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
      before: '1. VPN 앱을 완전히 종료한 뒤 다시 실행합니다.\n2. 같은 증상이 계속되면 PC를 재시작한 뒤 다시 연결합니다.',
      change: '3번 조치 추가: 공유기 VPN 패스스루 설정 확인',
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
      tickets: [
        t('RCPT-0301', '계정 잠금 풀었는데 SSO가 계속 실패해요', '브라우저 쿠키 삭제 후 다시 로그인'),
        t('RCPT-0309', '잠금 해제 후에도 로그인 오류가 나요', '저장된 세션을 지우고 재로그인'),
        t('RCPT-0317', '잠금 풀렸다는데 SSO 로그인 안 됨', '쿠키와 캐시 삭제 후 정상'),
        t('RCPT-0324', '계정 잠금 해제 직후 로그인 실패', '브라우저를 완전히 종료하고 다시 접속'),
      ],
      target: { docCode: 'IT-ACC-001', title: '사내 SSO 로그인 오류 대응 가이드', baseVersion: 'v1', latestVersion: 'v2', section: '3.2 비밀번호를 바꾼 뒤 계정이 잠김' },
      before: '1. 비밀번호를 바꾼 뒤에는 휴대폰 메일 앱의 저장된 비밀번호를 먼저 바꿉니다.\n2. 잠금이 풀리면 다시 로그인합니다.',
      change: '3번 조치 추가: 쿠키·저장된 세션 삭제 후 재접속',
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
      tickets: [t('RCPT-0401', '프린터를 추가했는데 인쇄가 안 돼요', '기본 프린터 지정 후 정상'), t('RCPT-0409', '드라이버 설치 후 인쇄 대기만 떠요', '인쇄 대기열을 비우고 기본 프린터로 지정'), t('RCPT-0415', '새 프린터 인쇄가 안 나와요', '기본 프린터 변경')],
      target: { docCode: 'IT-HW-003', title: '프린터·복합기 이용 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.2 프린터를 추가했는데 인쇄가 안 됨' },
      before: '1. 설정에서 프린터 목록에 장치가 보이는지 확인합니다.',
      change: '2·3번 조치 추가: 인쇄 대기열 비우기, 기본 프린터 지정',
      after: '1. 설정에서 프린터 목록에 장치가 보이는지 확인합니다.\n2. 인쇄 대기열에 멈춘 작업이 있으면 모두 삭제합니다.\n3. 사용할 프린터를 기본 프린터로 지정한 뒤 다시 인쇄합니다.',
      reason: '대기열과 기본 프린터 안내가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      seed: { docCode: 'IT-HW-003', ready: '준비 중' },
    },
    {
      id: 'c5',
      cat: 'ACS',
      topic: '공용 폴더 접근 권한 신청 방법',
      kind: 'amend',
      tickets: [t('RCPT-0501', '공용 폴더에 들어갈 수 없어요', '권한 신청서를 제출하고 팀장 승인 후 반영'), t('RCPT-0507', '공용 폴더 접근 권한이 필요해요', '신청서 제출, 팀장 승인'), t('RCPT-0514', '공용 폴더 권한 요청', '권한 신청 후 팀장 승인으로 반영')],
      target: { docCode: 'IT-ACS-001', title: '사내 시스템 접근권한 신청 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.1 접근권한을 신청하는 방법' },
      before: '1. 신청서에 시스템 이름과 사용 목적을 적어 제출합니다.',
      change: '2번 조치 추가: 공용 폴더는 경로를 적고 팀장 승인',
      after: '1. 신청서에 시스템 이름과 사용 목적을 적어 제출합니다.\n2. 공용 폴더는 폴더 경로를 함께 적어 제출하고, 팀장 승인이 끝나면 담당자가 권한을 반영합니다.',
      reason: '접근권한 가이드에 공용 폴더 신청 방법이 없어요.',
      warnings: [],
      scope: '담당자 이상',
      tx: '마스킹 후 허용',
      seed: { docCode: 'IT-ACS-001', ready: '준비 실패', error: '문서 변환 중 오류가 나서 검색 준비를 마치지 못했어요. 같은 버전으로 다시 시도할 수 있어요.' },
    },
    {
      id: 'c6',
      cat: 'SW',
      topic: '프로그램 설치 중 관리자 권한 오류',
      kind: 'amend',
      tickets: [
        t('RCPT-0601', '프로그램 설치가 권한 오류로 멈춰요', '소프트웨어 센터에서 설치하도록 안내'),
        t('RCPT-0606', '설치 중 관리자 권한이 필요하대요', '설치 요청 후 담당자가 원격으로 설치'),
        t('RCPT-0611', '설치할 때 권한 없음 메시지', '소프트웨어 센터 설치로 해결'),
        t('RCPT-0618', '프로그램 설치 권한 오류', '설치 요청서를 제출해 담당자가 설치'),
        t('RCPT-0622', '관리자 권한 오류로 설치 실패', '소프트웨어 센터에서 설치'),
        t('RCPT-0629', '설치가 권한 때문에 안 돼요', '설치 요청 후 원격 설치'),
      ],
      target: { docCode: 'IT-SW-001', title: '업무용 SW 설치 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.2 설치가 중간에 멈춤' },
      before: '1. 설치 파일을 다시 내려받아 실행합니다.',
      change: '2·3번 조치 추가: 소프트웨어 센터 설치, 설치 요청서 제출',
      after: '1. 설치 파일을 다시 내려받아 실행합니다.\n2. 관리자 권한 오류가 나면 소프트웨어 센터에서 같은 프로그램이 있는지 찾아 설치합니다.\n3. 센터에 없으면 설치 요청서를 제출하고 담당자의 원격 설치를 기다립니다.',
      reason: '권한 오류 때 쓸 설치 경로가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      seed: { docCode: 'IT-SW-001', ready: '준비 완료' },
    },
    {
      id: 'c7',
      cat: 'SYS',
      topic: '메일함 용량 초과 시 정리 방법',
      kind: 'amend',
      tickets: [t('RCPT-0701', '메일을 못 받아요', '보관함 용량을 비우고 정상'), t('RCPT-0705', '메일함이 가득 찼다고 나와요', '오래된 첨부 메일 삭제'), t('RCPT-0712', '메일 수신이 안 돼요', '용량 초과로 첨부 메일 정리'), t('RCPT-0718', '메일함 용량 초과 안내', '보관함 정리'), t('RCPT-0724', '메일이 안 들어와요', '용량 초과 해소 후 수신')],
      target: { docCode: 'IT-SYS-001', title: '그룹웨어·ERP 이용 오류 대응 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.3 메일을 받지 못함' },
      before: '1. 받은 편지함이 가득 찼는지 확인합니다.',
      change: '2번 조치 추가: 오래된 첨부 메일 삭제와 휴지통 비우기',
      after: '1. 받은 편지함이 가득 찼는지 확인합니다.\n2. 첨부 파일이 큰 오래된 메일부터 삭제하고 휴지통도 비웁니다.',
      reason: '용량 정리 안내가 현행 항목에 없어요.',
      warnings: [],
      scope: '전 직원',
      tx: '허용',
      seed: { docCode: 'IT-SYS-001', ready: '준비 완료', current: true },
    },
    {
      id: 'c8',
      cat: 'NET',
      topic: '3층 무선 공유기 재부팅',
      kind: 'amend',
      tickets: [t('RCPT-0801', '3층에서 와이파이가 안 돼요', '3층 공유기를 재부팅'), t('RCPT-0807', '3층 무선 연결 끊김', '공유기 전원 재부팅')],
      target: { docCode: 'IT-NET-002', title: '사내 네트워크 장애 대응 가이드', baseVersion: 'v2', latestVersion: 'v2', section: '3.1 사내 Wi-Fi가 끊김' },
      before: '1. 다른 위치에서 같은 증상이 있는지 확인합니다.',
      change: '2번 조치 추가: 해당 층 무선 공유기 재부팅',
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
let recs: Rec[] = seed()
let seeded = false
let snapshot: CaseItem[] = []
let sig = ''
const listeners = new Set<() => void>()

const FAIL_TEXT = '문서 변환 중 오류가 나서 검색 준비를 마치지 못했어요. 같은 버전으로 다시 시도할 수 있어요.'

/** 표시용 상태: 승인한 제안은 가이드 목록의 그 버전 상태에서 읽는다 */
function derive(r: Rec): CaseItem {
  const { seed: _seed, ...base } = r
  void _seed
  const rest = { ...base, ticketCount: r.tickets.length }
  if (r.dropReason !== undefined) return { ...rest, state: 'dropped' }
  if (!r.registered) return { ...rest, state: 'review' }
  const v = mockVersionState(r.registered.docId, r.registered.versionId)
  if (!v || v.ready === '준비 중') return { ...rest, state: 'preparing' }
  if (v.ready === '준비 실패') return { ...rest, state: 'failed', failReason: v.error ?? FAIL_TEXT }
  return { ...rest, state: v.state === '초안' ? 'ready' : 'live' }
}
const build = () => recs.map(derive)
const signature = (items: CaseItem[]) => items.map((c) => `${c.id}:${c.state}:${c.registered?.version ?? ''}`).join('|')
snapshot = build()
sig = signature(snapshot)

const emit = () => {
  snapshot = build()
  sig = signature(snapshot)
  listeners.forEach((f) => f())
}
/** 가이드 목록(모의)이 바뀌면(검색 준비 완료·현행 전환 등) 승인한 제안의 상태도 따라 바뀐다 */
subscribeStore(() => {
  const next = build()
  if (signature(next) === sig) return
  snapshot = next
  sig = signature(next)
  listeners.forEach((f) => f())
})

export const subscribeCases = (f: () => void) => {
  listeners.add(f)
  return () => {
    listeners.delete(f)
  }
}
export const getCases = () => snapshot

/** 시연 이력으로 승인해 둔 제안의 버전을 가이드 목록(모의)에 한 번 등록한다 (가이드 관리 화면을 열 때) */
export function ensureCaseVersions() {
  if (seeded) return
  seeded = true
  recs = recs.map((r) => {
    if (!r.seed || r.registered) return r
    const reg = mockRegisterCaseDraft({ docCode: r.seed.docCode, title: r.target?.title ?? r.topic, cat: r.cat, scope: r.scope, tx: r.tx, ready: r.seed.ready, error: r.seed.error, current: r.seed.current })
    return { ...r, registered: reg }
  })
  emit()
}

const patch = (id: string, f: (c: Rec) => Rec) => {
  recs = recs.map((c) => (c.id === id ? f(c) : c))
  emit()
}
const find = (id: string) => snapshot.find((c) => c.id === id)

interface CaseEdit {
  title?: string
  cat?: CategoryCode
  after: string
  scope: GuideScope
  tx: GuideTx
}
type Result = { ok: true } | { ok: false; message: string }
/** 값이 없는 칸(예: 기존 보강에는 제목·분류가 없다)은 기존 값을 덮어쓰지 않도록 뺀다 */
const defined = (e: CaseEdit): Partial<CaseItem> => Object.fromEntries(Object.entries(e).filter(([, v]) => v !== undefined)) as Partial<CaseItem>

/** 기준 버전이 현재 현행 버전과 다른지 (달라지면 등록을 막는다) */
export const baseChanged = (c: CaseItem) => (c.server ? c.server.baseChanged : !!c.target && c.target.baseVersion !== c.target.latestVersion)

/** 임시 저장: 상태는 그대로 검토 필요다 */
export function saveCase(id: string, e: Pick<CaseEdit, 'title' | 'cat' | 'after'>): void {
  patch(id, (c) => (c.registered || c.dropReason !== undefined ? c : { ...c, ...(defined({ ...e, scope: c.scope, tx: c.tx }) as Partial<Rec>), savedAt: new Date().toISOString() }))
}

/** 승인하고 초안 등록: 가이드 목록에 현행이 아닌 새 버전(없으면 새 문서)으로 등록하고 검색 준비를 시작한다. 기준 버전이 바뀐 건은 막는다 */
export function approveCase(id: string, e: CaseEdit): Result {
  const c = find(id)
  if (!c) return { ok: false, message: '제안을 찾을 수 없어요.' }
  if (c.state !== 'review') return { ok: false, message: '이미 승인했거나 처리한 제안이에요.' }
  if (baseChanged(c)) return { ok: false, message: '기준 가이드가 바뀌어서 등록할 수 없어요. 최신 내용과 비교한 뒤 다시 검토해 주세요.' }
  if (!e.after.trim()) return { ok: false, message: '가이드 내용을 입력해 주세요.' }
  const title = c.kind === 'new' ? (e.title ?? c.title ?? '').trim() : c.target!.title
  if (c.kind === 'new' && !title) return { ok: false, message: '가이드 제목을 입력해 주세요.' }
  const cat = c.kind === 'new' ? (e.cat ?? c.cat) : c.cat
  const registered = mockRegisterCaseDraft({ docCode: c.target?.docCode, title, cat, scope: e.scope, tx: e.tx, ready: '준비 중' })
  patch(id, (x) => ({ ...x, ...(defined(e) as Partial<Rec>), registered, savedAt: undefined }))
  return { ok: true }
}

/** 비가이드화: 사유를 남기고 이 제안을 닫는다 */
export function dropCase(id: string, reason: string): Result {
  const c = find(id)
  if (!c || c.state !== 'review') return { ok: false, message: '검토가 필요한 제안만 가이드화 안 함으로 바꿀 수 있어요.' }
  if (!reason.trim()) return { ok: false, message: '사유를 입력해 주세요.' }
  patch(id, (x) => ({ ...x, dropReason: reason.trim() }))
  return { ok: true }
}

/** 검색 준비에 실패한 같은 버전을 다시 준비한다 (후보로 다시 돌리지 않는다) */
export function retryCase(id: string): Result {
  const c = find(id)
  if (!c || c.state !== 'failed' || !c.registered) return { ok: false, message: '검색 준비에 실패한 건만 다시 시도할 수 있어요.' }
  if (!mockRetryCaseDraft(c.registered.docId, c.registered.versionId)) return { ok: false, message: '다시 시도할 수 없는 상태예요.' }
  emit()
  return { ok: true }
}

/** 기준 가이드가 바뀐 제안: 최신 내용에 맞춘 제안문으로 바꾸고 기준 버전을 최신으로 맞춘다 */
export function rebaseCase(id: string): Result {
  const c = find(id)
  if (!c || !c.target || !c.latest) return { ok: false, message: '최신 내용에 맞춘 제안이 없어요.' }
  patch(id, (x) => ({ ...x, after: x.latest!.after, before: x.latest!.before, target: { ...x.target!, baseVersion: x.target!.latestVersion } }))
  return { ok: true }
}

/** 등록한 버전의 본문(마크다운): 기존 가이드 보강이면 반영 위치와 제안문, 신규면 제목과 본문 */
export function registeredText(c: CaseItem): string {
  if (c.kind === 'amend' && c.target) return `## ${c.target.section}\n\n${c.after}`
  return `## ${c.title ?? c.topic}\n\n${c.after}`
}

/** 처음 상태로 되돌린다 (테스트) */
export function resetCaseGuides() {
  recs = seed()
  seeded = false
  emit()
}
