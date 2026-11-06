/**
 * 대화에서 "새로 생긴 메시지"만 움직이게 하려는 기록.
 * 서버에 글을 보내면 먼저 내 글(임시 id -1)과 "준비 중"을 보여 주고, 서버가 답하면 같은 글이 진짜 id 로 다시 온다.
 * id 가 바뀌면 같은 말풍선이 지워졌다 다시 생겨 화면이 다시 불러온 것처럼 보이므로, 임시 글과 같은 내 글은 같은 키를 이어 쓰고 새 메시지로 치지 않는다.
 */
export interface KnownMessages {
  id: number
  ids: Set<number>
  /** 새로 생긴(움직일) 메시지 id */
  fresh: Set<number>
  /** 지금 보이는 임시 내 글(id -1)의 글 */
  opt: string | null
  /** 진짜 id → 이어 쓰는 키 (임시 글이 진짜 글이 된 경우) */
  alias: Map<number, number>
}

export const OPTIMISTIC_USER_ID = -1

interface Msg {
  id: number
  role: string
  text?: string
}

const optText = (msgs: Msg[]) => msgs.find((m) => m.id === OPTIMISTIC_USER_ID)?.text ?? null

/** 다음 기록을 만든다. 바뀐 게 없으면 같은 객체를 돌려준다 */
export function nextKnown(prev: KnownMessages | null, inquiryId: number, msgs: Msg[]): KnownMessages {
  const ids = msgs.map((m) => m.id)
  const opt = optText(msgs)
  if (!prev || prev.id !== inquiryId) return { id: inquiryId, ids: new Set(ids), fresh: new Set(), opt, alias: new Map() }
  const fresh = ids.filter((x) => !prev.ids.has(x))
  if (!fresh.length) return prev.opt === opt ? prev : { ...prev, opt }
  const alias = new Map(prev.alias)
  // 임시 내 글이 진짜 글로 바뀐 것: 같은 글의 새 id 는 같은 키를 쓰고 움직이지 않는다
  if (prev.opt !== null && !ids.includes(OPTIMISTIC_USER_ID)) {
    const real = msgs.find((m) => m.role === 'user' && m.id > 0 && fresh.includes(m.id) && m.text === prev.opt)
    if (real) alias.set(real.id, OPTIMISTIC_USER_ID)
  }
  return { id: inquiryId, ids: new Set(ids), fresh: new Set(fresh.filter((x) => !alias.has(x))), opt, alias }
}
