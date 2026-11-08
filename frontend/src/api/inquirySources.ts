/**
 * 문의에서 AI 가 답에 쓴 가이드 (관리자 AI 처리 상세).
 *   GET /inquiries/{id}/messages   AI 답변마다 붙은 출처(sources: 문서 코드·버전·위치·종류)
 * 문의 목록(IQ-02)에는 가이드가 없어서 목록에는 칼럼을 두지 않고, 상세 패널을 열 때만 읽는다.
 * 같은 문서·위치는 한 번만 보여 준다. 과거 처리 사례(LEGACY)는 문서 코드가 없어 본문(excerpt)이 같은지로 구분하고, 화면이 그 본문을 짧게 펼쳐 보인다.
 * 모의 모드는 시연 행의 가이드 글을 풀어서 쓴다.
 */
import { request } from '../core/apiClient'
import { USE_MOCK_INQUIRY } from '../core/config'
import type { GuideImageRef } from './chatTypes'
import { ok, type ApiResult } from './types'

export interface UsedGuide {
  /** 과거 처리 사례(LEGACY)는 문서 코드가 없다 */
  docCode: string | null
  version: string | null
  location: string | null
  kind: 'DOCUMENT' | 'LEGACY'
  /** 근거로 쓴 본문. 과거 처리 사례를 펼쳐 보이거나 가이드 출처를 미리 볼 때 쓴다 */
  excerpt: string | null
  /** 본문의 `[그림]` 줄에 대응하는 그림 (DC-11) */
  images?: GuideImageRef[]
}

interface SourceItem {
  sourceKind: 'DOCUMENT' | 'LEGACY'
  docCode: string | null
  version: string | null
  location: string | null
  excerpt?: string | null
  images?: GuideImageRef[]
}

/** 시연 행의 가이드 글("IT-NET-001 VPN 접속 장애 대응 가이드 v2")에서 코드·버전을 뽑는다. '-' 는 없음 */
function guideFromText(text: string): UsedGuide[] {
  if (!text || text === '-') return []
  const m = text.match(/^(\S+)\s.*?(v\d[\w.]*)?$/)
  return m ? [{ docCode: m[1], version: m[2] ?? null, location: null, kind: 'DOCUMENT', excerpt: null }] : []
}

/** 모의 모드에서는 시연 행의 가이드 글과 과거 사례 본문(mockCases)을 그대로 푼다 */
export async function listUsedGuides(inquiryId: number | null, mockText = '', mockCases: string[] = []): Promise<ApiResult<UsedGuide[]>> {
  if (USE_MOCK_INQUIRY || inquiryId === null) return ok([...guideFromText(mockText), ...mockCases.map((c): UsedGuide => ({ docCode: null, version: null, location: null, kind: 'LEGACY', excerpt: c }))])
  const r = await request<{ items: { sources?: SourceItem[] }[] }>(`/inquiries/${inquiryId}/messages`)
  if (!r.ok) return r
  const seen = new Set<string>()
  const out: UsedGuide[] = []
  for (const m of r.data.items) {
    for (const s of m.sources ?? []) {
      // 과거 처리 사례는 문서 코드·위치가 모두 비어 있어서 본문으로 구분한다 (안 그러면 사례가 몇 건이든 하나로 합쳐진다)
      const key = s.sourceKind === 'LEGACY' ? `LEGACY|${s.excerpt ?? ''}` : `${s.sourceKind}|${s.docCode}|${s.version}|${s.location}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ docCode: s.docCode, version: s.version, location: s.location, kind: s.sourceKind, excerpt: s.excerpt ?? null, images: s.images?.length ? s.images : undefined })
    }
  }
  return ok(out)
}
