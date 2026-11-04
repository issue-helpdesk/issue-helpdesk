/**
 * 문의에서 AI 가 답에 쓴 가이드 (관리자 AI 처리 상세).
 *   GET /inquiries/{id}/messages   AI 답변마다 붙은 출처(sources: 문서 코드·버전·위치·종류)
 * 문의 목록(IQ-02)에는 가이드가 없어서 목록에는 칼럼을 두지 않고, 상세 패널을 열 때만 읽는다.
 * 같은 문서·위치는 한 번만 보여 주고, 발췌문은 쓰지 않는다. 모의 모드는 시연 행의 가이드 글을 풀어서 쓴다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import { ok, type ApiResult } from './types'

export interface UsedGuide {
  /** 과거 처리 사례(LEGACY)는 문서 코드가 없다 */
  docCode: string | null
  version: string | null
  location: string | null
  kind: 'DOCUMENT' | 'LEGACY'
}

interface SourceItem {
  sourceKind: 'DOCUMENT' | 'LEGACY'
  docCode: string | null
  version: string | null
  location: string | null
}

/** 시연 행의 가이드 글("IT-NET-001 VPN 접속 장애 대응 가이드 v2")에서 코드·버전을 뽑는다. '-' 는 없음 */
export function guideFromText(text: string): UsedGuide[] {
  if (!text || text === '-') return []
  const m = text.match(/^(\S+)\s.*?(v\d[\w.]*)?$/)
  return m ? [{ docCode: m[1], version: m[2] ?? null, location: null, kind: 'DOCUMENT' }] : []
}

export async function listUsedGuides(inquiryId: number | null, mockText = ''): Promise<ApiResult<UsedGuide[]>> {
  if (USE_MOCK_INQUIRY || inquiryId === null) return ok(guideFromText(mockText))
  const r = await request<{ items: { sources?: SourceItem[] }[] }>(`/inquiries/${inquiryId}/messages`)
  if (!r.ok) return r
  const seen = new Set<string>()
  const out: UsedGuide[] = []
  for (const m of r.data.items) {
    for (const s of m.sources ?? []) {
      const key = `${s.sourceKind}|${s.docCode}|${s.version}|${s.location}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ docCode: s.docCode, version: s.version, location: s.location, kind: s.sourceKind })
    }
  }
  return ok(out)
}
