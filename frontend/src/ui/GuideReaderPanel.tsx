/**
 * 가이드 본문 읽기 패널. 오른쪽에 상세 패널로 열리고, "크게 보기"로 화면 전체 너비로 넓힐 수 있다 (그림·표가 많은 가이드용).
 * 가이드 관리의 "보기"와 문의자·담당자용 가이드 열람 화면이 함께 쓴다. 본문 API 는 docs/api/06 R-48 로 요청 중이라
 * 서버에 없으면 그 사실을 안내한다.
 */
import { useEffect, useRef, useState } from 'react'
import { getGuideContent, type GuideContent } from '../api/guides'
import { useAuth } from '../core/session'
import { Icon } from './Icon'
import { useOutsideClose } from './useOutsideClose'
import { Markdown } from './Markdown'

export interface ReaderTarget {
  id: number
  docCode: string
  title: string
  /** 특정 버전을 볼 때(관리자). 없으면 현행 버전 */
  versionId?: number
  version?: string
  /** 서버에서 받지 않고 이 본문(마크다운)을 그대로 보여 줄 때 (해결 사례로 등록한 버전의 내용) */
  text?: string
}

export function GuideReaderPanel({ target, onClose }: { target: ReaderTarget; onClose: () => void }) {
  const { user } = useAuth()
  const [wide, setWide] = useState(false)
  // 열릴 때 오른쪽에서 밀려 들어오고, 닫을 때 밀려 나간 뒤에 실제로 닫는다 (접수 상세 패널과 같다. 움직임 줄이기 설정이면 바로 닫는다)
  const [slid, setSlid] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const opener = useRef<HTMLElement | null>(null)
  const [res, setRes] = useState<{ key: string; data: GuideContent | null; error: string } | null>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const key = `${target.id}:${target.versionId ?? 'cur'}:${target.version ?? ''}`

  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeBtn.current?.focus({ preventScroll: true })
  }, [])
  const finish = () => {
    const el = opener.current
    onClose()
    if (el && el !== document.body) setTimeout(() => el.isConnected && el.focus({ preventScroll: true }), 0)
  }
  const close = () => {
    if (leaving) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) finish()
    else setLeaving(true)
  }
  useOutsideClose(close)
  useEffect(() => {
    if (!leaving) return
    const t = setTimeout(finish, 400)
    return () => clearTimeout(t)
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.querySelector('[role="dialog"]')) close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })
  useEffect(() => {
    if (!user) return
    if (target.text !== undefined) return // 미리 만든 본문은 서버에서 받지 않는다
    let alive = true
    getGuideContent(user, target, target.versionId, target.version).then((r) => {
      if (alive) setRes({ key, data: r.ok ? r.data : null, error: r.ok ? '' : r.error.message })
    })
    return () => {
      alive = false
    }
  }, [user, key, target])

  const local = target.text !== undefined ? { key, data: { docCode: target.docCode, title: target.title, version: target.version ?? '', text: target.text } as GuideContent, error: '' } : null
  const cur = local ?? (res && res.key === key ? res : null)
  return (
    <aside
      className={`detail gread${wide ? ' wide' : ''}${!slid && !leaving ? ' slide' : ''}${leaving ? ' leave' : ''}`}
      role="complementary"
      aria-label="가이드 본문"
      onAnimationEnd={() => {
        if (leaving) finish()
        else setSlid(true)
      }}
    >
      <div className="dh">
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <div style={{ minWidth: 0 }}>
            <div className="mono small muted">
              {target.docCode}
              {(cur?.data?.version || target.version) && ` · ${cur?.data?.version || target.version}`}
            </div>
            <h3>{target.title}</h3>
          </div>
          <span style={{ flex: 1 }} />
          <button type="button" className="btn sec sm ico" aria-label={wide ? '패널 크기로 줄이기' : '크게 보기'} aria-pressed={wide} title={wide ? '패널 크기로 줄이기' : '화면 전체로 크게 보기'} onClick={() => setWide((w) => !w)}>
            <Icon name={wide ? 'minimize' : 'expand'} />
          </button>
          <button type="button" ref={closeBtn} className="btn sec sm ico" aria-label="닫기" onClick={close}>
            <Icon name="x" />
          </button>
        </div>
      </div>
      <div className="db">
        {!cur ? (
          <div className="empty" role="status">
            불러오는 중이에요…
          </div>
        ) : cur.data && cur.data.text.trim() ? (
          <div className="gread-body">
            <Markdown text={cur.data.text} images={cur.data.images} />
          </div>
        ) : (
          <div className="alert info" role="status">
            <Icon name="alert" />
            <div>{cur.error || '이 가이드에는 보여 줄 본문이 없어요.'}</div>
          </div>
        )}
      </div>
    </aside>
  )
}
