/**
 * 상태 배지 (공통 UI). 색은 의미를 돕는 보조 수단이고, 의미는 항상 글자 라벨이 전한다. (디자인 가이드)
 * tone 은 assets/tokens.css 의 `--s-{tone}-*` 이름(recv·asg·prog·need·re·ok·urg·warn)이다.
 */
export function StateBadge({ tone, label }: { tone: string; label: string }) {
  return (
    <span className={`badge b-${tone}`}>
      <i />
      <span className="lb">{label}</span>
    </span>
  )
}
