# ITssue Frontend

ITssue HelpDesk 화면(React). 화면 구성은 `design/ITssue-Prototype.html`과 `design/ITssue 디자인 가이드.html`을 기준으로 하고, 백엔드(FastAPI)와는 API로만 연결합니다. (시스템 설계서 3장·9장)

## 시작하기

Node.js 24 LTS가 필요합니다. (`.nvmrc`, `package.json`의 `engines` 참고)

```bash
cd frontend
npm install
cp .env.example .env.local   # 필요할 때만. 기본값은 가짜 응답(mock)
npm run dev                  # http://localhost:5173
```

| 명령 | 설명 |
| --- | --- |
| `npm run dev` | 개발 서버 |
| `npm run build` | 타입 검사 후 운영 빌드 (`dist/`) |
| `npm run typecheck` | 타입 검사만 |
| `npm run lint` | oxlint |
| `npm test` | 단위·화면 테스트 (Vitest). 항상 mock으로 실행 |
| `npm run preview` | 빌드 결과 미리보기 |

## 현재 만든 화면

- `/login` 로그인 (사번 로그인 · SSO 탭 · 잠김·이용 제한 안내) + 로그인 전 상담 패널 *(제안 기능)*
  - 계정 상태는 정상 · 잠김 · 이용 제한입니다. 로그인 5회 실패 시 잠기고 10분 후 자동으로 풀립니다. 시연(mock)에서도 같은 규칙으로 동작합니다.
  - 회원가입 기능은 없습니다. 신규 입사자 계정은 관리자가 만들어 제공합니다.
- 문의자 화면 틀 (사이드바 + 본문). 담당자·관리자도 같은 틀을 쓰며 메뉴만 역할에 따라 더해집니다.
  - `/new` 새 문의: 챗봇 시작 화면 (인사말 · 입력창 · 분류 칩 · 추천 카드). 보내기 이후 대화 흐름은 다음 단계입니다.
  - `/faq` FAQ *(제안 기능)*: 열람 허용된 Guide 기반 목록, 열면 답변과 출처, "상담하기"로 새 문의에 질문을 채워 이동
  - 사이드바: 메뉴 · 최근 문의(확인하지 않은 답변 수) · 사용자 정보 · 로그아웃. 860px 이하에서는 메뉴 버튼으로 여닫습니다.
- `/list` 문의 내역 · `/chat/:id` 문의 대화 · `/queue` 처리할 문의 · `/dash` 대시보드는 자리표시입니다. 화면을 만들면서 교체합니다.

## mock과 실제 API

`VITE_USE_MOCK`이 `false`가 아니면 가짜 응답으로 동작합니다. 백엔드 연동(3단계) 전까지의 기본값입니다.

- 가짜 계정은 프로토타입과 같습니다(비밀번호 `demo`). 로그인 화면의 "시연용 바로 로그인" 버튼은 mock일 때만 보입니다.
- 연동할 때는 `src/api/`의 어댑터(`auth.ts`, `consult.ts`)만 고칩니다. 화면 코드는 건드리지 않습니다.
- 개발 중 `/api` 요청은 Vite가 `VITE_DEV_PROXY_TARGET`(기본 `http://localhost:8000`)으로 넘기므로 CORS 설정 없이도 호출할 수 있습니다. 브라우저에서 FastAPI를 직접 호출한다면 백엔드에서 CORS를 허용해야 합니다.

### API 계약 (제안 · 백엔드 담당 확정 필요)

응답은 성공 `{ "ok": true, "data": ... }`, 실패 `{ "ok": false, "error": { "code": "...", "message": "..." } }` 형식을 가정합니다. 인증은 `Authorization: Bearer <JWT>`입니다.

