/** 테스트 공통 설정: jest-dom 판정 추가, 테스트마다 화면·토큰 초기화 */
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import { resetMockState } from '../src/api/mock/accounts'
import { resetChatMock } from '../src/api/mock/chatMock'
import { mockConfig } from '../src/api/mock/chatStore'
import { resetStaffMock } from '../src/api/mock/staffTickets'
import { resetUsersMock } from '../src/api/mock/users'
import { tokenStore } from '../src/core/tokenStore'

beforeEach(() => {
  // 토큰은 메모리에도 있으므로 sessionStorage 와 함께 비운다
  tokenStore.clear()
  sessionStorage.clear()
  // 가상 계정의 잠금·실패 기록도 처음 상태로 되돌린다
  resetMockState()
  // 문의 저장소도 처음 상태로 되돌리고, 시연용 지연을 없애 테스트가 바로 끝나게 한다
  mockConfig.typingMs = 0
  mockConfig.pipelineScale = 0
  mockConfig.autoRun = false
  mockConfig.saveFail = false
  resetChatMock()
  resetStaffMock()
  resetUsersMock()
})

afterEach(() => {
  // 렌더링한 화면을 정리한다
  cleanup()
})
