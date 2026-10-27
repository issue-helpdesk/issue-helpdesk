/**
 * 환경 설정 (앱 전체에서 한 곳에서만 읽는다).
 *
 * `import.meta.env.VITE_*` 값은 빌드 시 브라우저 코드에 그대로 들어간다.
 * 따라서 API 키·비밀번호 같은 비밀 값은 절대 여기에 넣지 않는다. (SRS NFR-SEC-06)
 */

/**
 * 가짜 응답(mock) 사용 여부.
 * 백엔드 연동(3단계) 전까지는 기본값이 true 이고, 'false' 로 설정해야 실제 API 를 호출한다.
 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

/**
 * 로그인·인증(AU, US)만 따로 가짜 응답 여부를 정한다. 백엔드가 인증 API 부터 만들어져서, 인증은 실제 서버에 붙이고
 * 문의·FAQ 는 아직 가짜 응답으로 두는 기간이 있기 때문이다. 값이 없으면 `VITE_USE_MOCK` 을 따른다.
 */
export const USE_MOCK_AUTH = (import.meta.env.VITE_USE_MOCK_AUTH ?? import.meta.env.VITE_USE_MOCK) !== 'false'

/** API 서버 주소(버전 포함). 비워 두면 같은 출처의 /api/v1 로 호출하고, 개발 서버(Vite)가 FastAPI 로 넘겨 준다. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

/** 서비스데스크 안내 문구 (IT-STD-001). 연결 실패·계정 제한 안내에 쓴다. */
export const SERVICEDESK = '내선 1000 (평일 09:00~18:00)'
