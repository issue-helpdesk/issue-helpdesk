/**
 * 무작위 UUID(v4) 만들기. 요청 중복 방지 키(Idempotency-Key)에 쓴다.
 * `crypto.randomUUID()` 는 https·localhost 에서만 있어서, http 로 운영하는 서버에서는 호출하면 오류가 난다.
 * 그래서 어디서나 쓸 수 있는 `crypto.getRandomValues` 로 직접 만들고, 그것도 없으면 Math.random 으로 대신한다.
 */
export function uuid(): string {
  const c = typeof globalThis.crypto !== 'undefined' ? globalThis.crypto : undefined
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  const b = new Uint8Array(16)
  if (typeof c?.getRandomValues === 'function') c.getRandomValues(b)
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  b[6] = (b[6] & 0x0f) | 0x40 // 버전 4
  b[8] = (b[8] & 0x3f) | 0x80 // 변종 10
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}
