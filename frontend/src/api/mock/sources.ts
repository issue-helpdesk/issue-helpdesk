/**
 * 시연용 출처 도우미. "IT-NET-001 VPN 접속 장애 대응 가이드 v2 · 3.1" 같은 표기를 GuideSource 객체로 바꾼다.
 * 실제 API 는 처음부터 GuideSource 객체를 준다.
 */
import type { GuideSource } from '../chatTypes'

export function guideSource(label: string, excerpt = ''): GuideSource {
  const m = /^(\S+)\s+(.+?)\s+(v\d+(?:\.\d+)?)\s*·\s*(\S+)$/.exec(label)
  if (!m) return { docCode: '', title: label, version: '', section: '', excerpt }
  return { docCode: m[1], title: m[2], version: m[3], section: m[4], excerpt }
}
