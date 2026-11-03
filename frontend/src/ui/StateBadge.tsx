/**
 * 상태 배지 (공통 UI). 색은 의미를 돕는 보조 수단이고, 의미는 항상 글자 라벨이 전한다. (디자인 가이드)
 * tone 은 assets/tokens.css 의 `--s-{tone}-*` 이름(recv·asg·info·prog·need·re·ok·urg·warn)이다. ring 이면 점이 속이 빈 링이다(끝난 문의).
 * sub 는 같은 이름의 상태를 나누는 보조 라벨이다 (예: 해결 확인 대기 / AI 안내). block 이면 배지 아래에 둔다.
 */
export function StateBadge({ tone, label, sub, block = false, ring = false }: { tone: string; label: string; sub?: string; block?: boolean; ring?: boolean }) {
  const badge = (
    <span className={`badge b-${tone}`}>
      <i className={ring ? 'ring' : undefined} />
      <span className="lb">{label}</span>
    </span>
  )
  if (!sub) return badge
  return block ? (
    <>
      {badge}
      <div className="ssub">{sub}</div>
    </>
  ) : (
    <>
      {badge}
      <span className="ssub" style={{ marginLeft: 6 }}>
        {sub}
      </span>
    </>
  )
}
