/**
 * 알림 종 (공통 UI): 오른쪽 위에서 안 읽은 알림 수를 보여 주고, 누르면 내 알림 목록을 연다. (docs/api/05 NT-01~04)
 * - 알림 종류는 두 가지다: 담당자에게 "새 티켓이 배정됐어요"(ASSIGNED), 문의자에게 "문의가 처리 완료됐어요"(FIN). 내용은 서버가 저장하지 않아 종류로 문구를 만든다.
 * - 안 읽은 알림은 색에만 기대지 않고 굵은 제목과 "안 읽음" 글자로 보인다. 아이콘이나 프로필 이미지는 쓰지 않는다.
 * - 알림을 누르면 그 티켓(담당자) 또는 문의(문의자)로 이동하고, 그 접수의 알림은 모두 읽음이 된다(NT-04).
 * - Esc·바깥 누르기로 닫으면 종 버튼으로 초점이 돌아온다.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listNotifications, markTicketRead, refreshUnread, watchUnread, type AppNotification } from '../api/notifications'
import { formatRelative } from '../core/format'
import { Icon } from './Icon'

const TITLE: Record<AppNotification['kind'], string> = { ASSIGNED: '새 티켓이 배정됐어요', FIN: '문의가 처리 완료됐어요' }
const LOAD_FAIL = '알림을 불러오지 못했어요. 연결 상태를 확인한 뒤 다시 불러와 주세요.'

export function NotificationBell() {
  const navigate = useNavigate()
  const [count, setCount] = useState(0)
  const [open, setOpen] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [items, setItems] = useState<AppNotification[] | null>(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => watchUnread((c) => setCount(c.count)), [])

  // 열려 있는 동안 목록을 읽는다 (조건을 바꾸면 처음부터, 안 읽은 수가 바뀌면 다시)
  useEffect(() => {
    if (!open) return
    let alive = true
    listNotifications(unreadOnly, page).then((r) => {
      if (!alive) return
      if (!r.ok) return setError(r.error.message || LOAD_FAIL)
      setError('')
      setItems((cur) => (page === 1 || !cur ? r.data.items : [...cur, ...r.data.items]))
      setMore(r.data.hasMore)
    })
    return () => {
      alive = false
    }
  }, [open, unreadOnly, page, count])

  useEffect(() => {
    if (!open) return
    const out = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      box.current?.querySelector<HTMLElement>('.bellbtn')?.focus()
    }
    document.addEventListener('pointerdown', out)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', out)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const toggle = () => {
    if (!open) {
      setItems(null)
      setPage(1)
      setError('')
    }
    setOpen((o) => !o)
  }

  const go = async (n: AppNotification) => {
    setOpen(false)
    if (!n.readAt) {
      await markTicketRead(n.ticketId)
      refreshUnread()
    }
    navigate(n.kind === 'ASSIGNED' ? `/queue/${n.ticketId}` : `/chat/${n.inquiryId}`)
  }

  const reload = () => {
    setError('')
    setItems(null)
    setPage(1)
    refreshUnread()
  }

  return (
    <div className="bell" ref={box}>
      <button type="button" className="bellbtn" aria-haspopup="dialog" aria-expanded={open} aria-label={count > 0 ? `알림 ${count}건` : '알림'} onClick={toggle}>
        <Icon name="bell" />
        {count > 0 && (
          <span className="bpip" aria-hidden="true">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {open && (
        <div className="bpop" role="dialog" aria-label="알림">
          <div className="bhd">
            <b>알림</b>
            <label className="bchk">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => {
                  setUnreadOnly(e.target.checked)
                  setPage(1)
                  setItems(null)
                }}
              />{' '}
              안 읽음만
            </label>
          </div>
          {error ? (
            <div className="bem" role="alert">
              <b>{error}</b>
              <button type="button" className="btn sec sm" onClick={reload}>
                다시 불러오기
              </button>
            </div>
          ) : items === null ? (
            <div className="bem" role="status">
              알림을 불러오는 중이에요.
            </div>
          ) : items.length === 0 ? (
            <div className="bem">
              <b>{unreadOnly ? '안 읽은 알림이 없어요' : '새 알림이 없어요'}</b>
              <span>배정되거나 처리가 끝나면 여기에 모여요.</span>
            </div>
          ) : (
            <ul className="blist">
              {items.map((n) => (
                <li key={n.id}>
                  <button type="button" className={`bitem${n.readAt ? ' read' : ''}`} onClick={() => void go(n)}>
                    <span className="bt">
                      {TITLE[n.kind]}
                      {!n.readAt && <span className="bnew">안 읽음</span>}
                    </span>
                    <span className="bs">
                      {n.receiptNo}
                      {n.summary ? ` · ${n.summary}` : ''}
                    </span>
                    <time className="bw" dateTime={n.createdAt}>
                      {formatRelative(n.createdAt)}
                    </time>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {more && !error && (
            <div className="bmore">
              <button type="button" className="btn sec sm" onClick={() => setPage((p) => p + 1)}>
                더 보기
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
