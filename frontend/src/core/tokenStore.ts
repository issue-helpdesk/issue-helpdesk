/**
 * 로그인 토큰(JWT) 보관소.
 *
 * - 메모리에 두고, 새로고침 후에도 로그인이 유지되도록 sessionStorage 에도 저장한다. (탭을 닫으면 사라짐)
 * - localStorage 는 쓰지 않는다. 오래 남아 노출 위험이 커지기 때문이다.
 * - 개인정보 보호 모드 등으로 저장소 접근이 막힐 수 있어서 모든 접근을 try/catch 로 감싼다.
 *   (막히면 메모리에만 저장하므로 새로고침 시 다시 로그인해야 한다)
 */

const KEY = 'itssue.token'

/** 메모리에 들고 있는 토큰 */
let memory: string | null = null

export const tokenStore = {
  /** 저장된 토큰을 돌려준다. 없으면 null */
  get(): string | null {
    if (memory) return memory
    try {
      memory = sessionStorage.getItem(KEY)
    } catch {
      // 저장소를 쓸 수 없으면 메모리 값만 사용한다
    }
    return memory
  },

  /** 로그인 성공 시 토큰을 저장한다. */
  set(token: string) {
    memory = token
    try {
      sessionStorage.setItem(KEY, token)
    } catch {
      // 저장소를 쓸 수 없으면 메모리에만 둔다
    }
  },

  /** 로그아웃·인증 실패 시 토큰을 지운다. */
  clear() {
    memory = null
    try {
      sessionStorage.removeItem(KEY)
    } catch {
      // 무시
    }
  },
}
