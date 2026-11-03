/**
 * 가이드 본문(마크다운)을 읽기 쉽게 보여 주는 가벼운 렌더러 (공통 UI).
 *
 * 지원: 제목(#~######), 글머리표(- · *), 번호 목록(1.), 표(| 로 나뉜 줄), [그림]·[표] 표시, 굵게(**), 코드(`), 빈 줄로 나뉜 문단.
 * HTML 을 해석하지 않고 React 요소로만 그리므로 서버가 준 문구를 그대로 넣어도 스크립트가 실행되지 않는다.
 *
 * 서버가 가져온 본문은 줄바꿈 없이 한 줄로 이어져 오는 경우가 있어서(### 제목 - 항목 - 항목 …),
 * 줄바꿈이 없으면 제목 표시·글머리표·번호 앞에서 줄을 나눠 읽을 수 있게 만든다.
 */
import { Fragment, type ReactNode } from 'react'
import { restoreBreaks } from './markdownText'

/** **굵게** 와 `코드` 를 인라인으로 처리한다 */
function inline(text: string): ReactNode {
  return text.split(/(\*\*.+?\*\*|`[^`]+`)/g).map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return <b key={i}>{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return <code key={i}>{p.slice(1, -1)}</code>
    return <Fragment key={i}>{p}</Fragment>
  })
}

type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'fig'; label: string; text: string }
  | { kind: 'table'; rows: string[][] }
  | { kind: 'ul' | 'ol'; items: string[] }

const cells = (line: string) => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())

function parse(text: string): Block[] {
  const blocks: Block[] = []
  for (const raw of restoreBreaks(text).split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const h = /^(#{1,6})\s+(.+)$/.exec(line)
    if (h) {
      blocks.push({ kind: 'h', level: h[1].length, text: h[2] })
      continue
    }
    const fig = /^\[(그림|표)\]\s*(.*)$/.exec(line)
    if (fig) {
      blocks.push({ kind: 'fig', label: fig[1], text: fig[2] })
      continue
    }
    if (line.startsWith('|') && line.endsWith('|')) {
      const row = cells(line)
      if (row.every((c) => /^:?-{2,}:?$/.test(c))) continue // 머리글 아래 구분선
      const last = blocks[blocks.length - 1]
      if (last && last.kind === 'table') last.rows.push(row)
      else blocks.push({ kind: 'table', rows: [row] })
      continue
    }
    const ul = /^[-*•]\s+(.+)$/.exec(line)
    const ol = /^\d{1,2}\.\s+(.+)$/.exec(line)
    if (ul || ol) {
      const kind = ul ? 'ul' : 'ol'
      const item = (ul ?? ol)![1]
      const last = blocks[blocks.length - 1]
      if (last && last.kind === kind) last.items.push(item)
      else blocks.push({ kind, items: [item] })
      continue
    }
    blocks.push({ kind: 'p', text: line })
  }
  return blocks
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {parse(text).map((b, i) => {
        if (b.kind === 'h') return <h4 key={i}>{inline(b.text)}</h4>
        if (b.kind === 'p') return <p key={i}>{inline(b.text)}</p>
        if (b.kind === 'fig')
          return (
            <div key={i} className="fig" role="img" aria-label={`${b.label}: ${b.text || '설명 없음'}`}>
              <b>{b.label}</b>
              {b.text}
            </div>
          )
        if (b.kind === 'table')
          return (
            <div key={i} className="tbl2">
              <table>
                <thead>
                  <tr>
                    {b.rows[0].map((c, j) => (
                      <th key={j}>{inline(c)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.slice(1).map((r, j) => (
                    <tr key={j}>
                      {r.map((c, k) => (
                        <td key={k}>{inline(c)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        const Tag = b.kind
        return (
          <Tag key={i}>
            {b.items.map((x, j) => (
              <li key={j}>{inline(x)}</li>
            ))}
          </Tag>
        )
      })}
    </div>
  )
}
