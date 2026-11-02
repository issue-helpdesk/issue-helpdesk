/**
 * 정렬할 수 있는 표 열 머리 (공통 UI). 누르면 정렬이 바뀌고, 현재 정렬은 aria-sort 로 알린다.
 * center 이면 머리글과 값을 가운데로 둔다 (배지가 들어가는 열).
 */
interface Props<C extends string> {
  col: C
  label: string
  tip?: string
  center?: boolean
  /** true 이면 정렬 버튼 없이 글자만 보인다 (서버가 이 열의 정렬을 받지 않을 때) */
  plain?: boolean
  /** 정렬을 고르지 않은 처음 상태는 null (어느 열도 강조하지 않는다) */
  sort: { col: C; dir: 'asc' | 'desc' } | null
  onSort: (c: C) => void
}

export function SortTh<C extends string>({ col, label, tip, center, plain, sort, onSort }: Props<C>) {
  if (plain) return <th className={center ? 'c' : undefined}>{label}</th>
  const on = sort?.col === col
  return (
    <th className={center ? 'c' : undefined} aria-sort={on ? (sort!.dir === 'desc' ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className={`d2th${on ? (sort!.dir === 'desc' ? ' dn' : ' up') : ''}`} title={tip} onClick={() => onSort(col)}>
        {label}
        <i>
          <b />
          <b />
        </i>
      </button>
    </th>
  )
}
