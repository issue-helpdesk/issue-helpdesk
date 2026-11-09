/**
 * 로그인 전 상담 API 어댑터 (제안 기능 · 팀 확정 전, PRD 4.1 · SRS PRE-01).
 *
 * 로그인 화면에서 계정·로그인 범위의 공개 Guide 안내만 한다. 인증 없이 호출하며 Ticket은 만들지 않는다.
 */
import { request, sleep } from '../core/apiClient'
import { HELPDESK, MOCK_ONLY } from '../core/config'
import { guideSource } from './mock/sources'
import { ok, type ApiResult, type ConsultReply } from './types'

/** 출처 미리보기에 보여 줄 가이드 요약 (시연용. 실제 연결 후에는 서버가 준 본문을 쓴다) */
const LOCK_GUIDE = `### 이런 경우
- 로그인에 5회 연속 실패해 계정이 잠겼어요.
### 조치 방법
1. 10분을 기다리면 잠금이 자동으로 해제돼요.
2. 해제된 뒤 비밀번호를 정확히 입력해 보세요.
3. 그래도 안 되면 IT 헬프데스크에 연락해 주세요.
### 해결 확인
- 로그인이 되면 해결된 것입니다.`
const MFA_GUIDE = `### 이런 경우
- OTP 번호가 계속 맞지 않거나 MFA 인증 창이 넘어가지 않아요.
### 조치 방법
1. OTP 앱의 **시간 자동 설정**이 켜져 있는지 확인해요.
2. 브라우저를 모두 닫고 다시 시도해요.
3. 기기를 바꿨다면 MFA 재등록을 요청해요.`

const EXPIRED_GUIDE = `### 이런 경우
- 로그인할 때 '비밀번호가 만료되었습니다' 메시지가 떠요.
### 조치 방법
1. 안내 화면의 **[지금 변경]** 을 눌러요.
2. 현재(만료된) 비밀번호를 입력해요.
3. 새 비밀번호를 두 번 입력해요. 비밀번호 규칙을 모두 채워야 해요.
4. 새 비밀번호로 다시 로그인해요.
### 해결되지 않으면
- 만료된 비밀번호도 기억나지 않으면 **[비밀번호가 기억나지 않나요?]** 로 초기화해요.`
const MISMATCH_GUIDE = `### 이런 경우
- 비밀번호를 맞게 쳤는데 '아이디 또는 비밀번호가 일치하지 않습니다'라고 나와요.
### 조치 방법
1. Caps Lock이 켜져 있지 않은지, 한/영 전환이 한글로 되어 있지 않은지 확인해요.
2. ID 칸에 이메일이 아니라 **사번**을 입력했는지 확인해요.
3. 그래도 실패하면 더 시도하지 않아요. **5회 연속 실패하면 계정이 잠겨요.**
4. 비밀번호가 기억나지 않으면 비밀번호 초기화로 진행해요.`
const DEVICE_GUIDE = `### 이런 경우
- 휴대폰을 바꿔서 2단계 인증(OTP·승인 알림)을 할 수 없어요.
### 조치 방법
1. 기존 휴대폰이 있으면 인증 앱에서 계정을 새 기기로 이전해요.
2. 기존 휴대폰이 없으면 서비스데스크에 MFA 초기화를 요청한 뒤 새 기기로 다시 등록해요.
3. OTP 번호가 계속 틀리면 휴대폰 시간을 '자동 설정'으로 바꿔 보세요.`

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
        HELPDESK,
      ],
    }
  }
  if (/(잠|잠금|5회|lock)/i.test(t)) {
    return {
      paragraphs: [
        '로그인 5회 실패 시 계정이 잠기고 **10분 후 자동으로 해제**돼요. 해제된 뒤 비밀번호를 정확히 입력해 보세요. 그래도 안 되면 서비스데스크에 연락해 주세요.',
      ],
      sources: [guideSource('IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 v2 · 3.2', LOCK_GUIDE)],
    }
  }
  if (/만료/.test(t)) {
    return {
      paragraphs: ['안내 화면의 **[지금 변경]**을 눌러 만료된 비밀번호를 입력하고, 규칙에 맞는 새 비밀번호를 두 번 입력해 바꾸세요. 만료된 비밀번호도 기억나지 않으면 **[비밀번호가 기억나지 않나요?]**로 초기화할 수 있어요.'],
      sources: [guideSource('IT-ACC-002 비밀번호 변경·초기화 가이드 · 3.3', EXPIRED_GUIDE)],
    }
  }
  if (/일치하지/.test(t)) {
    return {
      paragraphs: ['Caps Lock과 한/영 전환을 확인하고, ID 칸에 이메일이 아니라 **사번**을 입력했는지 확인해 보세요. 그래도 실패하면 더 시도하지 마세요. **5회 연속 실패하면 계정이 잠겨요.**'],
      sources: [guideSource('IT-ACC-001 사내 SSO 로그인 오류 대응 가이드 · 3.1', MISMATCH_GUIDE)],
    }
  }
  if (/(휴대폰|폰|기기).{0,8}(바꿔|바꾼|교체|변경)/.test(t)) {
    return {
      paragraphs: ['기존 휴대폰이 있으면 인증 앱에서 계정을 새 기기로 이전하세요. 기존 휴대폰이 없다면 서비스데스크에 **MFA 초기화**를 요청한 뒤 새 기기로 다시 등록해야 해요.', HELPDESK],
      sources: [guideSource('IT-ACC-003 MFA 인증 오류 대응 가이드 · 3.5', DEVICE_GUIDE)],
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
      sources: [guideSource('IT-ACC-003 MFA 인증 오류 대응 가이드 v2 · 3.3', MFA_GUIDE)],
    }
  }

  // 범위 밖: 근거 없이 답하지 않는다 (SRS NFR-REL-01)
  return {
    sources: [],
    paragraphs: [
      '이 질문은 로그인 전 상담 범위(계정·로그인)를 벗어나요. 근거 없이 안내하지 않을게요. 로그인 후 새 문의로 질문하거나 서비스데스크로 연락해 주세요.',
      HELPDESK,
    ],
  }
}

/** 로그인 전 상담 질문을 보낸다. 실제 경로(/public/consult)는 백엔드와 협의 후 확정한다. */
export async function askPreLogin(message: string): Promise<ApiResult<ConsultReply>> {
  if (MOCK_ONLY) {
    await sleep(800) // 응답 지연 흉내
    return ok(mockReply(message))
  }
  return request<ConsultReply>('/public/consult', { method: 'POST', body: JSON.stringify({ message }) })
}
