/**
 * 페이지 이동 (목록 아래). 20개씩 보고, 한 쪽 분량 이하면 총 건수만 한 줄로 알린다.
 * 구성: « 처음 · ‹ 이전 / 쪽 번호 / … 생략 / › 다음 · » 마지막. 작게 두고 이동·선택 모션은 없다.
 * 번호는 앞쪽이면 1~5 … 끝, 가운데면 1 … 앞뒤 … 끝, 뒤쪽이면 1 … 끝 5쪽처럼 7칸 안에서 보여 준다. (design/ITssue-Prototype.html pager)
 */
import { pageSlots } from './pageSlots'

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
  return (
    <nav className="d2pg" aria-label="페이지">
      <span className="small muted">
        {from}–{to} / {total}건 · {size}개씩
      </span>
      <div className="n">
        <button type="button" className="pn" aria-label="처음 페이지" disabled={page <= 1} onClick={() => onPage(1)}>
          «
        </button>
        <button type="button" className="pn" aria-label="이전 페이지" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹
        </button>
        {pageSlots(page, pages).map((x, i) =>
          x === '…' ? (
            <span key={`e${i}`} className="el" aria-hidden="true">
              …
            </span>
          ) : (
            <button key={x} type="button" className={x === page ? 'on' : ''} aria-current={x === page ? 'page' : undefined} aria-label={`${x}쪽`} onClick={() => onPage(x)}>
              {x}
            </button>
          ),
        )}
        <button type="button" className="pn" aria-label="다음 페이지" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          ›
        </button>
        <button type="button" className="pn" aria-label="마지막 페이지" disabled={page >= pages} onClick={() => onPage(pages)}>
          »
        </button>
      </div>
    </nav>
  )
}
