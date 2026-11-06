/**
 * 가이드 열람 (문의자·담당자, /docs). 내가 볼 수 있는 가이드의 현행 버전을 분류별로 훑고, 가이드 박스를 눌러 본문을 오른쪽 패널에서 읽는다.
 * 관리 화면(가이드 관리)과 같은 분류별 접이식 목록이고, 버전·외부 전송 같은 관리 정보는 보이지 않는다. 가이드 박스를 누르면 본문이 열린다.
 * 목록은 문서 API(DC-01, 열람 범위 안의 현행 버전만), 본문은 R-48(요청 중)로 읽는다. (api/guides.ts)
 */
import { useEffect, useMemo, useState } from 'react'
import { CATEGORIES } from '../../api/catalog'
import type { CategoryCode } from '../../api/chatTypes'
import { guideLabel, listReadableGuides, type Guide } from '../../api/guides'
import titleOps from '../../assets/mascot/title-ops.webp'
import { useAuth } from '../../core/session'
import { Collapse } from '../../ui/Collapse'
import { GuideReaderPanel, type ReaderTarget } from '../../ui/GuideReaderPanel'
import { Icon } from '../../ui/Icon'
import { ScopeBadge } from '../../ui/ScopeBadge'
import { Topbar } from '../../ui/Topbar'

export function GuideLibraryView() {
  const { user } = useAuth()
  const [guides, setGuides] = useState<Guide[] | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [catOpen, setCatOpen] = useState<Record<string, boolean>>({})
  const [reader, setReader] = useState<ReaderTarget | null>(null)

  useEffect(() => {
    if (!user) return
    let alive = true
    listReadableGuides(user).then((r) => {
      if (!alive) return
      if (r.ok) {
        setGuides(r.data)
        setError('')
      } else setError(r.error.message)
    })
    return () => {
      alive = false
    }
  }, [user, reload])

  const cats = useMemo(() => (Object.keys(CATEGORIES) as CategoryCode[]).filter((c) => guides?.some((g) => g.cat === c)), [guides])
  const allOpen = cats.length > 0 && cats.every((c) => catOpen[c])

  return (
    <>
      <main className="main">
        <Topbar title="가이드" sub="내가 볼 수 있는 사내 가이드" lead={<img className="tti" src={titleOps} alt="" width={56} height={56} />} />
        <div className="scroll">
          <div className="page">
            <div className="phead">
              <div className="eyebrow">IT GUIDE</div>
              <h1>사내 가이드를 찾아 읽어요</h1>
              <p className="muted" style={{ marginTop: 4 }}>
                본인에게 열람이 허용된 가이드의 현행 버전만 보여요. 가이드를 읽어도 문의가 접수되지는 않아요.
              </p>
            </div>

            {error && (
              <div className="alert err" role="alert">
                <Icon name="alert" />
                <div>
                  {error}{' '}
                  <button type="button" className="btn ghost sm" onClick={() => setReload((n) => n + 1)}>
                    다시 시도
                  </button>
                </div>
              </div>
            )}
            {guides === null && !error && (
              <div className="empty" role="status">
                불러오는 중이에요…
              </div>
            )}
            {guides?.length === 0 && <div className="empty">볼 수 있는 가이드가 없어요.</div>}

            {guides && guides.length > 0 && (
              <>
                <div className="row" style={{ justifyContent: 'space-between', margin: 0 }}>
                  <span className="small muted">
                    분류 {cats.length}개 · 가이드 {guides.length}개
                  </span>
                  <button type="button" className="btn ghost sm" onClick={() => setCatOpen(allOpen ? {} : Object.fromEntries(cats.map((c) => [c, true])))}>
                    {allOpen ? '모두 접기' : '모두 펼치기'}
                  </button>
                </div>
                <div className="gseclist">
                  {cats.map((c) => {
                    const gs = guides.filter((g) => g.cat === c)
                    const open = !!catOpen[c]
                    return (
                      <section key={c} className={`gsec${open ? ' open' : ''}`}>
                        <button type="button" className="gcb" aria-expanded={open} onClick={() => setCatOpen((m) => ({ ...m, [c]: !m[c] }))}>
                          <span className={`tag c-${c} gcbar`} aria-hidden="true" />
                          <span className="gcm">
                            <b>{CATEGORIES[c].name}</b>
                            <small>
                              {guideLabel(gs[0])}
                              {gs.length > 1 ? ` 외 ${gs.length - 1}개` : ''}
                            </small>
                          </span>
                          <span className="gcr">
                            <span className="gcn">{gs.length}개</span>
                            <span className={`gchv${open ? ' on' : ''}`} aria-hidden="true">
                              <Icon name="chevronDown" />
                            </span>
                          </span>
                        </button>
                        <Collapse open={open} className="gcp">
                          {open &&
                            gs.map((g) => (
                              <div className="gprow" key={g.id}>
                                <div className="gprh">
                                  {/* 가이드 박스 전체가 단추다: 누르면 오른쪽 패널에 본문이 열린다 */}
                                  <button type="button" className="grb" aria-label={`${g.docCode} 본문 보기`} onClick={() => setReader({ id: g.id, docCode: g.docCode, title: g.title, version: g.current?.version })}>
                                    <span className="grt">
                                      <span className="grtl">
                                        <b>{guideLabel(g)}</b>
                                      </span>
                                      <div className="small muted">현행 {g.current?.version}</div>
                                    </span>
                                    {/* 라벨은 담당자 이상만 볼 수 있는 가이드에만 붙인다 (문의자에게는 모두 전 직원용이라 의미가 없다) */}
                                    <span className="gbs">{g.current?.scope === '담당자 이상' && <ScopeBadge scope="담당자 이상" />}</span>
                                  </button>
                                </div>
                              </div>
                            ))}
                        </Collapse>
                      </section>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      </main>
      {reader && <GuideReaderPanel target={reader} onClose={() => setReader(null)} />}
    </>
  )
}
