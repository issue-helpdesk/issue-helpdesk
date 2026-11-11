/**
 * 가이드 본문 미리보기: 마크다운 표시(###, -, 1.)가 그대로 드러나지 않고, 한 줄로 이어진 본문도 나뉘어 보인다.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { askPreLogin } from '../src/api/consult'
import { ConsultPanel } from '../src/views/login/ConsultPanel'
import { Markdown } from '../src/ui/Markdown'
import { restoreBreaks } from '../src/ui/markdownText'

// 서버에서 받은 본문 그대로 (줄바꿈이 모두 공백으로 이어져 있다)
const FLAT =
  'VPN 접속 장애 대응 가이드 > 3. 증상별 조치 방법 > 3.3 집에서 VPN이 자주 끊김 ### 이런 경우 - 집에서 VPN을 연결하고 회의를 하면 연결이 자꾸 끊깁니다. - 공유기를 재시작하고 인터넷을 확인했지만 VPN만 계속 끊깁니다. 화면 메시지: 없음 ### 원인 - 가정용 공유기와 VPN의 전송 단위(MTU) 설정이 맞지 않아 연결이 끊기는 경우입니다. ### 조치 방법 1. 가정용 공유기를 재시작하고, VPN 없이 인터넷이 안정적인지 확인합니다. 2. 그래도 VPN만 자주 끊기면 IT 헬프데스크에 문의합니다. 3. 조정이 끝났다는 안내를 받으면 VPN에 다시 연결해 회의로 확인합니다. ### 해결 확인 - VPN을 연결한 채 회의를 해도 연결이 끊기지 않으면 해결된 것입니다.'

describe('가이드 본문 마크다운', () => {
  it('한 줄로 이어진 본문도 제목·목록 앞에서 줄이 나뉜다', () => {
    const t = restoreBreaks(FLAT)
    expect(t.split('\n').filter((l) => l.startsWith('### ')).length).toBe(4)
    expect(t).toContain('\n- 집에서 VPN을 연결하고')
    expect(t).toContain('\n1. 가정용 공유기를 재시작하고')
    expect(t).toContain('\n3. 조정이 끝났다는 안내를')
  })

  it('제목은 제목으로, 항목은 목록으로 그리고 표시 문자는 보이지 않는다', () => {
    const { container } = render(<Markdown text={FLAT} />)
    expect(container.querySelectorAll('h4').length).toBe(4)
    expect(container.querySelectorAll('ul li').length).toBeGreaterThanOrEqual(4)
    expect(container.querySelectorAll('ol li').length).toBe(3)
    expect(container.textContent).not.toContain('###')
    expect(screen.getByRole('heading', { name: '조치 방법', level: 4 })).toBeInTheDocument()
  })

  it('원본 문서의 그림 표시는 경로 없이 그림 상자로 보이고, 같은 설명의 기울임 줄은 겹치지 않게 뺀다', () => {
    const alt = "그림 3.4-1. 안내 화면"
    const text = ["#### 조치 방법", "", "1. 확인합니다.", "", `![${alt}](../images/IT-ACS-001_3.4-1.png)`, "", `*${alt}*`, ""].join("\n")
    const { container } = render(<Markdown text={text} />)
    expect(container.textContent).not.toContain("../images")
    expect(container.textContent).not.toContain("![")
    expect(container.querySelectorAll(".fig").length).toBe(1)
    expect(screen.getByRole("img", { name: /^그림: 3\.4-1\./ })).toBeInTheDocument()
    expect(container.textContent?.match(/3\.4-1\./g)?.length).toBe(1) // 설명이 두 번 나오지 않는다
  })

  it('줄바꿈이 있는 본문은 그대로 두고, 굵게·코드는 요소로 그린다', () => {
    const { container } = render(<Markdown text={'## 제목\n- **굵게** 와 `코드`\n\n일반 문단'} />)
    expect(container.querySelector('h4')?.textContent).toBe('제목')
    expect(container.querySelector('li b')?.textContent).toBe('굵게')
    expect(container.querySelector('li code')?.textContent).toBe('코드')
    expect(container.querySelector('p')?.textContent).toBe('일반 문단')
  })

  it('HTML 은 해석하지 않는다', () => {
    const { container } = render(<Markdown text={'<img src=x onerror=alert(1)> **ok**'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('<img src=x')
  })
})

describe('표와 그림 표시', () => {
  it('| 로 나뉜 줄은 표로, [그림]·[표] 줄은 설명 상자로 그린다', () => {
    const md = ['### 값', '| 항목 | 값 |', '|---|---|', '| MTU | 1400 |', '| 포트 | 443 |', '[그림] 그림 3.3-1. VPN 클라이언트 홈 화면', '[표] 표 2. 포트 목록'].join('\n')
    const { container } = render(<Markdown text={md} />)
    expect(container.querySelectorAll('th').length).toBe(2)
    expect(container.querySelectorAll('tbody tr').length).toBe(2)
    expect(container.textContent).not.toContain('|---')
    const figs = container.querySelectorAll('.fig')
    expect(figs).toHaveLength(2)
    expect(figs[0].textContent).toContain('VPN 클라이언트 홈 화면')
    expect(figs[1].getAttribute('aria-label')).toBe('표: 표 2. 포트 목록')
  })
})

describe('로그인 화면 공개 도움말', () => {
  it('내부 가이드 미리보기 없이 답변의 강조 문구를 표시한다', async () => {
    const r = await askPreLogin('계정이 잠겼어요')
    expect(r.ok && r.data.sources).toEqual([])
    render(<ConsultPanel />)
    await userEvent.click(screen.getByRole('button', { name: '계정이 잠겼어요' }))
    const answer = await screen.findByText('10분 후 자동으로 해제')
    expect(answer.tagName).toBe('B')
    expect(screen.queryByRole('button', { name: /IT-ACC-/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
