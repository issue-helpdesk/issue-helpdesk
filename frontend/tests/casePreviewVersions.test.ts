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

it('다른 버전이 먼저 현행이 된 초안은 다시 맞추고 재등록한 뒤 전환한다', async () => {
  vi.useFakeTimers()
  const send = async (path: string, body: object) => {
    const pending = previewSend(path, { method: 'POST', body: JSON.stringify(body) })
    await vi.advanceTimersByTimeAsync(200)
    return pending
  }
  const activate = async (id: number) => {
    const pending = previewSend(`/documents/1/versions/${id}`, { method: 'PATCH', body: '{"isCurrent":true}' })
    await vi.advanceTimersByTimeAsync(200)
    return pending
  }
  try {
    const first = await send('/guide-clusters/101/register', { draftRevision: 1 })
    if (!first?.ok) throw new Error('첫 등록 실패')
    const oldId = (first.data as { registeredVersion: { id: number } }).registeredVersion.id
    await activate(14) // v2.2를 만든 뒤 다른 제안의 v2.1이 먼저 현행이 된다.
    await vi.advanceTimersByTimeAsync(4000)
    expect(await activate(oldId)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_BASE_CHANGED' } })
    expect(await send('/guide-clusters/101/rebase', { draftRevision: 1 })).toMatchObject({ ok: true, data: { registeredVersion: null, baseChanged: false, baseVersion: { id: 14 }, draftRevision: 2 } })
    expect(await activate(oldId)).toMatchObject({ ok: false, error: { code: 'DOCUMENT_VERSION_ORPHANED' } })
    const second = await send('/guide-clusters/101/register', { draftRevision: 2 })
    if (!second?.ok) throw new Error('재등록 실패')
    const fresh = (second.data as { registeredVersion: { id: number; version: string } }).registeredVersion
    expect(fresh.version).toBe('v2.3')
    expect(fresh.id).not.toBe(oldId)
    await vi.advanceTimersByTimeAsync(4000)
    expect(await activate(fresh.id)).toMatchObject({ ok: true, data: { isCurrent: true } })
  } finally {
    vi.useRealTimers()
  }
})