| 호출 | 요청 | 성공 `data` | 실패 `error.code` |
| --- | --- | --- | --- |
| `POST /auth/login` | `{ employeeId, password }` | `{ accessToken, user: { id, name, dept, role, status } }` | `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, `ACCOUNT_RESTRICTED` |
| `GET /users/me` | - | `user` | `UNAUTHORIZED` |
| `POST /public/consult` *(제안 기능)* | `{ message }` | `{ paragraphs: string[], source?: string }` | - |
| `GET /faqs` *(제안 기능)* | - | `Faq[]` (`id, category, question, answer, source`) | - |
| `GET /inquiries` | - | `InquirySummary[]` (`id, title, stateLabel, stateKind, unread, when`) | - |

- `role`은 `user` · `staff` · `admin`, `status`는 `정상` · `잠김` · `이용 제한`입니다. (DB 값과의 대응: 정상=`ACTIVE`, 잠김=`LOCKED`, 이용 제한=`INACTIVE`) 필드 이름(camelCase 여부)은 협의 후 어댑터에서 맞춥니다.
- 화면은 `error.message`를 그대로 보여 주므로 문구는 사용자가 읽을 수 있는 한국어로 내려 주세요.

### 토큰 보관

JWT는 메모리에 두고, 새로고침을 견디도록 `sessionStorage`에도 저장합니다(탭을 닫으면 사라짐). `localStorage`는 쓰지 않습니다. 화면의 접근 제한(`RequireAuth`)은 편의 기능이며, 실제 권한 검사는 백엔드가 합니다(SRS NFR-SEC-02).

## 폴더 구조

수업 참고 프로젝트(`hanwha-agent`)의 frontend 구조(`core` · `ui` · `views` · `assets`)를 React에 맞게 옮겼습니다.

```
frontend/
├─ index.html · package.json · vite.config.ts · .env.example · .nvmrc
├─ src/
│  ├─ main.tsx          진입점 (글꼴·스타일 로드, 라우터·로그인 상태로 감싸기)
│  ├─ App.tsx           최상위 컴포넌트
│  ├─ core/             앱의 뼈대
│  │  ├─ config.ts        환경 설정 (mock 여부, API 주소, 서비스데스크 안내)
│  │  ├─ apiClient.ts     API 호출 단일 진입점 (Bearer 토큰, 오류 형식 통일)
│  │  ├─ tokenStore.ts    토큰 보관 (메모리 + sessionStorage)
│  │  ├─ session.tsx      로그인 상태 (AuthProvider, useAuth)
│  │  ├─ roles.ts         역할별 첫 화면·이름
│  │  └─ router.tsx       경로 정의, 로그인 필요 영역
│  ├─ api/              백엔드 API 어댑터와 타입 (types.ts, auth.ts, consult.ts, mock/)
│  ├─ ui/               공통 UI 조각 (AppShell, Sidebar, Topbar, Composer, Logo, Icon, RichText …)
│  ├─ views/            화면 (login/, inquiry/, faq/, HomePlaceholder)
│  └─ assets/           tokens.css(디자인 토큰), base.css(기본 규칙), components.css(컴포넌트 규칙), layout.css(사이드바·본문 틀)
└─ tests/               Vitest 설정과 테스트 (backend/tests 와 같은 방식)
```

새 화면은 `views/`에 만들고 `core/router.tsx`에 경로를 추가합니다. 여러 화면이 함께 쓰는 조각은 `ui/`로 올립니다. 코드 주석은 한글로 답니다.

## 사용 라이브러리와 라이선스

설치한 라이브러리는 `package.json`에 범위, `package-lock.json`에 정확한 버전이 기록됩니다. `package-lock.json`은 반드시 함께 커밋합니다. 라이브러리를 추가하면 아래 표에도 한 줄을 추가해 주세요.

| 구분 | 라이브러리 | 버전(설치 시점) | 라이선스 | 용도 |
| --- | --- | --- | --- | --- |
| 실행 | react, react-dom | 19.3.1 | MIT | 화면 |
| 실행 | react-router-dom | 7.18.4 | MIT | 화면 이동 |
| 실행 | @fontsource/noto-sans-kr | 5.3.1 | OFL-1.1 | 본문 글꼴 (자체 제공, 외부 요청 없음) |
| 실행 | @fontsource/ibm-plex-mono | 5.3.0 | OFL-1.1 | 번호·식별자 글꼴 |
| 개발 | vite, @vitejs/plugin-react | 8.3.4 / 6.1.2 | MIT | 개발 서버·빌드 |
| 개발 | typescript | 6.0.3 | Apache-2.0 | 타입 검사 |
| 개발 | oxlint | 1.88.0 | MIT | 린트 |
| 개발 | vitest, jsdom | 5.0.5 / 30.1.3 | MIT | 테스트 |
| 개발 | @testing-library/react, user-event, jest-dom | 16.3.3 / 14.6.8 / 7.0.1 | MIT | 화면 테스트 |
| 개발 | @types/node, @types/react, @types/react-dom | - | MIT | 타입 정의 |

글꼴(OFL-1.1)은 사용·배포가 가능하며 글꼴 파일 자체를 단독으로 판매하는 것만 금지됩니다. 로고는 디자인 가이드의 가상 로고이며 실제 한화시스템 로고를 쓰지 않습니다.

## 환경 변수

`VITE_`로 시작하는 값은 브라우저에 그대로 노출됩니다. **API 키·비밀번호 같은 비밀 값은 넣지 않습니다.** (SRS NFR-SEC-06) `.env.example`을 참고하세요.
