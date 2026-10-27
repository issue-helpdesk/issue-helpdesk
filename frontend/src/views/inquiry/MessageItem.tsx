/**
 * 대화 메시지 한 줄. 문의자·AI·담당자·시스템 안내를 역할에 맞게 그린다.
 * 본문은 구조화된 블록을 React 요소로만 그리며, HTML 로 해석하지 않는다.
 */
import { URGENCY_LABEL } from '../../api/catalog'
import type { ChatBlock, ChatMessage, DraftEdit, GuideSource, Inquiry, LegacyCase, ReplyRequest } from '../../api/chatTypes'
import { Fragment } from 'react'
import { formatDateTime, sourceLabel } from '../../core/format'
import { Icon } from '../../ui/Icon'
import { Pav } from '../../ui/Pav'
import type { Pose } from '../../ui/poseImages'
import { RichText } from '../../ui/RichText'
import { DraftCard } from './DraftCard'
import { TicketCard } from './TicketCard'

/** 대화 화면이 메시지 안의 버튼에 연결해 주는 동작 */
export interface ChatActions {
  reply: (req: ReplyRequest) => void
  confirmDraft: () => void
  saveDraft: (edit: DraftEdit) => Promise<boolean>
  cancelDraft: () => void
  resolve: () => void
  reject: () => void
  showSource: (s: GuideSource) => void
  showLegacy: (l: LegacyCase) => void
  /** 접수 실패 안내에 보여 줄 서비스데스크 연락처 */
  servicedesk: string
}

