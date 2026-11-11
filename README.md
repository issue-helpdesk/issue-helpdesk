# 사내 IT 장애·문의 대응 AI Agent (ITssue)

> 캡스톤 프로젝트
>
> 반복되는 IT 문의는 AI가 1차로 응대하고, 해결이 어려운 건은 담당자에게 티켓을 자동 생성·배정하는 헬프데스크 에이전트입니다.

## 목차

- [배경](#배경)
- [목표](#목표)
- [주요 기능](#주요-기능)
- [시스템 구성](#시스템-구성)
- [기술 스택](#기술-스택)
- [개발 환경 설정](#개발-환경-설정)
- [실행 구성 (Docker Compose)](#실행-구성-docker-compose)
- [테스트](#테스트)
- [문서](#문서)
- [팀원](#팀원)

## 배경

- 반복 문의(비밀번호 초기화, VPN 접속, 프린터 오류 등)와 장애 접수가 몰리면서 대응이 지연됩니다.
- 담당자가 단순 문의 처리에 시간을 쓰느라 실제 장애 대응이 늦어지고 업무 부담이 큽니다.

## 목표

1차 문의는 AI가 직접 응대하고, 장애 유형과 긴급도를 분류해 해결 가이드를 제시하거나 담당자에게 티켓을 자동 생성·배정합니다.

## 주요 기능

- **AI 상담**: 부족한 정보를 되묻고, 가이드 문서(RAG) → 과거 처리 이력 순으로 근거를 찾아 답변합니다. 긴급 징후가 보이면 바로 담당자 연결을 제안합니다.
- **분류·긴급도 판단**: 문의 유형(7개 분류·50개 시나리오)과 긴급도를 판단하고, 문의자가 확인·수정한 접수 초안으로 접수합니다.
- **Jira 연동**: 접수를 Jira 티켓으로 만들고 담당자를 자동 배정합니다(부재 일정 반영). 상태 변경은 웹훅과 주기 대조로 동기화합니다.
- **담당자·관리자 화면**: 처리할 문의 목록·상세·처리 결과 등록, 알림, 대시보드, 감사 로그.
- **가이드 관리**: 문서 업로드·버전 관리·현행 전환·FAQ, 해결 사례를 묶어 가이드 초안을 만드는 주간 분석.
- **민감정보 보호**: AI 호출과 로그에 들어가는 개인정보·비밀값을 가립니다.

## 시스템 구성

| 구성 요소 | 역할 | 위치 |
|---|---|---|
| Frontend | 문의자·담당자·관리자 화면 (Vercel 배포) | [frontend/](frontend/README.md) |
| Backend API | FastAPI, `/api/v1` 아래 인증·문의·접수·문서·FAQ·알림·대시보드 등 | [backend/app/](backend/app/main.py) |
| Jira worker | 접수 생성·배정·상태 전환 작업 실행, 웹훅 반영, 주기 대조 (2개 실행) | [backend/app/integrations/jira/worker.py](backend/app/integrations/jira/worker.py) |
| Guide worker | 해결 사례 가이드화 주간 분석 (월요일 00:00 KST, 서버 전용) | [backend/app/workers/guide_analysis.py](backend/app/workers/guide_analysis.py) |
| Database | PostgreSQL + pgvector. 로컬 개발은 공유 Supabase, 운영은 EC2 Docker | [docker-compose.db.yml](docker-compose.db.yml) |

## 기술 스택

| 구분 | 기술 |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic |
| Frontend | Node 24, React 19, TypeScript, Vite, React Router, Vitest |
| Database | PostgreSQL 17 + pgvector (로컬 Supabase / EC2 Docker 구성) |
| AI 흐름·모델 | LangGraph, Claude API (LLMPort·Adapter, 모델은 `LLM_MODEL`로 지정) |
| 검색 | 로컬 임베딩 BGE-M3 (1024차원, KURE-v1과 비교 후 선정), pgvector |
| 외부 연동 | Jira Software (REST API, 웹훅) |
| 실행 구성 | Docker Compose, Nginx, 별도 Jira worker·Guide worker |

## 개발 환경 설정

Python **3.12** 기준입니다. 패키지 관리는 [uv](https://docs.astral.sh/uv/)를 사용합니다.

### 1. uv 설치 (최초 한 번)

```bash
# macOS
brew install uv

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 패키지 설치

저장소 루트에서 실행합니다. `.venv` 가상환경이 자동으로 만들어집니다. Python 3.12가 없으면 uv가 함께 설치합니다.

```bash
# 기본 + 개발용(pytest, poe)
uv sync

# 임베딩 모델까지 (검색·적재 담당, 배포 서버만)
uv sync --extra embedding
```

> Linux에서는 `pyproject.toml` 설정에 따라 CPU 전용 torch가 설치됩니다. (GPU 판은 `.venv`가 약 5.7GB, CPU 판은 약 1.3GB)

명령은 `uv run`을 앞에 붙여 실행합니다. 가상환경을 활성화했다면 생략해도 됩니다.

```bash
uv run pytest
# 또는
.venv\Scripts\activate   # macOS: source .venv/bin/activate
```

패키지 추가·삭제는 `pip` 대신 `uv add <패키지>` / `uv remove <패키지>`로 합니다. `pyproject.toml`과 `uv.lock`이 함께 갱신되니 두 파일 모두 커밋하세요.

### 3. 환경 변수

`.env.example`을 `.env`로 복사하고 값을 채웁니다. 자세한 설명은 [.env.example](.env.example)의 주석을 봅니다.

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | DB 주소. 로컬은 Supabase Session pooler 주소 |
| `DB_POOL_SIZE` · `DB_MAX_OVERFLOW` | 개발 PC는 `1`·`3`, 서버는 지워서 기본값 사용 |
| `JWT_SECRET` | 32자 이상 무작위 값. 없거나 짧으면 API 서버가 시작되지 않음 |
| `REFRESH_COOKIE_SECURE` | 로컬 http 개발에서 Refresh 쿠키가 안 오가면 `false` |
| `JIRA_BASE_URL` · `JIRA_EMAIL` · `JIRA_API_TOKEN` | Jira 연동 계정 |
| `JIRA_WEBHOOK_SECRET` | Jira 웹훅 비밀값. 없으면 웹훅을 모두 401로 거절 |
| `LLM_API_KEY` · `LLM_MODEL` | Claude API 키와 모델 |
| `EMBEDDING_MODEL_DIR` · `EMBEDDING_PRELOAD` | 임베딩 모델 폴더(기본: 저장소 옆 `models/`), 시작 시 미리 열지 여부 |
| `ASK_MORE_*` · `AI_HISTORY_LIMIT` | AI 상담 추가 질문 한도, AI에 보낼 이전 대화 수 |

### 4. DB 연결 확인

```bash
uv run pytest tests/test_db_connection.py -v
```

`PASSED`가 나오면 연결된 것입니다.

> 로컬 개발은 팀 공유 DB를 사용합니다. 테이블 변경(마이그레이션)은 `backend/app/db/migrations/`에 있으며, 공유 DB 반영(`cd backend && uv run alembic upgrade head`)은 담당자와 맞춘 뒤 진행합니다. 운영 서버는 컨테이너를 올릴 때 `migrate` 서비스가 자동으로 실행합니다.

### 5. 백엔드 서버 실행

```bash
uv run poe dev
```

코드를 수정하면 서버가 자동으로 재시작됩니다. 실행 후 http://127.0.0.1:8000/docs 에서 API 문서를, http://127.0.0.1:8000/api/v1/health/live 에서 상태를 확인할 수 있습니다.

### 6. 작업 실행기 (필요할 때만)

접수 이후 Jira 생성·배정·상태 반영은 별도 실행기가 처리합니다. 공유 DB에 쌓인 작업을 실제 Jira로 보내므로 필요할 때만 띄웁니다.

```bash
# Jira worker: 한 번만 돌고 종료
uv run python backend/app/integrations/jira/worker.py --once

# Jira worker: 30초마다 반복
uv run python backend/app/integrations/jira/worker.py --interval 30 --limit 10
```

주간 가이드 분석(`app.workers.guide_analysis`)은 실제 Claude 호출과 DB 저장을 하므로 서버에서만 실행합니다.

### 7. 프론트엔드 실행

Node.js 24가 필요합니다. 기본값은 가짜 응답(mock)이며, 실제 백엔드에 붙이는 방법은 [frontend/README.md](frontend/README.md)와 `frontend/.env.example`을 봅니다.

```bash
cd frontend
npm install
cp .env.example .env.local   # 필요할 때만
npm run dev                  # http://localhost:5173 (/api 요청은 8000번으로 전달)
```

## 실행 구성 (Docker Compose)

저장소 루트에서 실행합니다. 각 파일 맨 위 주석에 준비물과 주의 사항이 있습니다.

| 파일 | 내용 |
|---|---|
| [docker-compose.yml](docker-compose.yml) | `backend`(8000) · `jira-worker`(2개) · `web`(Nginx, `COMPOSE_PROFILES=web`일 때만) |
| [docker-compose.db.yml](docker-compose.db.yml) | 운영 DB (pgvector/pg17). 앱과 따로 올리고 내림, 포트를 열지 않음 |
| [docker-compose.server.yml](docker-compose.server.yml) | EC2 전용. 도커 DB 네트워크 연결, `migrate`, `guide-worker`, 운영용 Jira 필드 매핑 |

```bash
# EC2: DB 먼저, 그다음 앱 (.env 의 COMPOSE_FILE 로 server 파일을 함께 읽음)
docker compose -f docker-compose.db.yml up -d
docker compose up -d --build
```

> `docker compose -f docker-compose.db.yml down -v`는 DB 데이터 볼륨까지 지웁니다.

## 테스트

```bash
# 백엔드 (저장소 루트)
uv run pytest
uv run pytest tests/test_inquiries.py -v   # 파일 하나만

# 프론트엔드
cd frontend
npm test            # Vitest (항상 mock으로 실행)
npm run typecheck
npm run lint
```

## 문서

### 기획·설계

| 문서 | 내용 |
|---|---|
| [프로젝트 기획서](docs/01.프로젝트_기획서.md) | 배경·목표·구현 범위 |
| [제품 정의서 (PRD)](docs/02.제품정의서(PRD).md) | 기능·정책·MVP 범위 |
| [요구사항 정의서 (SRS)](docs/03.요구사항정의서(SRS).md) | 기능·비기능 요구사항 |
| [시스템 설계서](docs/04.시스템_설계서.md) | 아키텍처·DB·API |
| [가상 기업 환경 정의서](docs/05.가상기업_환경정의서.md) | 조직·사용자·IT 환경 |
| [테이블 설계서](docs/06.테이블_설계서.md) | 테이블·컬럼·코드 값 |
| [API 설계서](docs/07.API_설계서.md) | API 목록·현행 구현 범위 |
| [AI 입출력 형식](docs/08.AI_입출력_형식.md) | AI 호출 입력·출력 형식 |
| [대화 상태 정의](docs/09.대화_상태_정의.md) | 상담 대화 상태와 전환 |
| [민감정보 정책](docs/10.민감정보_정책.md) | 개인정보·비밀값 처리 기준 |
| [Jira Ticket 담당자 배정 로직](docs/11.Jira_티켓_담당자_배정_로직.md) | 담당자 선정 기준·Jira 호출·확인 필요 사항 |
| [사용자 매뉴얼](docs/12.사용자_매뉴얼.md) | 문의자·담당자·관리자 화면 사용법·문제 해결 |

### API 명세 (영역별)

| 문서 | 내용 |
|---|---|
| [인증·사용자](docs/api/01.인증_사용자.md) | 로그인·토큰·계정 |
| [문의·상담](docs/api/02.문의_상담.md) | 문의 대화·접수 초안 |
| [접수·연동](docs/api/03.접수_연동.md) | 담당자 접수·Jira 연동 |
| [문서·FAQ](docs/api/04.문서_FAQ.md) | 가이드 문서·FAQ·해결 사례 가이드화 |
| [기준정보·운영](docs/api/05.기준정보_운영.md) | 기준 정보·부재 일정·알림·보안 감사·운영 |

### 모듈·기타

| 문서 | 내용 |
|---|---|
| [Jira 연동 상세](docs/integrations/jira/) | 생성·배정·상태 전환·worker·테스트 환경 |
| [Jira 연동 모듈](backend/app/integrations/jira/README.md) | 연동 코드 구성·필드 매핑 |
| [RAG 문서 처리](backend/app/rag/README.md) | 파싱·청크·임베딩·검색·적재·평가 |
| [프론트엔드](frontend/README.md) | 화면 구성·mock과 실제 API 전환 |
| [점검 기록](docs/reviews/) | 문서 정합성·화면·조회 점검 결과 |
| [Git 협업 가이드](docs/git-collaboration-guide.md) | 브랜치·커밋·PR 규칙 |
| [데이터셋 설명](dataset/README.md) | 데이터 파일과 코드 |

## 팀원

| 이름 | 역할 | 담당 업무 |
|---|---|---|
| 이민식 | 팀장 | **검색** · 임베딩 모델 비교·선정(BGE-M3), 사내 자료 검색, 열람 권한·전송 정책 필터, 근거 문장 선택 |
| 고나영 | 팀원 | **프론트** · 문의자·담당자·관리자 화면(React), 디자인 시안, 서버 API 연결, UI·UX 화면 작업 |
| 김태연 | 팀원 | **문서 처리·평가** · 가이드 파싱·청크·그림 연결·적재·검증, 해결 사례 가이드 초안, 검색·판단 평가 도구 |
| 김현나 | 팀원 | **AI 판단·정보 보호** · AI 판단 흐름 설계·구현(LangGraph, Claude), 민감정보 보호, 해결 사례 → 가이드 자동화 |
| 김현우 | 팀원 | **ITSM 연동** · Jira 티켓 생성, 담당자 배정·재배정·복구, 변경 알림·주기 동기화, 보안 신호 감지·관리자 알림 |
| 박민경 | 팀원 | **백엔드** · 서버·DB 구성, 로그인·권한, EC2 배포, 문의·접수·가이드·운영 API, 가이드화 API, 보안 알림 감지 |

---

> 본 프로젝트의 회사·조직·데이터는 모두 **가상 설정**입니다.
