/**
 * 시연용 문의 시작 데이터와 초기화.
 * 문의자 김서연(EMP-1001)에게 네 건의 문의가 있다. (design/ITssue-Prototype.html 의 사이드바 최근 문의와 같은 상태)
 * 다른 계정은 빈 목록으로 시작한다.
 */
import type { ChatBlock, Draft, Ticket } from '../chatTypes'
import { daysAgoIso } from '../../core/format'
import { GUIDES, groupOf, toSource } from './chatEngine'
import { cancelTimers, clearRecords, createRecord, notify, push, resetSeq } from './chatStore'

const p = (text: string): ChatBlock => ({ type: 'p', text })

/** 모든 문의와 번호·예약 작업을 처음 상태로 되돌린다 (새로고침과 같은 효과, 테스트에서도 사용) */
export function resetChatMock() {
  cancelTimers()
  clearRecords()
  resetSeq()
  seed()
  notify()
}

function seed() {
  const OWNER = 'EMP-1001'
  const NAME = '김서연'

  /* 문의 101: VPN 연결 문제로 접수된 뒤 담당자가 처리 중 (새 답변 1건) */
  {
    const { inquiry } = createRecord(OWNER, NAME, 'VPN 연결이 자주 끊겨요', 101)
    const g = GUIDES.NET
    const ticket: Ticket = {
      receiptNo: 'RCPT-1041',
      jiraKey: 'ITHD-1520',
      title: 'VPN·네트워크 지원 문의',
      categoryCode: 'NET',
      urgency: 'P3',
      ...groupOf('네트워크팀'),
      assigneeId: 2,
      assigneeName: '김담당',
      workStatus: 'WIP',
      assignStatus: 'ASSIGNED',
      jiraSyncStatus: 'SYNCED',
      createdAt: daysAgoIso(1),
      resolutionNote: '',
      needReply: false,
    }
    const draft: Draft = {
      title: ticket.title,
      categoryCode: 'NET',
      targetSystem: 'VPN·네트워크',
      summary: 'VPN 연결이 자주 끊겨요.',
      occurredAt: '어제부터요.',
      businessImpact: '저만 안 되고 메일 업무는 가능해요.',
      triedActions: '재접속과 재시작을 해봤어요.',
      aiSummary: `${g.guide} ${g.version} 안내 후에도 해결되지 않음`,
      urgency: 'P3',
      urgencyReasons: ['개인 업무 일부 지장, 대체 방법 있음'],
      ...groupOf('네트워크팀'),
    }
    push(inquiry, { role: 'user', text: 'VPN 연결이 자주 끊겨요' })
    push(inquiry, {
      role: 'assistant',
      blocks: [p('확인한 내용을 보면 **VPN·네트워크** 문의로 보여요. 먼저 아래 순서로 해 보세요.'), { type: 'ol', items: g.steps }, p('이 방법으로 해결되었나요?')],
      sources: [toSource(g)],
      replies: [
        { label: '해결', action: 'resolved', primary: true },
        { label: '미해결', action: 'unresolved' },
      ],
      locked: true,
    })
    push(inquiry, { role: 'user', text: '미해결' })
    push(inquiry, { role: 'user', text: '담당자 연결' })
    push(inquiry, { role: 'assistant', blocks: [p('지금까지 확인한 내용을 정리했어요. 맞는지 확인하고, 필요하면 수정해 주세요.')], card: 'draft' })
    push(inquiry, { role: 'user', text: '접수' })
    push(inquiry, { role: 'assistant', blocks: [p('접수되었어요. 접수번호는 **RCPT-1041** 입니다. 담당자 연결을 진행하고 있어요. 진행 상황은 아래 카드에서 바로 볼 수 있어요.')], card: 'ticket' })
    push(inquiry, { role: 'staff', from: '김담당 담당자', groupName: '네트워크팀', kind: '처리 안내', createdAt: daysAgoIso(1), text: 'VPN 서버 쪽 인증 정보를 확인하고 있어요. 곧 결과를 알려 드릴게요.' })
    inquiry.status = 'HANDED_OFF'
    inquiry.step = 'submitted'
    inquiry.categoryCode = 'NET'
    inquiry.draft = draft
    inquiry.draftState = 'confirmed'
    inquiry.ticket = ticket
    inquiry.unread = 1
    inquiry.updatedAt = daysAgoIso(1)
    inquiry.createdAt = daysAgoIso(1)
  }

  /* 문의 102: AI 안내로 해결 */
  {
    const { inquiry } = createRecord(OWNER, NAME, '계정 잠금 해제 방법', 102)
    const g = GUIDES.ACC
    push(inquiry, { role: 'user', text: '계정 잠금 해제 방법' })
    push(inquiry, {
      role: 'assistant',
      blocks: [p('확인한 내용을 보면 **계정·로그인** 문의로 보여요. 먼저 아래 순서로 해 보세요.'), { type: 'ol', items: g.steps }, p('이 방법으로 해결되었나요?')],
      sources: [toSource(g)],
      replies: [
        { label: '해결', action: 'resolved', primary: true },
        { label: '미해결', action: 'unresolved' },
      ],
      locked: true,
    })
    push(inquiry, { role: 'user', text: '해결' })
    push(inquiry, { role: 'assistant', blocks: [p('다행이에요! 이 문의는 **AI 해결**로 기록했어요. 다른 문제가 생기면 새 문의를 시작해 주세요.')] })
    inquiry.status = 'AI_RESOLVED'
    inquiry.step = 'closed'
    inquiry.categoryCode = 'ACC'
    inquiry.updatedAt = daysAgoIso(3)
    inquiry.createdAt = daysAgoIso(3)
  }

  /* 문의 103: 응답이 없어 종료됨 (미확인 처리) */
  {
    const { inquiry } = createRecord(OWNER, NAME, 'VPN 인증서 갱신이 필요한가요', 103)
    const g = GUIDES.NET
    push(inquiry, { role: 'user', text: 'VPN 인증서 갱신이 필요한가요' })
    push(inquiry, {
      role: 'assistant',
      blocks: [p('확인한 내용을 보면 **VPN·네트워크** 문의로 보여요. 먼저 아래 순서로 해 보세요.'), { type: 'ol', items: g.steps }, p('이 방법으로 해결되었나요?')],
      sources: [toSource(g)],
      replies: [
        { label: '해결', action: 'resolved', primary: true },
        { label: '미해결', action: 'unresolved' },
      ],
      locked: true,
    })
    push(inquiry, { role: 'sys', text: '일정 시간 응답이 없어 상담을 종료했어요. 미확인 처리합니다.' })
    inquiry.status = 'UNCONFIRMED'
    inquiry.step = 'closed'
    inquiry.categoryCode = 'NET'
    inquiry.updatedAt = daysAgoIso(6)
    inquiry.createdAt = daysAgoIso(6)
  }

  /* 문의 104: 담당자 처리 후 해결 확인까지 끝난 문의 */
  {
    const { inquiry } = createRecord(OWNER, NAME, '노트북 화면 깜빡임', 104)
    const ticket: Ticket = {
      receiptNo: 'RCPT-1030',
      jiraKey: 'ITHD-1509',
      title: 'PC·주변기기 지원 문의',
      categoryCode: 'HW',
      urgency: 'P3',
      ...groupOf('엔드포인트지원팀'),
      assigneeId: 201,
      assigneeName: '문오리',
      workStatus: 'CLS',
      assignStatus: 'ASSIGNED',
      jiraSyncStatus: 'SYNCED',
      createdAt: daysAgoIso(8),
      resolutionNote: '디스플레이 드라이버를 다시 설치했습니다.',
      needReply: false,
    }
    push(inquiry, { role: 'user', text: '노트북 화면 깜빡임' })
    push(inquiry, { role: 'assistant', blocks: [p('접수되었어요. 접수번호는 **RCPT-1030** 입니다. 담당자 연결을 진행하고 있어요. 진행 상황은 아래 카드에서 바로 볼 수 있어요.')], card: 'ticket' })
    inquiry.status = 'HANDED_OFF'
    inquiry.step = 'submitted'
    inquiry.categoryCode = 'HW'
    inquiry.ticket = ticket
    inquiry.draftState = 'confirmed'
    inquiry.updatedAt = daysAgoIso(8)
    inquiry.createdAt = daysAgoIso(8)
  }
}

resetChatMock()
