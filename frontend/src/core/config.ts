/**
 * 환경 설정 (앱 전체에서 한 곳에서만 읽는다).
 *
 * `import.meta.env.VITE_*` 값은 빌드 시 브라우저 코드에 그대로 들어간다.
 * 따라서 API 키·비밀번호 같은 비밀 값은 절대 여기에 넣지 않는다. (SRS NFR-SEC-06)
 */

/** 환경 변수 값이 비었거나 없으면 undefined (Docker 빌드 인자는 비어 있어도 변수가 생긴다) */
const raw = (v: string | undefined) => (v === undefined || v.trim() === '' ? undefined : v.trim())

/**
 * 가짜 응답(mock) 사용 여부의 기본값.
 * 백엔드 연동(3단계) 전까지는 true 이고, 'false' 로 설정해야 실제 API 를 호출한다.
 * 아래 영역별 변수가 없으면 이 값을 따른다. 영역별로 따로 켜고 끌 수 있어서 서버가 만들어진 순서대로 하나씩 연결해 볼 수 있다.
 */
export const USE_MOCK = raw(import.meta.env.VITE_USE_MOCK) !== 'false'

/** 영역별 값: 자기 변수가 있으면 그 값, 없으면 VITE_USE_MOCK 을 따른다 ('false' 일 때만 실제 서버) */
const area = (v: string | undefined) => (raw(v) ?? raw(import.meta.env.VITE_USE_MOCK)) !== 'false'

/** 로그인·인증·계정 관리 (AU, US, 부서 목록) */
export const USE_MOCK_AUTH = area(import.meta.env.VITE_USE_MOCK_AUTH)
/** 문의 대화·문의 목록, 접수 초안·최종 접수 (IQ, TK-01~04) */
export const USE_MOCK_INQUIRY = area(import.meta.env.VITE_USE_MOCK_INQUIRY)
/** 담당자 접수 목록·상세·업무 상태 변경·이력 (TK-05~08). 모의에서는 문의 저장소와 연결돼 있어서, 접수까지 서버로 확인하려면 INQUIRY 도 함께 서버로 둔다 */
export const USE_MOCK_TICKET = area(import.meta.env.VITE_USE_MOCK_TICKET)
/** 화면 알림: 담당자 배정·처리 완료 알림과 안 읽은 개수 (NT-01~04). 모의에서는 알림이 없다 */
export const USE_MOCK_NOTIFY = area(import.meta.env.VITE_USE_MOCK_NOTIFY)
/** FAQ (FQ) */
export const USE_MOCK_FAQ = area(import.meta.env.VITE_USE_MOCK_FAQ)
/** 가이드 관리: 문서 목록·버전·업로드·현행 전환·정책 변경 (DC-01·02·06·07·09) */
export const USE_MOCK_GUIDE = area(import.meta.env.VITE_USE_MOCK_GUIDE)
/** 운영 집계: AI 사용 현황 (OP-03). 서버가 구현하기 전에는 모의로 둔다 */
export const USE_MOCK_OPS = area(import.meta.env.VITE_USE_MOCK_OPS)

/**
 * 문의 서버 모드에서 접수(담당자 연결 → 초안 → 최종 접수)와 접수 이후 해결·미해결을 실제 서버로 보낼지.
 * 기본은 false(막아 둠): 접수를 만들면 공유 DB 에 접수와 ITSM 작업(JIRA_CREATE 등)이 남는데, 작업을 처리하는 실행기(worker)가
 * 서버에 떠 있지 않으면 끝나지 않고 쌓이기 때문이다. 실행기가 준비된 환경에서만 'true' 로 켠다. USE_MOCK_INQUIRY 가 true 이면 상관없다.
 */
export const SERVER_INTAKE = raw(import.meta.env.VITE_SERVER_INTAKE) === 'true'

/**
 * 서버에 API 가 아직 없는 기능(로그인 전 상담, 통계 집계)은 위 변수와 상관없이 항상 모의로 동작한다.
 * 서버에 만들어지면 이 값을 쓰는 곳을 영역별 변수로 바꾼다.
 */
export const MOCK_ONLY: boolean = true

/** API 서버 주소(버전 포함). 비워 두면 같은 출처의 /api/v1 로 호출하고, 개발 서버(Vite)가 FastAPI 로 넘겨 준다. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

/** 서비스데스크 안내 문구 (IT-STD-001). 연결 실패·계정 제한 안내에 쓴다. */
export const SERVICEDESK = '내선 1000 (평일 09:00~18:00)'
