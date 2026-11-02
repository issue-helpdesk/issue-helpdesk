import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * 개발 서버·빌드·테스트 설정.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // 개발 중에는 /api 요청을 FastAPI로 넘겨 CORS 설정 없이도 호출할 수 있다. (서버 경로가 /api/v1 이라 그대로 넘긴다)
      // 같은 출처라서 Refresh Token 쿠키(SameSite=Strict)도 그대로 오간다.
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      // 테스트 파일은 src 밖의 tests 폴더에 둔다 (backend/tests 와 같은 방식)
      include: ['tests/**/*.test.{ts,tsx}'],
      setupFiles: ['./tests/setup.ts'],
      css: false,
      // 테스트는 항상 가짜 응답(mock)으로 실행한다.
      env: { VITE_USE_MOCK: 'true', VITE_USE_MOCK_AUTH: 'true', VITE_USE_MOCK_INQUIRY: 'true', VITE_USE_MOCK_TICKET: 'true', VITE_USE_MOCK_FAQ: 'true' },
    },
  }
})
