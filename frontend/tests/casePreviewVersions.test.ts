import { beforeEach, expect, it, vi } from 'vitest'
let previewSend: typeof import('../src/api/mock/casePreview').previewSend
beforeEach(async () => {
  vi.resetModules()
  previewSend = (await import('../src/api/mock/casePreview')).previewSend
})

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

it('미리보기 현행 전환을 실제 서버로 넘기지 않고 문서와 제안 상태에 함께 반영한다', async () => {
  const result = await previewSend('/documents/1/versions/14', { method: 'PATCH', body: JSON.stringify({ isCurrent: true }) })
  expect(result).toMatchObject({ ok: true, data: { id: 14, isCurrent: true, versionState: 'CURRENT' } })
  const versions = await previewSend('/documents/1/versions', {})
  expect(versions).toMatchObject({ ok: true, data: { items: [expect.objectContaining({ id: 14, isCurrent: true }), expect.objectContaining({ id: 12, isCurrent: false, versionState: 'EXPIRED' })] } })
  expect(await previewSend('/guide-clusters/107', {})).toMatchObject({ ok: true, data: { status: 'APPLIED', registeredVersion: { isCurrent: true } } })
  expect(await previewSend('/documents/1/versions/9999', { method: 'PATCH', body: '{"isCurrent":true}' })).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_FOUND' } })
})

it('거절한 제안의 버전은 미리보기에서도 현행으로 전환하지 않는다', async () => {
  await previewSend('/guide-clusters/107/reject', { method: 'POST', body: '{"reason":"중복 제안"}' })
  expect(await previewSend('/documents/1/versions/14', { method: 'PATCH', body: '{"isCurrent":true}' })).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_HAS_REJECTED_CLUSTER' } })
})

it('새로 등록한 미리보기 초안도 문서 버전 목록에 추가한다', async () => {
  const registered = await previewSend('/guide-clusters/101/register', { method: 'POST', body: '{"draftRevision":1,"viewScope":"AGENT","transferPolicy":"BLOCKED"}' })
  expect(registered?.ok).toBe(true)
  if (!registered?.ok) throw new Error('미리보기 등록 실패')
  const id = (registered.data as { registeredVersion: { id: number } }).registeredVersion.id
  expect(await previewSend('/documents/1/versions', {})).toMatchObject({ ok: true, data: { items: expect.arrayContaining([expect.objectContaining({ id, ingestStatus: 'PENDING', versionState: 'DRAFT', viewScope: 'AGENT', transferPolicy: 'BLOCKED' })]) } })
  expect(await previewSend(`/documents/1/versions/${id}`, { method: 'PATCH', body: '{"isCurrent":true}' })).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_NOT_READY' } })
})
