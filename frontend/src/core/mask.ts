/**
 * 민감정보 가림 (docs/10 2.3 규칙 중 화면에서 쓰는 A·B 등급, design/ITssue-Prototype.html 의 maskSens 와 같은 규칙).
 *
 * 비밀정보(A: 비밀번호·인증번호·API 키·개인 키)와 고유식별·금융(B: 주민등록번호·카드·계좌번호)은
 * 대화·초안·로그에 넣기 전에 ●로 바꾼다. 휴대폰·이메일·사번(C), 직원 이름(D), 내선번호·IP·오류 코드는 가리지 않는다.
 * 실제 서비스에서는 서버가 같은 일을 하며(저장 전 가림), 이 파일은 시연(mock)과 로그인 전 상담 화면에서 쓴다.
 */

const MASK = '●●●●●●'

/** 이름 뒤에 값이 붙은 비밀번호·인증번호 ("비밀번호는 abc123", "인증번호: 123456") */
const LABELED =
  /(비밀번호|비번|패스워드|암호|인증번호|인증 번호|인증코드|보안코드|OTP|PIN|password|passwd|pwd|pw)(\s*(?:는|은|이|가|:|=)\s*)([^\s,]+)/gi
/** 위 이름 가운데 비밀번호(재설정 안내를 덧붙이는 종류) */
const PASSWORD_LABEL = /^(비밀번호|비번|패스워드|암호|password|passwd|pwd|pw)$/i
const PRIVATE_KEY = /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g
const KEY_PREFIX = /(?:sk-|ghp_|AKIA|xoxb-|Bearer\s+)[A-Za-z0-9._-]{20,}/g
const KEY_LABELED = /(API\s?키|토큰|token|secret)(\s*(?:는|은|이|가|:|=)?\s*)([A-Za-z0-9._-]{16,})/gi
const RRN = /\d{6}-\d{7}/g
const CARD = /\d{4}([-\s])\d{4}\1\d{4}\1\d{4}/g
/** 숫자를 -로 이은 묶음 (합계 10자리 이상이면 계좌번호) */
const DASHED = /\d+(?:-\d+)+/g
const LONG_DIGITS = /\d{6,}/g
/** 가리지 않는 값: 휴대폰·이메일·사번(C 등급), 0x 오류 코드 */
const KEEP = /01[016789][-\s]?\d{3,4}[-\s]?\d{4}|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|EMP-\d{4}|0[xX][0-9a-fA-F]+/g

export interface Masked {
  text: string
  /** 가린 값이 있었는지 */
  hit: boolean
  /** 비밀정보(A)를 가렸는지 */
  secret: boolean
  /** 그 가운데 비밀번호였는지 */
  password: boolean
  /** 고유식별·금융(B)을 가렸는지 */
  identity: boolean
}

export function maskSensitive(input: string): Masked {
  const r = { secret: false, password: false, identity: false }
  // 가리면 안 되는 값은 잠시 치워 두었다가, 마지막에 되돌려 놓는다
  const kept: string[] = []
  let text = input.replace(KEEP, (m) => `\uE000${kept.push(m) - 1}\uE000`)

  text = text.replace(PRIVATE_KEY, () => {
    r.secret = true
    return MASK
  })
  text = text.replace(KEY_PREFIX, () => {
    r.secret = true
    return MASK
  })
  text = text.replace(KEY_LABELED, (_all, key: string, sep: string) => {
    r.secret = true
    return key + sep + MASK
  })
  text = text.replace(LABELED, (all, key: string, sep: string, value: string) => {
    if (/[0-9A-Za-z!@#$%^&*]/.test(value) && !/^●+$/.test(value)) {
      r.secret = true
      if (PASSWORD_LABEL.test(key)) r.password = true
      return key + sep + MASK
    }
    return all
  })
  text = text.replace(RRN, () => {
    r.identity = true
    return MASK
  })
  text = text.replace(CARD, () => {
    r.identity = true
    return MASK
  })
  text = text.replace(DASHED, (m) => {
    if (m.replace(/-/g, '').length < 10) return m
    r.identity = true
    return MASK
  })
  text = text.replace(LONG_DIGITS, () => {
    r.secret = true // 6자리 이상 연속 숫자는 인증번호·OTP 로 본다
    return MASK
  })

  text = text.replace(/\uE000(\d+)\uE000/g, (_all, i: string) => kept[+i])
  return { text, hit: r.secret || r.identity, ...r }
}

/** 이미 가려진 글인지 (●가 3개 이상) */
export const hasMask = (text: string) => /●{3,}/.test(text)

/** 가려졌다고 알릴 때 쓰는 안내 문구 (docs/10 6.1) */
export const MASK_NOTICE = '비밀번호·인증번호로 보이는 값은 저장하기 전에 ●로 바꿨어요. 앞으로는 입력하지 마세요.'
export const MASK_NOTICE_PASSWORD = '실제 비밀번호였다면 셀프 비밀번호 재설정 포털에서 바꾸는 것이 안전해요.'
export const MASK_NOTICE_IDENTITY = '주민등록번호·카드·계좌 번호는 IT 문의에 필요하지 않아 저장하기 전에 ●로 바꿨어요.'

/** 가린 종류에 맞는 안내 문구들 (비밀정보 → 비밀번호 추가 안내 → 고유식별·금융 순) */
export function maskNotices(m: Pick<Masked, 'secret' | 'password' | 'identity'>): string[] {
  const out: string[] = []
  if (m.secret) out.push(m.password ? `${MASK_NOTICE} ${MASK_NOTICE_PASSWORD}` : MASK_NOTICE)
  if (m.identity) out.push(MASK_NOTICE_IDENTITY)
  return out
}
