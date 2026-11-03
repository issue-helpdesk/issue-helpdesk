/**
 * 문의 상태의 화면 표시: 접수(진행의 시작)는 하늘색, 미연결 종료(끝난 문의)는 회색 보라 + 속이 빈 점으로 나눈다.
 * 예전에는 둘이 같은 색이라 사이드바 최근 문의에서 구분되지 않았다.
 */
import { describe, expect, it } from 'vitest'
import { stateView } from '../src/ui/stateStyle'

describe('stateView: 접수와 미연결 종료 구분', () => {
  it('접수는 하늘색(info) 채워진 점이다', () => {
    const v = stateView({ displayStatus: 'received', stateLabel: '접수', stateKind: 'received' })
    expect(v).toMatchObject({ label: '접수', tone: 'info' })
    expect(v.ring).toBeFalsy()
  })

  it('미연결 종료는 회색 보라(recv)에 속이 빈 점이다', () => {
    const v = stateView({ displayStatus: 'unresolved', stateLabel: '미연결 종료', stateKind: 'received' })
    expect(v).toMatchObject({ label: '미연결 종료', tone: 'recv', ring: true })
  })

  it('두 상태의 색 토큰은 서로 다르다', () => {
    const a = stateView({ displayStatus: 'received', stateLabel: '접수', stateKind: 'received' })
    const b = stateView({ displayStatus: 'unresolved', stateLabel: '미연결 종료', stateKind: 'received' })
    expect(a.tone).not.toBe(b.tone)
  })

  it('다른 상태의 색은 그대로다', () => {
    expect(stateView({ displayStatus: 'in_progress', stateLabel: '진행 중', stateKind: 'progress' }).tone).toBe('prog')
    expect(stateView({ displayStatus: 'resolved', stateLabel: '해결 완료', stateKind: 'resolved' }).tone).toBe('ok')
    expect(stateView({ displayStatus: 'ai_resolved', stateLabel: 'AI 해결', stateKind: 'ai' }).tone).toBe('ok')
  })
})
