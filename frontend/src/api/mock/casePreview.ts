/**
 * 개발 전용 미리보기: 서버에 AI 가이드 제안이 아직 없을 때 "서버 연결 화면"(등록·다시 맞추기·넣을 문서 변경)을 눈으로 보기 위한 가짜 서버.
 * `VITE_PREVIEW_GUIDE_CASES=true` 이고 개발 서버(npm run dev, mode=development)일 때만 켜지며, 배포 빌드에는 들어가지 않는다.
 * 로그인 등 다른 요청은 그대로 실서버로 가고, /guide-clusters 와 /documents 요청만 이 파일이 메모리에서 답한다 (실서버 DB 는 건드리지 않는다).
 * 새로고침하면 처음 상태로 돌아간다. 모양은 docs/api/04 (GC-01~08, DC-01·02) 응답을 따른다.
 */
import { displayMessage } from '../errorText'
import { fail, ok, type ApiResult, type ErrorDetail } from '../types'

export const PREVIEW_GUIDE_CASES = import.meta.env.MODE === 'development' && String(import.meta.env.VITE_PREVIEW_GUIDE_CASES ?? '').trim() === 'true'

interface Ver {
  id: number
  version: string
  isCurrent: boolean
  ingestStatus: 'DONE' | 'PENDING' | 'FAILED'
}
interface Doc {
  id: number
  docCode: string
  docType: 'GUIDE'
  title: string
  categoryCode: string
  isActive: boolean
  versions: (Ver & { viewScope: string; transferPolicy: string; versionState: string; ingestError: null })[]
}
interface Conflict {
  section: string
  kind: string
  message: string
  oldMd: string
  newMd: string
}
interface Cluster {
  id: number
  category: { code: string; name: string }
  judgment: string
  status: 'REVIEWING' | 'APPLIED' | 'REJECTED'
  title: string
  ticketCount: number
  targetDocId: number | null
  targetSection: string | null
  targetMd: string | null
  registeredVersion: Ver | null
  draftMd: string | null
  draftRevision: number
  reviewInfo: { reason: string; warnings: string[]; [key: string]: unknown } | null
  baseVersion: Ver | null
  currentVersion: Ver | null
  baseChanged: boolean
  conflicts: Conflict[]
  rejectReason: string | null
  tickets: { ticketId: number; receiptNo: string; summary: string; symptom: string; resolutionNote: string }[]
}

const ver = (id: number, version: string, current: boolean): Doc['versions'][number] => ({ id, version, isCurrent: current, ingestStatus: 'DONE', viewScope: 'ALL', transferPolicy: 'ALLOWED', versionState: current ? 'CURRENT' : 'EXPIRED', ingestError: null })

// 등록 완료 제안(107번)이 가리키는 초안도 버전 목록에 둔다. 안내만 있고 전환할 행이 빠지지 않게 한다.
const seedDocs = (): Doc[] => [
  { id: 1, docCode: 'IT-NET-001', docType: 'GUIDE', title: 'VPN 접속 장애 대응 가이드', categoryCode: 'NET', isActive: true, versions: [{ ...ver(14, 'v2.1', false), versionState: 'DRAFT' }, ver(12, 'v2.0', true)] },
  { id: 2, docCode: 'IT-ACC-001', docType: 'GUIDE', title: '사내 SSO 로그인 오류 대응 가이드', categoryCode: 'ACC', isActive: true, versions: [ver(21, 'v2.1', true)] },
  { id: 3, docCode: 'IT-SW-001', docType: 'GUIDE', title: '업무용 SW 설치 가이드', categoryCode: 'SW', isActive: true, versions: [ver(31, 'v1.0', true)] },
  { id: 4, docCode: 'IT-HW-005', docType: 'GUIDE', title: '노트북 배터리 점검 가이드 (버전 없음)', categoryCode: 'HW', isActive: true, versions: [] },
]

const tk = (n: number, summary: string, note: string) => ({ ticketId: n, receiptNo: `REQ-2026-${String(1000 + n).padStart(6, '0')}`, summary, symptom: summary, resolutionNote: note })

