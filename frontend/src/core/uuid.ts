/**
 * 무작위 UUID(v4) 만들기. 요청 중복 방지 키(Idempotency-Key)에 쓴다.
 * `crypto.randomUUID()` 는 https·localhost 에서만 있어서, http 로 운영하는 서버에서는 호출하면 오류가 난다.
 * 그래서 어디서나 쓸 수 있는 `crypto.getRandomValues` 로 직접 만든다.
 * 둘 다 없으면(아주 오래된 브라우저) 예측 가능한 값으로 대신하지 않고 예외를 던진다. 호출한 쪽(`idemPost`)이
 * 이를 오류 결과로 바꿔 화면에 "요청을 보내지 못했어요" 로 안내한다.
 */
export function uuid(): string {
  const c = typeof globalThis.crypto !== 'undefined' ? globalThis.crypto : undefined
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  if (typeof c?.getRandomValues !== 'function') throw new Error('이 브라우저에서는 요청 키를 만들 수 없어요')
  const b = new Uint8Array(16)
  c.getRandomValues(b)
  b[6] = (b[6] & 0x0f) | 0x40 // 버전 4
  b[8] = (b[8] & 0x3f) | 0x80 // 변종 10
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}
