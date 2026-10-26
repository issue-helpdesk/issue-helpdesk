/**
 * 시각 표시 도우미. API 는 시각을 ISO 8601(+09:00)로 주고, '어제' 같은 표시는 화면이 계산한다. (docs/07.API_계약서.md)
 */

const pad = (n: number) => String(n).padStart(2, '0')

/** 지금 시각을 ISO 8601 로 (시연 데이터용) */
export const nowIso = () => new Date().toISOString()

/** 지금부터 n일 전 시각을 ISO 8601 로 (시연 데이터용) */
export const daysAgoIso = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

/** 날짜·시각 표시 (예: 10.19 14:05) */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 최근 활동 표시 (예: 방금, 3시간 전, 어제, 6일 전, 10.02) */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const min = Math.floor((now.getTime() - d.getTime()) / 60_000)
  if (min < 1) return '방금'
  if (min < 60) return `${min}분 전`
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000)
  if (days === 0) return `${Math.floor(min / 60)}시간 전`
  if (days === 1) return '어제'
  if (days < 30) return `${days}일 전`
  return `${pad(d.getMonth() + 1)}.${pad(d.getDate())}`
}

/** Guide 출처 한 줄 표시 (예: IT-NET-001 VPN 접속 장애 대응 가이드 v2 · 3.1) */
export function sourceLabel(s: { docCode: string; title: string; version: string; section: string }): string {
  return [s.docCode, s.title, s.version].filter(Boolean).join(' ') + (s.section ? ` · ${s.section}` : '')
}
