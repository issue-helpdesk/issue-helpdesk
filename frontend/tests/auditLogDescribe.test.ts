/**
 * 운영 기록: 서버가 준 영문 코드·내부 값을 화면 말로 바꾸는 사전과 describeAudit().
 * 서버가 지금 남기는 기존 이벤트와 가이드화 이벤트가 모두 사전에 있고, 값마다 사람이 읽는 말로 바뀐다.
 */
import { describe, expect, it } from 'vitest'
import { EVENT_LABEL, TARGET_LABEL, TARGET_KINDS, describeAudit } from '../src/api/auditLogs'

const d = (eventType: string, result: string | null, reason: string | null = null) => describeAudit({ eventType, result, reason })

describe('이벤트 사전', () => {
  it('지원하는 이벤트가 모두 한글 이름과 색을 가진다', () => {
    const server = [
      'SECURITY_ALERT_REVIEW',
      'SECURITY_ALERT_CLOSE',
      'SECURITY_ALERT_VIEW',
      'SENSITIVE_INPUT',
      'BLOCK',
      'FAIL',
      'URGENT_CLOSED',
      'CONFIRM',
      'REASSIGN',
      'INTEGRATION_RETRY',
      'DOCUMENT_ACTIVATE',
      'DOCUMENT_DEACTIVATE',
      'DOCUMENT_VERSION_ACTIVATE',
      'DOCUMENT_VERSION_RETRY',
      'DOCUMENT_POLICY_CHANGE',
      'USER_CREATE',
      'USER_ROLE_CHANGE',
      'USER_STATUS_CHANGE',
      'PASSWORD_RESET',
      'LOGIN_BLOCKED',
      'ACCOUNT_LOCKED',
      'FAQ_DELETE',
      'FAQ_AUTO_UNPUBLISH',
      'CASE_GUIDE_REGISTER',
      'GUIDE_CLUSTER_REGISTER',
      'GUIDE_CLUSTER_REBASE',
      'GUIDE_CLUSTER_TARGET_CHANGE',
      'GUIDE_CLUSTER_REJECT',
      'GUIDE_CLUSTER_APPLY',
    ]
    expect(Object.keys(EVENT_LABEL).sort()).toEqual([...server].sort())
    for (const k of server) expect(EVENT_LABEL[k].label).not.toBe(k)
  })
})

