/**
 * 해결 사례 제안의 "넣을 문서 변경 / 문서 연결" 창 (관리자, 서버 연결 전용). docs/api/04 GC-08.
 * - 항목 추가·SEC 직접 검토: 넣을 문서(현행이 있는 임직원용 가이드)를 고른다.
 * - 변경: 문서와 함께 바꿀 항목 번호(예: 3.3)를 적는다. 같은 문서에서 항목만 옮겨도 된다.
 * - 새 가이드: 버전이 하나도 없는 임직원용 가이드만 연결된다. 없으면 이 창에서 문서만 새로 만든다(DC-02, 파일은 올리지 않는다).
 * 문서를 옮기면 초안 글은 그대로 두고 기준을 새로 잡는다. 변경은 충돌이 생길 수 있어, 패널에서 새 현행 원문과 비교해 고친 뒤 저장해야 등록된다.
 */
import { useEffect, useId, useState } from 'react'
import { changeCaseTarget } from '../../api/caseClusters'
import { createGuideDocument, listGuides, nextDocCode, type Guide } from '../../api/guides'
import type { CaseItem } from '../../api/mock/caseGuides'
import { useAuth } from '../../core/session'
import { Modal } from '../../ui/Modal'
import { SelectBox } from '../../ui/SelectBox'

const SECTION_RE = /^\d+\.\d+$/

