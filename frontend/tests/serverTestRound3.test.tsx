/**
 * 서버 테스트 3차: 같은 출처 합치기, AI 새 답변 표시(마지막 변경 시각), 문의자에게 내부 긴급도 사유 숨김.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import type { GuideSource } from '../src/api/chatTypes'
import { hasUnseenUpdate, markInquirySeen, markInquiryUnseen } from '../src/api/inquirySeen'
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

describe('AI 새 답변 표시 (서버 알림이 없어 마지막 AI 답변 ID로, R-45)', () => {
  beforeEach(() => localStorage.clear())

  it('처음 보는 문의는 점 없이 기록만 하고, 그 뒤에 새 AI 답변이 저장되면 점을 켜며, 열어 보면 꺼진다', () => {
    expect(hasUnseenUpdate('EMP-1001', 7, 501)).toBe(false) // 이 브라우저에서 처음
    expect(hasUnseenUpdate('EMP-1001', 7, 501)).toBe(false) // 그대로
    expect(hasUnseenUpdate('EMP-1001', 7, 512)).toBe(true) // AI 가 새로 답함
    markInquirySeen('EMP-1001', 7, 512) // 대화 화면에서 봄
    expect(hasUnseenUpdate('EMP-1001', 7, 512)).toBe(false)
  })

  it('AI 답변이 없는 문의(null)에는 점이 없고, 사용자 글·상태 변경처럼 값이 그대로면 켜지지 않는다', () => {
    expect(hasUnseenUpdate('EMP-1001', 9, null)).toBe(false)
    expect(hasUnseenUpdate('EMP-1001', 9, undefined)).toBe(false)
    markInquirySeen('EMP-1001', 9, 300)
    expect(hasUnseenUpdate('EMP-1001', 9, 300)).toBe(false)
    markInquirySeen('EMP-1001', 9, null) // 답변이 없으면 기록을 지우지 않는다
    expect(hasUnseenUpdate('EMP-1001', 9, 300)).toBe(false)
  })

  it('값의 크기가 아니라 같은지만 본다', () => {
    markInquirySeen('EMP-1001', 7, 600)
    expect(hasUnseenUpdate('EMP-1001', 7, 400)).toBe(true)
  })

  it('사용자별·문의별로 따로 기록한다', () => {
    hasUnseenUpdate('EMP-1001', 7, 100)
    hasUnseenUpdate('EMP-1001', 8, 100)
    markInquirySeen('EMP-1001', 7, 109)
    expect(hasUnseenUpdate('EMP-1001', 8, 109)).toBe(true)
    expect(hasUnseenUpdate('EMP-1003', 7, 109)).toBe(false) // 다른 사용자는 처음 보는 것
  })

  it('이 브라우저에서 보낸 문의의 답이 문의 화면을 떠나 있는 동안 오면, 처음 보는 문의여도 점이 켜진다', () => {
    markInquiryUnseen('EMP-1001', 15) // 대기 화면을 떠난 뒤 답이 도착
    expect(hasUnseenUpdate('EMP-1001', 15, 530)).toBe(true)
    markInquirySeen('EMP-1001', 15, 530) // 열어서 확인
    expect(hasUnseenUpdate('EMP-1001', 15, 530)).toBe(false)
  })

  it('이미 확인한 기록이 있는 문의는 "아직 안 봄"으로 덮어쓰지 않는다', () => {
    markInquirySeen('EMP-1001', 16, 520)
    markInquiryUnseen('EMP-1001', 16)
    expect(hasUnseenUpdate('EMP-1001', 16, 520)).toBe(false)
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