describe('describeAudit', () => {
  it('보안 알림의 대상·결과를 번역하고 사유와 알 수 없는 결과는 보존한다', () => {
    expect(TARGET_LABEL.security_alert).toBe('보안 알림')
    expect(TARGET_KINDS).toContain('security_alert')
    expect(d('SECURITY_ALERT_REVIEW', 'REVIEW').out).toBe('확인 시작')
    expect(d('SECURITY_ALERT_CLOSE', 'CLOSE', '정상 문의 확인')).toMatchObject({ out: '종결', reason: '정상 문의 확인' })
    expect(d('SECURITY_ALERT_VIEW', 'VIEW_ORIGINAL').out).toBe('저장된 문의 열람')
    expect(d('SECURITY_ALERT_VIEW', 'UNKNOWN').out).toBe('UNKNOWN')
  })
  it('가이드화 결과의 종류·상태만 번역하고 번호·버전·사유와 모르는 값은 보존한다', () => {
    expect(TARGET_LABEL.guide_cluster).toBe('AI 가이드 제안')
    expect(TARGET_KINDS).toContain('guide_cluster')
    expect(d('GUIDE_CLUSTER_REGISTER', 'ADD_ITEM → v2.1').out).toBe('항목 추가 → v2.1')
    expect(d('GUIDE_CLUSTER_REJECT', 'NEW_GUIDE REVIEWING → REJECTED', '중복이에요')).toMatchObject({ out: '새 가이드 검토 중 → 반영 안함', reason: '중복이에요' })
    expect(d('GUIDE_CLUSTER_APPLY', 'MANUAL_CANDIDATE REVIEWING → APPLIED').out).toBe('매뉴얼 후보 검토 중 → 반영 완료')
    expect(d('GUIDE_CLUSTER_REBASE', 'CHANGE 기준 버전 12 → 34, 충돌 2건').out).toBe('항목 변경 기준 버전 12 → 34, 충돌 2건')
    expect(d('GUIDE_CLUSTER_TARGET_CHANGE', 'CHANGE 문서 3 → 9 항목 3.2').out).toBe('항목 변경 문서 3 → 9 항목 3.2')
    expect(d('GUIDE_CLUSTER_REGISTER', 'FUTURE_KIND → v3').out).toBe('FUTURE_KIND → v3')
    expect(d('CASE_GUIDE_REGISTER', 'RCPT-0001 → v2').out).toBe('RCPT-0001 → v2')
  })

  it('재배정: 배정 · 재배정 · 배정 실패', () => {
    expect(d('REASSIGN', 'ASSIGN').out).toBe('배정')
    expect(d('REASSIGN', 'REASSIGN', '기존 담당자 휴가')).toMatchObject({ out: '재배정', reason: '기존 담당자 휴가' })
    expect(d('REASSIGN', 'FAIL').out).toBe('배정 실패')
  })

  it('연동 재처리·근거 차단·AI 실패', () => {
    expect(d('INTEGRATION_RETRY', 'QUEUED').out).toBe('재처리 예약')
    expect(d('INTEGRATION_RETRY', 'ALREADY_APPLIED').out).toBe('이미 반영돼 있음')
    expect(d('INTEGRATION_RETRY', 'LINKED_EXISTING').out).toBe('기존 ITSM 이슈에 연결')
    expect(d('BLOCK', 'DOC_BLOCKED', 'IT-SEC-003')).toMatchObject({ out: '근거 문서 차단', reason: '문서 IT-SEC-003' })
    expect(d('BLOCK', 'ALL_BLOCKED').out).toBe('근거 전체 차단, 담당자 연결 제안')
    expect(d('FAIL', 'FILTER_FAILED').out).toBe('민감정보 필터 실패')
    expect(d('FAIL', 'AI_FAILED', 'TIMEOUT')).toMatchObject({ out: 'AI 답변 실패', reason: 'TIMEOUT' })
    // 사유 앞의 서버 내부 번호(④)는 떼고 보인다
    expect(d('FAIL', 'FILTER_FAILED', '④ 검색 근거 IT-SEC-003').reason).toBe('검색 근거 IT-SEC-003')
    expect(d('FAIL', 'FILTER_FAILED', '④ 외부 모델 호출 직전').reason).toBe('외부 모델 호출 직전')
  })

  it('서버가 결과에 담아 준 접수번호·문서 코드·FAQ 번호만 식별 이름(name)으로 올린다', () => {
    expect(d('CONFIRM', 'RCPT-1041')).toMatchObject({ name: 'RCPT-1041', out: '접수 확정' })
    expect(d('DOCUMENT_ACTIVATE', 'IT-ACC-001')).toMatchObject({ name: 'IT-ACC-001', out: '활성화' })
    expect(d('DOCUMENT_DEACTIVATE', 'IT-HW-003')).toMatchObject({ name: 'IT-HW-003', out: '비활성화' })
    expect(d('FAQ_DELETE', 'FAQ-007')).toMatchObject({ name: 'FAQ-007', out: '삭제' })
    expect(d('FAQ_AUTO_UNPUBLISH', 'FAQ-012').name).toBe('FAQ-012')
    // 접수번호가 없는 이벤트에는 이름을 만들어 내지 않는다
    expect(d('REASSIGN', 'ASSIGN').name).toBe('')
    expect(d('USER_CREATE', 'EMPLOYEE').name).toBe('')
  })

  it('문서: 버전 전환·재처리·정책 변경(열람 범위/외부 전송)', () => {
    expect(d('DOCUMENT_VERSION_ACTIVATE', 'v1 → v2').out).toBe('현행 v1 → v2')
    expect(d('DOCUMENT_VERSION_RETRY', 'v3 파일 교체').out).toBe('v3 — 파일을 바꿔 재처리')
    expect(d('DOCUMENT_VERSION_RETRY', 'v3 같은 파일').out).toBe('v3 — 같은 파일로 재처리')
    expect(d('DOCUMENT_POLICY_CHANGE', 'v2 ALL/ALLOWED → ADMIN/BLOCKED').out).toBe('v2 · 열람 전 직원 → 관리자만 / 외부 전송 허용 → 금지')
    expect(d('DOCUMENT_POLICY_CHANGE', 'v1 AGENT/MASKED → ALL/ALLOWED').out).toBe('v1 · 열람 담당자 이상 → 전 직원 / 외부 전송 마스킹 후 허용 → 허용')
    expect(d('DOCUMENT_POLICY_CHANGE', '형식이 다른 값').out).toBe('형식이 다른 값') // 모르는 모양은 그대로
  })

  it('사용자: 역할·상태는 계정 관리 화면과 같은 말', () => {
    expect(d('USER_CREATE', 'EMPLOYEE').out).toBe('계정 생성 (역할: 문의자)')
    expect(d('USER_ROLE_CHANGE', 'AGENT', '팀 이동')).toMatchObject({ out: '역할 → 담당자', reason: '팀 이동' })
    expect(d('USER_STATUS_CHANGE', 'INACTIVE').out).toBe('상태 → 이용 제한')
    expect(d('PASSWORD_RESET', 'ACTIVE').out).toBe('임시 비밀번호 재발급 (상태: 정상)')
    expect(d('LOGIN_BLOCKED', 'INACTIVE').out).toBe('로그인 차단 (상태: 이용 제한)')
    expect(d('ACCOUNT_LOCKED', 'LOCKED').out).toBe('연속 실패로 잠김')
  })

  it('민감정보·긴급 종료', () => {
    expect(d('SENSITIVE_INPUT', 'PASSWORD', '1건')).toMatchObject({ out: '가린 항목: 비밀번호', reason: '1건' })
    expect(d('SENSITIVE_INPUT', 'RRN').out).toBe('가린 항목: 주민등록번호')
    expect(d('URGENT_CLOSED', 'CLOSED_UNRESOLVED').out).toBe('긴급 징후가 있었는데 담당자 연결 없이 종료')
  })

  it('사전에 없는 이벤트·값은 서버가 준 글 그대로 둔다', () => {
    expect(d('SOMETHING_NEW', 'X', '사유')).toEqual({ name: '', out: 'X', reason: '사유' })
    expect(d('INTEGRATION_RETRY', 'NEW_VALUE').out).toBe('NEW_VALUE')
    expect(d('FAIL', null).out).toBe('')
  })
})