export function CaseTargetDialog({ c, onClose, onDone }: { c: CaseItem; onClose: () => void; onDone: (message: string) => void }) {
  const { user } = useAuth()
  const uid = useId()
  const isNew = c.kind === 'new'
  const isChange = c.server?.judgment === 'CHANGE'
  const [guides, setGuides] = useState<Guide[] | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [mode, setMode] = useState<'pick' | 'create'>('pick')
  const [docId, setDocId] = useState('')
  const [section, setSection] = useState(c.target?.section ?? '')
  const [code, setCode] = useState('')
  const [title, setTitle] = useState(c.title ?? c.topic)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [fieldErr, setFieldErr] = useState<{ doc?: string; section?: string; code?: string; title?: string }>({})

  useEffect(() => {
    if (!user) return
    let alive = true
    listGuides(user).then((r) => {
      if (!alive) return
      if (!r.ok) return setLoadErr(r.error.message)
      setGuides(r.data)
      setCode((cur) => cur || nextDocCode(r.data, c.cat))
    })
    return () => {
      alive = false
    }
  }, [user, c.cat])

  // 넣을 수 있는 문서: 항목 추가·변경·SEC 는 현행이 있는 임직원용 가이드, 새 가이드는 현행(버전)이 없는 가이드
  const candidates = (guides ?? [])
    .filter((g) => g.docType !== 'MANUAL' && g.isActive && (isNew ? !g.current : !!g.current && (g.current.scope === undefined || g.current.scope === '전 직원')))
    .sort((a, b) => Number(b.cat === c.cat) - Number(a.cat === c.cat) || a.docCode.localeCompare(b.docCode))
  const options = candidates.map((g) => ({ value: String(g.id), label: `${g.docCode} ${g.title}${g.current ? ` · 현행 ${g.current.version}` : ''}`, accent: g.cat }))

  const submit = async () => {
    if (!user || !c.server || busy) return
    const fe: typeof fieldErr = {}
    if (mode === 'pick' && !docId) fe.doc = '넣을 문서를 골라 주세요.'
    if (mode === 'create') {
      if (!/^IT-[A-Z]{2,4}-\d{3}$/.test(code.trim().toUpperCase())) fe.code = '문서 번호 형식이 맞지 않아요. 예) IT-NET-004'
      if (!title.trim()) fe.title = '제목을 입력해 주세요.'
    }
    if (isChange && !SECTION_RE.test(section.trim())) fe.section = '바꿀 항목 번호를 적어 주세요. 예) 3.3'
    setFieldErr(fe)
    if (Object.keys(fe).length) return
    setBusy(true)
    setErr('')
    let target = Number(docId)
    let created = ''
    if (mode === 'create') {
      const d = await createGuideDocument(user, { docCode: code, title, cat: c.cat })
      if (!d.ok) {
        setBusy(false)
        return setErr(d.error.message)
      }
      target = d.data.id
      created = `${d.data.docCode} 문서를 만들고 `
    }
    const r = await changeCaseTarget(c.id, c.server.draftRevision, target, isChange ? section : undefined)
    setBusy(false)
    if (!r.ok) {
      // 문서는 만들어졌으니 다시 만들지 않도록 고른 상태로 바꾼다
      if (mode === 'create') {
        setMode('pick')
        setDocId(String(target))
        setGuides(null)
        void listGuides(user).then((g) => g.ok && setGuides(g.data))
      }
      return setErr(r.error.message)
    }
    const conflicts = r.data.server?.conflicts?.length ?? 0
    onDone(`${created}넣을 문서를 바꿨어요.${conflicts ? ' 새 현행과 달라진 내용이 있어요. 비교해서 초안을 고쳐 저장해 주세요.' : ''}`)
  }

  return (
    <Modal title={isNew ? '새 가이드 문서 연결' : '넣을 문서 변경'} variant="form" onClose={onClose}>
      <p className="small muted" style={{ margin: 0 }}>
        {isNew
          ? '새 가이드는 버전이 하나도 없는 가이드 문서에 넣어요. 연결한 문서에 v1.0으로 등록돼요.'
          : '초안 글은 그대로 두고, 넣을 문서(와 항목)만 바꿔요. 새 문서의 현행 가이드가 기준이 돼요.'}
      </p>

      {isNew && (
        <div className="seg" role="group" aria-label="연결 방법">
          <button type="button" className={mode === 'pick' ? 'on' : ''} aria-pressed={mode === 'pick'} onClick={() => setMode('pick')}>
            만들어 둔 문서 고르기
          </button>
          <button type="button" className={mode === 'create' ? 'on' : ''} aria-pressed={mode === 'create'} onClick={() => setMode('create')}>
            새 문서 만들기
          </button>
        </div>
      )}

      {mode === 'pick' ? (
        <div className="field">
          <label htmlFor={`${uid}-doc`}>넣을 문서</label>
          {loadErr ? (
            <div className="ferr" role="alert">
              {loadErr}
            </div>
          ) : (
            <SelectBox
              id={`${uid}-doc`}
              value={docId}
              invalid={!!fieldErr.doc}
              placeholder={guides === null ? '불러오는 중이에요…' : '문서를 골라 주세요'}
              empty={isNew ? '연결할 수 있는 문서가 없어요. "새 문서 만들기"로 만들어 주세요.' : '넣을 수 있는 가이드가 없어요.'}
              options={options}
              onChange={(v) => {
                setDocId(v)
                setFieldErr((f) => ({ ...f, doc: undefined }))
              }}
            />
          )}
          {fieldErr.doc && (
            <div className="ferr" role="alert">
              {fieldErr.doc}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor={`${uid}-code`}>문서 번호</label>
            <input id={`${uid}-code`} className={`inp${fieldErr.code ? ' err' : ''}`} value={code} maxLength={20} autoComplete="off" aria-invalid={!!fieldErr.code} onChange={(e) => setCode(e.target.value)} />
            {fieldErr.code && (
              <div className="ferr" role="alert">
                {fieldErr.code}
              </div>
            )}
          </div>
          <div className="field">
            <label htmlFor={`${uid}-title`}>제목</label>
            <input id={`${uid}-title`} className={`inp${fieldErr.title ? ' err' : ''}`} value={title} maxLength={200} autoComplete="off" aria-invalid={!!fieldErr.title} onChange={(e) => setTitle(e.target.value)} />
            {fieldErr.title && (
              <div className="ferr" role="alert">
                {fieldErr.title}
              </div>
            )}
          </div>
          <p className="small muted" style={{ margin: 0 }}>
            임직원용 가이드 문서만 만들어요. 파일은 올리지 않고, 등록할 때 이 제안의 초안으로 v1.0이 만들어져요.
          </p>
        </>
      )}

      {isChange && (
        <div className="field">
          <label htmlFor={`${uid}-sec`}>바꿀 항목 번호</label>
          <input id={`${uid}-sec`} className={`inp${fieldErr.section ? ' err' : ''}`} value={section} placeholder="예) 3.3" autoComplete="off" aria-invalid={!!fieldErr.section} onChange={(e) => setSection(e.target.value)} />
          {fieldErr.section && (
            <div className="ferr" role="alert">
              {fieldErr.section}
            </div>
          )}
        </div>
      )}

      {err && (
        <div className="ferr" role="alert">
          {err}
        </div>
      )}
      <div className="acts">
        <button type="button" className="btn sec" onClick={onClose}>
          취소
        </button>
        <button type="button" className="btn pri" disabled={busy || (mode === 'pick' && guides === null && !loadErr)} onClick={() => void submit()}>
          {busy ? '바꾸는 중이에요…' : isNew ? (mode === 'create' ? '만들고 연결' : '연결') : '문서 변경'}
        </button>
      </div>
    </Modal>
  )
}
