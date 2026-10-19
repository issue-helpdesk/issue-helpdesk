/**
 * 앱 진입점.
 * 글꼴·스타일을 불러오고, 라우터와 로그인 상태(AuthProvider)로 App 을 감싸 화면에 붙인다.
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
import App from './App.tsx'
import { AuthProvider } from './core/session.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
