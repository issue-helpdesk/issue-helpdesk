/**
 * 로그인 전 상담 API 어댑터 (제안 기능 · 팀 확정 전, PRD 4.1 · SRS PRE-01).
 *
 * 로그인 화면에서 계정·로그인 범위의 공개 Guide 안내만 한다. 인증 없이 호출하며 Ticket은 만들지 않는다.
 */
import { request, sleep } from '../core/apiClient'
import { SERVICEDESK, USE_MOCK } from '../core/config'
import { guideSource } from './mock/sources'
import { ok, type ApiResult, type ConsultReply } from './types'

/** 보안 사고가 의심되는 표현. 일반 안내 대신 담당자 연결 경로를 알려 준다. */
const SECURITY = /(피싱|악성|랜섬|해킹|도용|탈취|도난|분실|유출|의심.{0,6}(메일|링크|파일|접속)|(링크|첨부).{0,8}(눌렀|열었|클릭))/

/**
 * 시연용 결정적 응답 (실제 AI 호출이 아님).
 * 근거가 없는 질문에는 임의로 답하지 않고 로그인 후 문의나 서비스데스크로 안내한다.
 */
function mockReply(text: string): ConsultReply {
  const t = text.trim()

  if (SECURITY.test(t)) {
    return {
      sources: [],
      paragraphs: [
        '보안 사고가 의심되면 **로그인 후 새 문의**에서 담당자 연결을 요청해 주세요. 로그인할 수 없는 상황이면 서비스데스크로 바로 연락해 주세요.',
        `서비스데스크 ${SERVICEDESK}`,
      ],
    }
  }
  if (/(잠|잠금|5회|lock)/i.test(t)) {
    return {
      paragraphs: [
        '로그인 5회 실패 시 계정이 잠기고 **10분 후 자동으로 해제**돼요. 해제된 뒤 비밀번호를 정확히 입력해 보세요. 그래도 안 되면 서비스데스크에 연락해 주세요.',
      ],
      sources: [guideSource('IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3.2')],
    }
  }
  if (/(비밀번호|패스워드|재설정|초기화)/.test(t)) {
    return {
      paragraphs: [
        '비밀번호는 직접 초기화할 수 없어요. 로그인 화면의 **[비밀번호를 잊으셨나요?]**에서 안내를 확인하고, 서비스데스크에 **임시 비밀번호 발급**을 요청해 주세요. 임시 비밀번호로 로그인하면 새 비밀번호를 정해요.',
        '새 비밀번호는 8~64자이며 영문 대·소문자, 숫자, 특수문자 중 3종류 이상을 섞어야 해요. 비밀번호는 이 창에 입력하지 마세요.',
      ],
      sources: [],
      ctas: [{ label: '비밀번호를 잊으셨나요? 열기', action: 'forgot' }],
    }
  }
  if (/(SSO|MFA|OTP|인증)/i.test(t)) {
    return {
      paragraphs: [
        'OTP 앱의 **시간 자동 설정**이 켜져 있는지 확인하고, 브라우저를 모두 닫고 다시 시도해 보세요. 기기를 바꿨다면 MFA 재등록이 필요할 수 있어요.',
      ],
      sources: [guideSource('IT-ACC-003 MFA 인증 오류 대응 가이드 v2 · 3.3')],
    }
  }

  // 범위 밖: 근거 없이 답하지 않는다 (SRS NFR-REL-01)
  return {
    sources: [],
    paragraphs: [
      '이 질문은 로그인 전 상담 범위(계정·로그인)를 벗어나요. 근거 없이 안내하지 않을게요. 로그인 후 새 문의로 질문하거나 서비스데스크로 연락해 주세요.',
      `서비스데스크 ${SERVICEDESK}`,
    ],
  }
}

/** 로그인 전 상담 질문을 보낸다. 실제 경로(/public/consult)는 백엔드와 협의 후 확정한다. */
export async function askPreLogin(message: string): Promise<ApiResult<ConsultReply>> {
  if (USE_MOCK) {
    await sleep(800) // 응답 지연 흉내
    return ok(mockReply(message))
  }
  return request<ConsultReply>('/public/consult', { method: 'POST', body: JSON.stringify({ message }) })
}
