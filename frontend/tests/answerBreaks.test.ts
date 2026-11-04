/**
 * 줄바꿈 없이 한 줄로 온 AI 답변의 "1) 2) 3)" 단계를 문장 단위 줄·번호 목록으로 보여 준다.
 */
import { describe, expect, it } from 'vitest'
import { breakInlineSteps, toBlocks } from '../src/api/inquiryServer'

const ONE_LINE =
  '포토샵은 유료 프로그램이라 소프트웨어 센터에서 라이선스 신청을 거쳐 설치해요. 1) 브라우저에서 portal.ict.example 에 회사 계정(사번)으로 로그인한 뒤 [소프트웨어 센터]를 누르세요. 2) 검색 칸에 \'photoshop\'을 입력하세요. 3) 오른쪽에 [설치 요청]이 보이면 눌러 라이선스를 신청하세요. 라이선스가 할당되면 설치할 수 있어요. 첫 실행 때는 회사 계정으로 로그인이 필요해요.'

describe('줄바꿈 없는 답변의 번호 단계', () => {
  it('한 줄로 온 답변은 앞 문장, 번호 목록, 뒤 문장으로 나뉜다', () => {
    const b = toBlocks(ONE_LINE)
    expect(b[0]).toEqual({ type: 'p', text: '포토샵은 유료 프로그램이라 소프트웨어 센터에서 라이선스 신청을 거쳐 설치해요.' })
    expect(b[1]).toMatchObject({ type: 'ol' })
    expect((b[1] as { items: string[] }).items).toHaveLength(3)
    expect((b[1] as { items: string[] }).items[0]).toContain('portal.ict.example 에 회사 계정(사번)으로')
    expect(b.slice(2).map((x) => (x as { text: string }).text)).toEqual(['라이선스가 할당되면 설치할 수 있어요.', '첫 실행 때는 회사 계정으로 로그인이 필요해요.'])
  })

  it('줄바꿈이 이미 있거나 번호 단계가 없는 답변은 그대로 둔다', () => {
    expect(breakInlineSteps('첫째 줄이에요.\n둘째 줄이에요. 1) 가 2) 나')).toBe('첫째 줄이에요.\n둘째 줄이에요. 1) 가 2) 나')
    expect(breakInlineSteps('안녕하세요. 도와드릴게요. 예) 이렇게요.')).toBe('안녕하세요. 도와드릴게요. 예) 이렇게요.')
    expect(breakInlineSteps('1) 하나만 있어요. 끝이에요.')).toBe('1) 하나만 있어요. 끝이에요.')
  })
})
