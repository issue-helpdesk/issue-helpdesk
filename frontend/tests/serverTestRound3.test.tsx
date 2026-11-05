/**
 * 서버 테스트 3차: 같은 출처 합치기, AI 새 답변 표시(마지막 변경 시각), 문의자에게 내부 긴급도 사유 숨김.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import type { GuideSource } from '../src/api/chatTypes'
import { hasUnseenUpdate, markInquirySeen } from '../src/api/inquirySeen'
import { isRuleUrgencyReason } from '../src/api/urgencyReason'
import { uniqueSources } from '../src/ui/sourceGroups'

const src = (over: Partial<GuideSource> = {}): GuideSource => ({ docCode: 'IT-SW-001', title: '', version: '2', section: '2', excerpt: '', ...over })

describe('uniqueSources', () => {
  it('같은 문서·버전·위치는 하나로 합치고, 본문은 먼저 있는 것, 그림은 모아서 쓴다', () => {
    const out = uniqueSources([
      src(),
      src({ excerpt: '2 포털 접속', images: [{ key: 'SW/a.png', caption: '첫 화면' }] }),
      src({ images: [{ key: 'SW/a.png', caption: '첫 화면' }, { key: 'SW/b.png', caption: '검색' }] }),
      src({ section: '3.1' }),
      src({ docCode: 'IT-SW-002' }),
    ])
    expect(out.map((s) => `${s.docCode}|${s.section}`)).toEqual(['IT-SW-001|2', 'IT-SW-001|3.1', 'IT-SW-002|2'])
    expect(out[0].excerpt).toBe('2 포털 접속')
    expect(out[0].images).toEqual([{ key: 'SW/a.png', caption: '첫 화면' }, { key: 'SW/b.png', caption: '검색' }])
  })
})

describe('AI 새 답변 표시 (서버 알림이 없어 마지막 변경 시각으로)', () => {
  beforeEach(() => localStorage.clear())
  const at = (min: number) => new Date(Date.UTC(2026, 10, 5, 1, min)).toISOString()

  it('처음 보는 문의는 점 없이 기록만 하고, 그 뒤에 바뀌면 점을 켜며, 열어 보면 꺼진다', () => {
    expect(hasUnseenUpdate('EMP-1001', 7, at(0))).toBe(false) // 이 브라우저에서 처음
    expect(hasUnseenUpdate('EMP-1001', 7, at(0))).toBe(false) // 그대로
    expect(hasUnseenUpdate('EMP-1001', 7, at(5))).toBe(true) // AI 가 새로 답함
    markInquirySeen('EMP-1001', 7, at(5)) // 대화 화면에서 봄
    expect(hasUnseenUpdate('EMP-1001', 7, at(5))).toBe(false)
  })

  it('사용자별·문의별로 따로 기록한다', () => {
    hasUnseenUpdate('EMP-1001', 7, at(0))
    hasUnseenUpdate('EMP-1001', 8, at(0))
    markInquirySeen('EMP-1001', 7, at(9))
    expect(hasUnseenUpdate('EMP-1001', 8, at(9))).toBe(true)
    expect(hasUnseenUpdate('EMP-1003', 7, at(9))).toBe(false) // 다른 사용자는 처음 보는 것
  })
})

describe('문의자에게 숨기는 내부 긴급도 사유', () => {
  it('"세부 유형 … 기본 긴급도"만 규칙 사유로 보고, 사람이 쓴 사유와 빈 값은 아니다', () => {
    expect(isRuleUrgencyReason('세부 유형 NET-04 기본 긴급도')).toBe(true)
    expect(isRuleUrgencyReason('개인 업무 전면 중단 (재택 중 VPN 불가)')).toBe(false)
    expect(isRuleUrgencyReason('설치 요청이라 기본 긴급도 P4에서 시작해요.')).toBe(false)
    expect(isRuleUrgencyReason(null)).toBe(false)
  })
})
