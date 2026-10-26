/**
 * 민감정보 마스킹 (design/ITssue-Prototype.html 의 maskSens 와 같은 규칙).
 *
 * 비밀번호·인증번호로 보이는 값은 대화·초안·로그에 넣기 전에 ●로 바꾼다.
 * 실제 서비스에서는 서버가 같은 일을 하며, 이 파일은 시연(mock)과 로그인 전 상담 화면에서 쓴다.
 */

const MASK = '●●●●●●'

/** "비밀번호는 abc123", "인증번호: 123456" 처럼 이름 뒤에 값이 붙은 모양 (값에 숫자·영문·기호가 있을 때만) */
const LABELED = /(비밀번호|패스워드|암호|인증번호|인증 번호|보안코드|OTP|PIN|password|passwd|pw)(\s*(?:는|은|이|가|:|=)\s*)([^\s,]+)/gi
/** 6자리 이상 숫자 */
const LONG_DIGITS = /\d{6,}/g

export interface Masked {
  text: string
  /** 가린 값이 있었는지 */
  hit: boolean
}

export function maskSensitive(input: string): Masked {
  let hit = false
  let text = input.replace(LABELED, (all, key: string, sep: string, value: string) => {
    if (/[0-9A-Za-z!@#$%^&*]/.test(value) && !/^●+$/.test(value)) {
      hit = true
      return key + sep + MASK
    }
    return all
  })
  text = text.replace(LONG_DIGITS, () => {
    hit = true
    return MASK
  })
  return { text, hit }
}

/** 이미 가려진 글인지 (●가 3개 이상) */
export const hasMask = (text: string) => /●{3,}/.test(text)

/** 가려졌다고 알릴 때 쓰는 안내 문구 */
export const MASK_NOTICE = '비밀번호·인증번호로 보이는 값은 저장하기 전에 ●로 바꿨어요. 앞으로는 입력하지 마세요.'
