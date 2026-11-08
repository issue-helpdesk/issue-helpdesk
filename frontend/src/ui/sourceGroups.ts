import type { GuideSource } from '../api/chatTypes'

interface Group {
  key: string
  head: string
  items: GuideSource[]
}

/** 같은 가이드끼리 묶는다 (처음 나온 순서를 지킨다) */
export function groupSources(sources: GuideSource[]): Group[] {
  const groups: Group[] = []
  for (const s of sources) {
    const key = `${s.docCode}|${s.version}|${s.title}`
    let g = groups.find((x) => x.key === key)
    if (!g) {
      g = { key, head: [s.docCode, s.title, s.version].filter(Boolean).join(' '), items: [] }
      groups.push(g)
    }
    g.items.push(s)
  }
  return groups
}

/**
 * 같은 문서·버전·위치의 출처를 하나로 합친다 (처음 나온 순서를 지킨다). 서버는 근거 조각마다 한 줄씩 줘서
 * 한 답변에 같은 출처가 여러 번 올 수 있다 (docs/api/06 R-44). 본문은 먼저 나온 비어 있지 않은 것을, 그림은 모두 모아 쓴다.
 */
export function uniqueSources(sources: GuideSource[]): GuideSource[] {
  const out: GuideSource[] = []
  const at = new Map<string, number>()
  for (const s of sources) {
    const key = `${s.docCode}|${s.version}|${s.section}`
    const i = at.get(key)
    if (i === undefined) {
      at.set(key, out.length)
      out.push(s)
      continue
    }
    const first = out[i]
    const images = [...(first.images ?? []), ...(s.images ?? []).filter((x) => !(first.images ?? []).some((y) => y.key === x.key && y.caption === x.caption))]
    out[i] = { ...first, excerpt: first.excerpt || s.excerpt, images: images.length ? images : undefined }
  }
  return out
}
