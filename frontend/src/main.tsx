/**
 * 앱 진입점.
 * 글꼴·스타일을 불러오고, 라우터와 로그인 상태(AuthProvider)로 App 을 감싸 화면에 붙인다.
 * 테마 적용하고, HTML에서 화면을 넣을 자리를 찾은 후, 화면 이동과 로그인 상태 관리 기능 준비한다.
 */
/** 
 * StrictMode: 개발 중 잘못된 사용을 발견하도록 돕는 도구
 * createRoot: React 화면을 브라우저에 연결하는 함수
 * BrowserRouter: /login, /new 같은 주소에 따라 화면을 이동할 수 있게 하는 도구
*/
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

// 글꼴은 외부(Google Fonts)에서 받지 않고 패키지에 포함해 자체 제공한다. (Noto Sans KR · IBM Plex Mono: SIL OFL 1.1)
import '@fontsource/noto-sans-kr/korean-400.css'
import '@fontsource/noto-sans-kr/korean-500.css'
import '@fontsource/noto-sans-kr/korean-600.css'
import '@fontsource/noto-sans-kr/korean-700.css'
import '@fontsource/noto-sans-kr/latin-400.css'
import '@fontsource/noto-sans-kr/latin-500.css'
import '@fontsource/noto-sans-kr/latin-600.css'
import '@fontsource/noto-sans-kr/latin-700.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'

// 스타일: 디자인 토큰 → 기본 규칙 → 컴포넌트 규칙 순서로 불러온다
import './assets/tokens.css'
import './assets/base.css'
import './assets/components.css'
import './assets/layout.css'
import './assets/chat.css'

// 우리 프로젝트에서 작성한 코드. 전체 앱, 로그인 상태 관리, 테마 적용 기능을 가져온다.
import App from './App.tsx'
import { AuthProvider } from './core/session.tsx'
import { applyStoredTheme } from './core/theme.ts'

// 저장된 테마 설정을 적용하는 함수 실행. (화면 붙이기 전에 실행하기 위해 여기에 배치)
applyStoredTheme()

// 앱을 브라우저에 붙인다.
// StricMode - 개발중 추가 검사 / BrowserRouter-주소를 이용한 화면 이동, 
// AuthProvider - 로그인한 사용자와 로그인 상태 / App - 실제 앱 구성.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