const seedClusters = (): Cluster[] => [
  {
    id: 101, category: { code: 'NET', name: '네트워크' }, judgment: 'ADD_ITEM', status: 'REVIEWING', title: 'VPN 접속 후 사내 시스템이 열리지 않을 때', ticketCount: 4,
    targetDocId: 1, targetSection: null, targetMd: null, registeredVersion: null,
    draftMd: '### 3.5 VPN 연결은 되는데 사내 시스템이 열리지 않을 때\n\n1. VPN 클라이언트를 완전히 종료한 뒤 다시 실행합니다.\n2. 연결 후 DNS 캐시를 비웁니다. (`ipconfig /flushdns`)\n3. 그래도 안 되면 IT 헬프데스크에 접수합니다.',
    draftRevision: 1, reviewInfo: { reason: '같은 증상의 해결 사례 4건이 현행 가이드에 없는 절차를 공통으로 사용했어요.', warnings: [], form: 'TROUBLESHOOT', guessed: ['원인'], differences: ['REQ-2026-001001·001002는 VPN 재실행으로, 001003은 DNS 초기화만으로 해결했어요. 공통인 DNS 초기화를 먼저 쓰고 재실행은 보조로 넣었어요.'] },
    baseVersion: { id: 12, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE' }, currentVersion: { id: 12, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE' },
    baseChanged: false, conflicts: [], rejectReason: null,
    tickets: [tk(1, 'VPN 연결 후 그룹웨어가 열리지 않아요', 'DNS 캐시 초기화 후 정상'), tk(2, 'VPN 접속은 되는데 ERP 접속 불가', 'VPN 재실행·DNS 초기화로 해결'), tk(3, '재택근무 중 사내 사이트 접속 오류', 'DNS 초기화 안내'), tk(4, 'VPN 연결됨 표시인데 내부망 접속 안 됨', 'VPN 재실행')],
  },
  {
    id: 102, category: { code: 'ACC', name: '계정' }, judgment: 'CHANGE', status: 'REVIEWING', title: 'SSO 로그인 오류 시 확인 순서 변경', ticketCount: 6,
    targetDocId: 2, targetSection: '3.3', targetMd: '### 3.3 로그인 오류\n\n브라우저를 다시 시작한 뒤 로그인합니다.',
    registeredVersion: null,
    draftMd: '### 3.3 로그인 오류\n\n1. 시크릿 창에서 로그인해 봅니다.\n2. 브라우저 쿠키·캐시를 삭제합니다.\n3. 계정 잠금 여부를 헬프데스크에 확인합니다.',
    draftRevision: 3, reviewInfo: { reason: '현행 3.3 항목의 안내만으로는 해결되지 않은 사례 6건이 모였어요.\n계정 잠금이 원인인 사례가 3건이에요.', warnings: ['3.3 항목의 기존 안내를 대체해요.'], change_note: '브라우저 재시작만 안내하던 항목에 시크릿 창·캐시 삭제·계정 잠금 확인을 순서대로 추가했어요. 재시작만으로는 해결되지 않은 사례가 많았기 때문이에요.' },
    baseVersion: { id: 20, version: 'v2.0', isCurrent: false, ingestStatus: 'DONE' }, currentVersion: { id: 21, version: 'v2.1', isCurrent: true, ingestStatus: 'DONE' },
    baseChanged: true, conflicts: [], rejectReason: null,
    tickets: [tk(5, 'SSO 로그인 계속 실패', '시크릿 창·캐시 삭제로 해결'), tk(6, '로그인 화면이 반복돼요', '쿠키 삭제'), tk(7, 'SSO 오류 코드 E-401', '계정 잠금 해제')],
  },
  {
    id: 103, category: { code: 'HW', name: '장비' }, judgment: 'NEW_GUIDE', status: 'REVIEWING', title: '노트북 배터리 팽창 신고와 교체 절차', ticketCount: 3,
    targetDocId: null, targetSection: null, targetMd: null, registeredVersion: null,
    draftMd: '---\ndoc_no: ""\ntitle: "노트북 배터리 팽창 신고와 교체 절차"\ncategory: "HW"\nversion: "v1.0"\n---\n\n# 노트북 배터리 팽창 신고와 교체 절차\n\n## 1. 개요\n\n(작성 필요)\n\n## 2. 먼저 확인할 사항\n\n(작성 필요)\n\n## 3. 증상별 조치 방법\n\n### 3.1 노트북 바닥이 부풀거나 트랙패드가 눌리지 않을 때\n\n1. 즉시 전원을 끄고 충전기를 분리합니다.\n2. IT 헬프데스크에 신고합니다.\n3. 교체 장비를 받으면 데이터를 이전합니다.\n\n## 4. 자주 묻는 질문\n\n## 5. 주의사항\n\n## 6. 문의처\n\nIT 헬프데스크 내선 1000 (평일 09:00~18:00)\n',
    draftRevision: 1, reviewInfo: { reason: '관련 가이드가 없고 같은 신고가 3건 있었어요.', warnings: ['6장 문의처를 같은 분류 현행 가이드에서 복사했어요.'], form: 'TROUBLESHOOT', guide_title: '노트북 배터리 팽창 신고와 교체 절차', guessed: ['원인'] },
    baseVersion: null, currentVersion: null, baseChanged: false, conflicts: [], rejectReason: null,
    tickets: [tk(8, '노트북 바닥이 부풀었어요', '배터리 팽창, 교체'), tk(9, '트랙패드가 눌리지 않아요', '배터리 팽창 확인, 교체'), tk(10, '노트북이 책상에서 흔들려요', '배터리 팽창')],
  },
  {
    id: 104, category: { code: 'ACS', name: '권한' }, judgment: 'MANUAL_CANDIDATE', status: 'REVIEWING', title: '신규 입사자 계정 일괄 발급 절차', ticketCount: 5,
    targetDocId: null, targetSection: null, targetMd: null, registeredVersion: null, draftMd: null, draftRevision: 0,
    reviewInfo: { reason: '담당자 내부 절차라 가이드가 아닌 매뉴얼 후보예요.', warnings: [], manual_note: '- 입사자 명단은 인사팀 전달 파일 기준으로 일괄 등록해요.\n- 초기 비밀번호는 입사일에 맞춰 문자로 보내요.\n- 권한 그룹은 부서 기본값을 먼저 적용한 뒤 개별 신청을 받아요.', manual_items: ['IT-MAN-001 3.2 계정 발급', 'IT-MAN-001 3.4 입사자 일괄 처리'] },
    baseVersion: null, currentVersion: null, baseChanged: false, conflicts: [], rejectReason: null,
    tickets: [tk(11, '신규 입사자 5명 계정 발급', '내부 절차 참고')],
  },
  {
    id: 105, category: { code: 'SEC', name: '보안' }, judgment: 'SEC_MANUAL', status: 'REVIEWING', title: '의심 메일 신고 후 계정 조치', ticketCount: 2,
    targetDocId: null, targetSection: null, targetMd: null, registeredVersion: null,
    draftMd: '### 의심 메일 신고 후 계정 조치\n\n1. 신고된 메일을 격리합니다.\n2. 클릭한 사용자의 비밀번호를 초기화합니다.',
    draftRevision: 1, reviewInfo: { reason: '의심 사고 티켓이라 AI가 가이드 초안을 만들지 않았어요.', warnings: [] },
    baseVersion: null, currentVersion: null, baseChanged: false, conflicts: [], rejectReason: null,
    tickets: [tk(12, '피싱 메일 링크를 눌렀어요', '비밀번호 초기화')],
  },
  {
    id: 106, category: { code: 'SW', name: '소프트웨어' }, judgment: 'ADD_ITEM', status: 'REVIEWING', title: '설치 중 관리자 권한 요청이 뜰 때', ticketCount: 3,
    targetDocId: 3, targetSection: null, targetMd: null, registeredVersion: null,
    draftMd: '### 2.4 설치 중 관리자 권한을 요구할 때\n\n설치 프로그램을 우클릭해 "관리자 권한으로 실행"을 선택합니다. 그래도 안 되면 IT 헬프데스크에 요청합니다.',
    draftRevision: 2, reviewInfo: { reason: '현행 가이드가 바뀌었는지 확인이 필요해요.\n권한 요청이 뜨는 조건이 설치 프로그램마다 달라요.', warnings: [], differences: ['2건은 우클릭 실행으로, 1건은 IT 헬프데스크 원격 설치로 해결했어요.'] },
    baseVersion: { id: 30, version: 'v0.9', isCurrent: false, ingestStatus: 'DONE' }, currentVersion: { id: 31, version: 'v1.0', isCurrent: true, ingestStatus: 'DONE' },
    baseChanged: true, conflicts: [], rejectReason: null,
    tickets: [tk(13, '설치할 때 권한 요청이 떠요', '관리자 권한 실행'), tk(14, '프로그램 설치 불가', '관리자 권한')],
  },
  {
    id: 107, category: { code: 'NET', name: '네트워크' }, judgment: 'ADD_ITEM', status: 'REVIEWING', title: 'Wi-Fi 인증서 갱신 안내 (등록됨, 검색 준비 끝)', ticketCount: 2,
    targetDocId: 1, targetSection: null, targetMd: null, registeredVersion: { id: 14, version: 'v2.1', isCurrent: false, ingestStatus: 'DONE' },
    draftMd: '### 3.6 Wi-Fi 인증서가 만료됐을 때\n\n설정에서 인증서를 삭제하고 다시 연결합니다.',
    draftRevision: 2, reviewInfo: { reason: '이미 초안으로 등록돼 현행 전환을 기다려요.', warnings: [] },
    baseVersion: { id: 12, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE' }, currentVersion: { id: 12, version: 'v2.0', isCurrent: true, ingestStatus: 'DONE' },
    baseChanged: false, conflicts: [], rejectReason: null,
    tickets: [tk(15, 'Wi-Fi 인증서 오류', '인증서 재설치'), tk(16, '사내 Wi-Fi 연결 안 됨', '인증서 삭제 후 재연결')],
  },
]

let docs = seedDocs()
let clusters = seedClusters()
let nextDocId = 50

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const err = <T>(code: string, details?: ErrorDetail[]): ApiResult<T> => fail(code, displayMessage(code, '', details), { details })
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

const docRef = (id: number | null) => {
  const d = docs.find((x) => x.id === id)
  return d ? { id: d.id, docCode: d.docCode, title: d.title } : null
}
const summary = (c: Cluster) => ({ id: c.id, category: c.category, judgment: c.judgment, status: c.status, title: c.title, ticketCount: c.ticketCount, targetDocument: docRef(c.targetDocId), registeredVersion: c.registeredVersion })
const detail = (c: Cluster, warnings?: string[]) => ({
  ...summary(c),
  targetSection: c.targetSection,
  targetMd: c.targetMd,
  conflicts: c.conflicts,
  draftMd: c.draftMd,
  draftRevision: c.draftRevision,
  reviewInfo: c.reviewInfo,
  baseVersion: c.baseVersion,
  currentVersion: c.currentVersion,
  baseChanged: c.baseChanged,
  rejectReason: c.rejectReason,
  reviewedBy: c.status === 'REJECTED' ? { name: '관리자(미리보기)' } : null,
  reviewedAt: c.status === 'REJECTED' ? new Date().toISOString() : null,
  tickets: c.tickets,
  ...(warnings ? { warnings } : {}),
})

const SECTION_RE = /^\d+\.\d+$/

function clusterCall(c: Cluster, action: string, body: Record<string, unknown>): ApiResult<unknown> {
  if (action === 'reject') {
    if (c.status !== 'REVIEWING') return err('GUIDE_CLUSTER_NOT_REVIEWING')
    c.status = 'REJECTED'
    c.rejectReason = String(body.reason ?? '')
    return ok(detail(c))
  }
  if (action === 'apply') {
    if (c.status !== 'REVIEWING') return err('GUIDE_CLUSTER_NOT_REVIEWING')
    c.status = 'APPLIED'
    return ok(detail(c))
  }
  if (c.status !== 'REVIEWING') return err('GUIDE_CLUSTER_NOT_REVIEWING')
  if (body.draftRevision !== c.draftRevision) return err('GUIDE_CLUSTER_DRAFT_CONFLICT')

  if (action === 'register') {
    if (c.judgment === 'MANUAL_CANDIDATE') return err('GUIDE_CLUSTER_NOT_REGISTRABLE', [{ field: 'cluster', reason: 'JUDGMENT', message: '' }])
    if (c.draftMd === null) return err('GUIDE_CLUSTER_NOT_REGISTRABLE', [{ field: 'cluster', reason: 'NO_DRAFT', message: '' }])
    if (c.targetDocId === null) return err('GUIDE_CLUSTER_NOT_REGISTRABLE', [{ field: 'cluster', reason: 'NO_TARGET', message: '' }])
    if (c.baseChanged) return err('GUIDE_CLUSTER_BASE_CHANGED')
    if (c.judgment === 'NEW_GUIDE' && c.draftMd.split('\n').some((l) => l.trim() === '(작성 필요)')) {
      return err('GUIDE_CLUSTER_ASSEMBLE_FAILED', [{ field: 'draftMd', reason: 'ASSEMBLE', message: "'(작성 필요)' 자리가 남아 있습니다: 1장, 2장" }])
    }
    if (c.conflicts.length) return err('GUIDE_CLUSTER_CONFLICT_UNRESOLVED', [{ field: 'section', reason: 'CONFLICT', message: '', value: c.conflicts[0].section }])
    const d = docs.find((x) => x.id === c.targetDocId)
    const v = c.registeredVersion ?? { id: nextDocId * 10 + 1, version: d?.versions.length ? 'v2.2' : 'v1.0', isCurrent: false, ingestStatus: 'PENDING' as const }
    v.ingestStatus = 'PENDING'
    c.registeredVersion = v
    // 검색 준비는 몇 초 뒤 끝난다
    setTimeout(() => {
      if (c.registeredVersion) c.registeredVersion.ingestStatus = 'DONE'
    }, 4000)
    return ok(detail(c, ['표가 들어 있는 항목은 검색에서 글자만 읽힐 수 있어요. (미리보기 경고 예시)']))
  }

  if (action === 'rebase') {
    if (!c.baseChanged) return err('GUIDE_CLUSTER_REBASE_FAILED', [{ field: 'cluster', reason: 'REBASE', message: '기준이 바뀌지 않은 제안이에요.' }])
    c.baseChanged = false
    c.baseVersion = c.currentVersion
    c.draftRevision += 1
    if (c.judgment === 'CHANGE') {
      c.conflicts = [{ section: c.targetSection ?? '3.3', kind: 'CHANGED_IN_CURRENT', message: '초안을 만든 뒤 현행에서 이 항목이 고쳐졌어요.', oldMd: c.targetMd ?? '', newMd: '### 3.3 로그인 오류\n\n브라우저를 다시 시작하고, 그래도 안 되면 SSO 포털 공지를 확인한 뒤 로그인합니다.' }]
      return ok(detail(c, ['3.3 항목이 현행에서 달라졌어요. 비교해서 초안을 고쳐 주세요.']))
    }
    return ok(detail(c, ['새 현행 v1.0에 맞춰 위치를 다시 잡았어요. (미리보기 경고 예시)']))
  }

  if (action === 'target') {
    const d = docs.find((x) => x.id === body.documentId)
    if (!d) return err('DOCUMENT_NOT_FOUND')
    const sec = typeof body.targetSection === 'string' ? body.targetSection : null
    if (c.judgment === 'CHANGE' && !(sec && SECTION_RE.test(sec))) return err('VALIDATION_ERROR')
    if (d.id === c.targetDocId && sec === c.targetSection) return err('GUIDE_CLUSTER_TARGET_UNCHANGED')
    if (c.judgment === 'NEW_GUIDE' && d.versions.length) return err('GUIDE_CLUSTER_TARGET_INVALID', [{ field: 'documentId', reason: 'TARGET', message: '이미 버전이 있는 문서에는 새 가이드를 연결할 수 없어요.' }])
    if (c.judgment !== 'NEW_GUIDE' && !d.versions.length) return err('GUIDE_CLUSTER_TARGET_INVALID', [{ field: 'documentId', reason: 'TARGET', message: '현행 버전이 없는 문서예요.' }])
    c.targetDocId = d.id
    c.targetSection = sec
    c.draftRevision += 1
    const cur = d.versions.find((x) => x.isCurrent)
    c.baseVersion = c.currentVersion = cur ? { id: cur.id, version: cur.version, isCurrent: true, ingestStatus: 'DONE' } : null
    c.baseChanged = false
    c.targetMd = c.judgment === 'CHANGE' ? '### ' + sec + ' (기준 원문)\n\n문서를 옮기면서 가져온 원문 예시예요.' : null
    c.conflicts = c.judgment === 'CHANGE' ? [{ section: sec ?? '', kind: 'CHANGED_IN_CURRENT', message: '새 문서의 해당 항목이 초안의 기준과 달라요.', oldMd: c.targetMd ?? '', newMd: '### ' + sec + ' (새 문서 현행)\n\n새 문서에 이미 있는 내용 예시예요.' }] : []
    return ok(detail(c, c.conflicts.length ? ['새 문서의 현행 내용과 다른 항목이 있어요.'] : undefined))
  }
  return err('NOT_FOUND')
}

/** /guide-clusters·/documents 요청이면 가짜 응답을, 아니면 null (실서버로 보낸다) */
export async function previewSend(path: string, init: RequestInit): Promise<ApiResult<unknown> | null> {
  const p = path.split('?')[0]
  const method = (init.method ?? 'GET').toUpperCase()
  const body: Record<string, unknown> = typeof init.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : {}
  if (p === '/guide-clusters/analysis-status' && method === 'GET') {
    await wait(200)
    const mon = new Date()
    mon.setHours(0, 0, 0, 0)
    mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7))
    const next = new Date(mon)
    next.setDate(next.getDate() + 7)
    return ok({ lastAnalyzedAt: mon.toISOString(), nextAnalysisAt: next.toISOString(), lastRunStatus: 'SUCCEEDED' })
  }
  const m = /^\/guide-clusters(?:\/(\d+)(?:\/(\w+))?)?$/.exec(p)
  const d = /^\/documents(?:\/(\d+)\/versions)?$/.exec(p)
  if (!m && !d) return null
  await wait(200)

  if (m) {
    if (!m[1]) {
      return ok({ items: clusters.map(summary), page: 1, size: 100, totalItems: clusters.length, totalPages: 1 })
    }
    const c = clusters.find((x) => x.id === Number(m[1]))
    if (!c) return err('GUIDE_CLUSTER_NOT_FOUND')
    if (!m[2]) {
      if (method === 'GET') return ok(copy(detail(c)))
      if (method === 'PATCH') {
        if (c.status !== 'REVIEWING') return err('GUIDE_CLUSTER_NOT_REVIEWING')
        if (body.draftRevision !== c.draftRevision) return err('GUIDE_CLUSTER_DRAFT_CONFLICT')
        c.draftMd = String(body.draftMd ?? '')
        c.draftRevision += 1
        c.conflicts = [] // 초안을 고쳐 저장하면 충돌이 풀린다
        return ok(copy(detail(c)))
      }
    }
    const r = clusterCall(c, m[2] ?? '', body)
    return r.ok ? ok(copy(r.data)) : r
  }

  if (d && !d[1]) {
    if (method === 'POST') {
      const code = String(body.docCode ?? '')
      if (docs.some((x) => x.docCode === code)) return err('DOCUMENT_CODE_DUPLICATE')
      const nd: Doc = { id: nextDocId++, docCode: code, docType: 'GUIDE', title: String(body.title ?? ''), categoryCode: String(body.categoryCode ?? ''), isActive: true, versions: [] }
      docs = [...docs, nd]
      return ok({ id: nd.id, docCode: nd.docCode, docType: nd.docType, title: nd.title, categoryCode: nd.categoryCode, currentVersion: null })
    }
    return ok({
      items: docs.map((x) => {
        const cur = x.versions.find((v) => v.isCurrent)
        return { id: x.id, docCode: x.docCode, docType: x.docType, title: x.title, categoryCode: x.categoryCode, isActive: x.isActive, currentVersion: cur ? { version: cur.version, viewScope: cur.viewScope, transferPolicy: cur.transferPolicy } : null, ingestSummary: null }
      }),
      page: 1,
      size: 100,
      totalItems: docs.length,
      totalPages: 1,
    })
  }
  const doc = docs.find((x) => x.id === Number(d?.[1]))
  return doc ? ok({ items: doc.versions.map((v) => ({ ...v, registeredAt: null })) }) : err('DOCUMENT_NOT_FOUND')
}
