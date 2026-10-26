/**
 * 페이지 이동 (목록 아래). 20개씩 보고, 처음·끝·현재 앞뒤 쪽만 번호로 보여 준다. (design/ITssue-Prototype.html pager)
 * 한 쪽 분량 이하면 총 건수만 한 줄로 알린다.
 */
interface Props {
  page: number
  size: number
  total: number
  onPage: (p: number) => void
}

export function Pager({ page, size, total, onPage }: Props) {
  const pages = Math.max(1, Math.ceil(total / size))
  if (total <= size) return <div className="hint" style={{ padding: 10 }}>총 {total}건</div>
  const from = (page - 1) * size + 1
  const to = Math.min(total, page * size)
  const nums: (number | '…')[] = []
  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || Math.abs(i - page) <= 1) nums.push(i)
    else if (nums[nums.length - 1] !== '…') nums.push('…')
  }
  return (
    <nav className="d2pg" aria-label="페이지">
      <span className="small muted">
        {from}–{to} / {total}건 · {size}개씩
      </span>
      <div className="n">
        <button type="button" className="pn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹ 이전
        </button>
        {nums.map((x, i) =>
          x === '…' ? (
            <span key={`e${i}`} className="muted">
              …
            </span>
          ) : (
            <button key={x} type="button" className={x === page ? 'on' : ''} aria-current={x === page ? 'page' : undefined} onClick={() => onPage(x)}>
              {x}
            </button>
          ),
        )}
        <button type="button" className="pn" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          다음 ›
        </button>
      </div>
    </nav>
  )
}