function Block({ b }: { b: ChatBlock }) {
  if (b.type === 'p') {
    return b.muted ? (
      <p className="small muted" style={{ marginTop: 10 }}>
        <RichText text={b.text} />
      </p>
    ) : (
      <p>
        <RichText text={b.text} />
      </p>
    )
  }
  if (b.type === 'ol') {
    return (
      <ol>
        {b.items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ol>
    )
  }
  // 긴급 징후 요약
  return (
    <div className="card w">
      <dl className="dl" style={{ margin: 0 }}>
        <dt>추천 담당 그룹</dt>
        <dd>{b.groupName}</dd>
        <dt>긴급도</dt>
        <dd>
          <span className={`pri-${b.urgency.toLowerCase()}`}>
            {b.urgency} · {URGENCY_LABEL[b.urgency]}
          </span>
        </dd>
        <dt>판단 근거</dt>
        <dd>{b.urgencyReasons.join(' · ')}</dd>
      </dl>
    </div>
  )
}

interface Props {
  inquiry: Inquiry
  message: ChatMessage
  busy: boolean
  actions: ChatActions
  /** 방금 생긴 답변이면 아래에서 올라오며 나타난다 (한 번) */
  fresh?: boolean
  /** 답변 아바타의 잇슈 모습과, 모습이 바뀐 첫 답변에 붙는 상태 글 */
  pose?: Pose
  poseText?: string
  /** 이어가기 창을 거치기 전에는 지난 선택 버튼을 잠가 둔다 */
  replyLock?: boolean
  /** 이어가기 뒤 대화 맨 아래에 다시 보이는 버튼이 있으면 이 메시지의 버튼은 감춘다 */
  hideReplies?: boolean
}

export function MessageItem({ inquiry, message: m, busy, actions, fresh = false, pose = 'base', poseText = '', replyLock = false, hideReplies = false }: Props) {
  if (m.role === 'user') return <div className="msg u">{m.text}</div>
  if (m.role === 'sys') {
    // 안내 문구는 첫 줄이 제목, 나머지가 설명이다 (민감정보 가림 안내, 보안 사고 안내 등). tone 으로 색을 구분한다.
    const [head, ...rest] = (m.text ?? '').split('\n')
    if (!rest.length) return <div className="msg sys">{m.text}</div>
    return (
      <div className={`msg sys note${m.tone ? ` ${m.tone}` : ''}`}>
        <b>{head}</b>
        <span>
          {rest.map((line, i) => (
            <Fragment key={i}>
              {i > 0 && <br />}
              {line}
            </Fragment>
          ))}
        </span>
      </div>
    )
  }

  if (m.role === 'staff') {
    return (
      <div className="msg a staff">
        <span className="sav" aria-hidden="true">
          {(m.from ?? '').slice(0, 1)}
        </span>
        <div className="body">
          <div className="sh">
            <b>{(m.from ?? '').replace(' 담당자', '')}</b>
            <span className="tag stf">담당자{m.groupName ? ` · ${m.groupName}` : ''}</span>
            <span className="small muted">
              {m.kind}{m.createdAt ? ` · ${formatDateTime(m.createdAt)}` : ''}
            </span>
          </div>
          <div className="sb">{m.text}</div>
        </div>
      </div>
    )
  }

  // AI 가 답변을 준비하는 중
  if (m.typing) {
    return (
      <div className="msg a">
        <Pav pose={pose} />
        <div className="body" role="status">
          <span className="dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>{' '}
          <span className="muted small">{m.typing.label}</span>
        </div>
      </div>
    )
  }

  // 같은 종류의 초안 카드가 여러 번 있어도 마지막 하나만 조작할 수 있다
  const lastDraftId = [...inquiry.messages].reverse().find((x) => x.card === 'draft')?.id

  return (
    <div className={`msg a${fresh ? ' rise' : ''}`}>
      <Pav pose={pose} />
      <div className="body">
        {poseText && <div className="pst">{poseText}</div>}
        {m.blocks?.map((b, i) => (
          <Block key={i} b={b} />
        ))}

        {m.legacy && <LegacyButton legacy={m.legacy} onOpen={actions.showLegacy} />}
        {m.sources && (
          <div>
            {m.sources.map((s) => (
              <SourceButton key={`${s.docCode}${s.section}`} source={s} onOpen={actions.showSource} />
            ))}
          </div>
        )}

        {m.card === 'draft' && inquiry.draft && (
          <DraftCard
            draft={inquiry.draft}
            state={inquiry.draftState}
            note={inquiry.draftNote}
            active={m.id === lastDraftId}
            busy={busy}
            onConfirm={actions.confirmDraft}
            onSave={actions.saveDraft}
            onCancel={actions.cancelDraft}
          />
        )}

        {m.card === 'ticket' && (m.ticketSnapshot ?? inquiry.ticket) && (
          <TicketCard ticket={(m.ticketSnapshot ?? inquiry.ticket)!} readOnly={!!m.ticketSnapshot} busy={busy} onResolve={actions.resolve} onReject={actions.reject} />
        )}

        {m.card === 'savefail' && (
          <div className="alert err" style={{ marginTop: 12 }} role="alert">
            <Icon name="alert" />
            <div>
              <b>접수를 저장하지 못했어요.</b>
              <br />
              작성한 내용은 그대로 보관했어요. 잠시 후 다시 시도하거나 아래 경로로 접수해 주세요.
              <br />
              <span className="small">
                · 서비스데스크 {actions.servicedesk}
                <br />· 그룹웨어 IT 요청 메뉴
              </span>
            </div>
          </div>
        )}

        {m.replies && !hideReplies && (
          <div className="replies">
            {m.replies.map((r) => (
              <button
                key={`${r.action}${r.label}`}
                type="button"
                className={`chip${r.primary ? ' on' : ''}`}
                disabled={m.locked || busy || replyLock}
                onClick={() => actions.reply({ messageId: m.id, action: r.action, arg: r.arg } satisfies ReplyRequest)}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SourceButton({ source: s, onOpen }: { source: GuideSource; onOpen: (s: GuideSource) => void }) {
  return (
    <button type="button" className="src" onClick={() => onOpen(s)}>
      <Icon name="file" size={16} />
      {sourceLabel(s)}
    </button>
  )
}

function LegacyButton({ legacy, onOpen }: { legacy: LegacyCase; onOpen: (l: LegacyCase) => void }) {
  return (
    <div>
      <button type="button" className="src" onClick={() => onOpen(legacy)}>
        <Icon name="file" size={16} />
        과거 처리 사례 참고
      </button>
    </div>
  )
}
