import type { GuideSource } from '../api/chatTypes'

export interface Group {
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

