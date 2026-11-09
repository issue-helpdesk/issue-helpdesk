import { expect, it } from 'vitest'
import { previewSend } from '../src/api/mock/casePreview'

it('등록된 미리보기 제안의 준비 완료 버전이 실제 문서 버전 목록에도 있다', async () => {
  // 제안 카드만 준비 완료이고 이동한 버전 표에는 초안이 없는 불일치를 방지한다.
  const result = await previewSend('/guide-clusters/107', {})
  expect(result?.ok).toBe(true)
  if (!result?.ok) throw new Error('미리보기 제안을 읽지 못했어요.')
  const detail = result.data as { targetDocument: { id: number }; registeredVersion: { id: number; version: string } }
  const versions = await previewSend(`/documents/${detail.targetDocument.id}/versions`, {})
  expect(versions?.ok).toBe(true)
  if (!versions?.ok) throw new Error('미리보기 버전을 읽지 못했어요.')
  expect((versions.data as { items: unknown[] }).items).toContainEqual(expect.objectContaining({
    ...detail.registeredVersion, isCurrent: false, ingestStatus: 'DONE', versionState: 'DRAFT',
  }))
})
