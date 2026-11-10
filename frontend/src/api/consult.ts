/**
 * 로그인 전에 공개할 수 있는 고정 도움말이다. 서버·AI 호출이나 문의 접수는 하지 않는다.
 * IT-ACC-002의 일반 안내를 참고하되 현재 서비스의 흐름에 맞췄다.
 * 내부 가이드 원문, 본인 확인·승인 절차, SSO·휴대폰 인증 안내는 포함하지 않는다.
 */
import { SERVICEDESK } from '../core/config'
import { PASSWORD_RULE } from '../core/password'
import { ok, type ApiResult, type ConsultReply } from './types'

const CONTACT = `IT 헬프데스크 사내 연락처: ${SERVICEDESK}`

const ANSWERS: Record<string, ConsultReply> = {
  '계정이 잠겼어요': {
    paragraphs: ['로그인에 5회 연속 실패하면 계정이 잠겨요. **10분 후 자동으로 해제**되니 잠시 기다렸다가 다시 로그인해 주세요.', '비밀번호가 기억나지 않으면 반복해서 시도하지 말고 비밀번호 분실 안내를 확인해 주세요.'],
    sources: [],
    ctas: [{ label: '비밀번호 분실 안내 보기', action: 'forgot' }],
  },
  '비밀번호를 잊었어요': {
    paragraphs: ['비밀번호는 직접 초기화할 수 없어요. IT 헬프데스크에 **임시 비밀번호 발급**을 요청해 주세요. 임시 비밀번호로 로그인하면 새 비밀번호를 정할 수 있어요.', CONTACT, '비밀번호와 인증번호는 다른 사람에게 알려 주지 마세요.'],
    sources: [],
    ctas: [{ label: '비밀번호 분실 안내 보기', action: 'forgot' }],
  },
  '사번 또는 비밀번호가 맞지 않아요': {
    paragraphs: ['이메일 대신 **사번**을 입력했는지 확인해 주세요. Caps Lock과 한/영 전환, 입력 앞뒤에 공백이 들어갔는지도 확인해 주세요.', '계속 실패하면 반복해서 시도하지 말고 비밀번호 분실 안내를 확인해 주세요.'],
    sources: [],
    ctas: [{ label: '비밀번호 분실 안내 보기', action: 'forgot' }],
  },
  '새 비밀번호가 규칙에 맞지 않아요': {
    paragraphs: [PASSWORD_RULE, '비밀번호 확인란에도 같은 새 비밀번호를 입력해 주세요.'],
    sources: [],
  },
  '임시 비밀번호를 받았어요': {
    paragraphs: ['로그인 화면에서 **사번과 발급받은 임시 비밀번호**를 입력해 주세요. 로그인 후 나타나는 비밀번호 변경 화면에서 새 비밀번호를 정하면 돼요.', PASSWORD_RULE, '임시 비밀번호로도 로그인할 수 없으면 IT 헬프데스크에 다시 문의해 주세요.'],
    sources: [],
  },
}

/** 질문과 답변을 한곳에서 관리해 화면의 질문에 답변이 빠지지 않도록 한다. */
export const PRE_LOGIN_QUESTIONS = Object.keys(ANSWERS)

export async function askPreLogin(message: string): Promise<ApiResult<ConsultReply>> {
  // 지정한 질문에만 답한다. 임의 입력을 서버나 외부 AI로 전달하지 않는다.
  const reply = Object.hasOwn(ANSWERS, message) ? ANSWERS[message] : {
    paragraphs: ['아래 질문에서 겪고 있는 문제를 선택해 주세요. 다른 문의는 로그인 후 새 문의에서 접수할 수 있어요.', CONTACT],
    sources: [],
  }
  return ok(reply)
}
