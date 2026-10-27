# 사내 IT 장애·문의 대응 AI Agent

> 캡스톤 프로젝트
>
> 반복되는 IT 문의는 AI가 1차로 응대하고, 해결이 어려운 건은 담당자에게 티켓을 자동 생성·배정하는 헬프데스크 에이전트입니다.

## 목차

- [배경](#배경)
- [목표](#목표)
- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [개발 환경 설정](#개발-환경-설정)
- [문서](#문서)
- [팀원](#팀원)

## 배경

- 반복 문의(비밀번호 초기화, VPN 접속, 프린터 오류 등)와 장애 접수가 몰리면서 대응이 지연됩니다.
- 담당자가 단순 문의 처리에 시간을 쓰느라 실제 장애 대응이 늦어지고 업무 부담이 큽니다.

## 목표

1차 문의는 AI가 직접 응대하고, 장애 유형과 긴급도를 분류해 해결 가이드를 제시하거나 담당자에게 티켓을 자동 생성·배정합니다.

## 주요 기능

- IT FAQ·장애 대응 매뉴얼 기반 답변 (RAG)
- 문의 유형 및 긴급도 자동 분류
- 과거 유사 장애 이력 검색 및 조치 방법 제안
- 해결 불가 시 티켓 자동 생성 및 담당자 배정 (모의 티켓 시스템)
- 문의·장애 처리 현황 대시보드

## 기술 스택

| 구분 | 기술 |
|---|---|
| Backend | Python 3.12, FastAPI |
| Frontend | Streamlit |
| Database | PostgreSQL (Supabase), pgvector |
| LLM | Claude |

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
# 기본 + 개발용(pytest)
uv sync

# 임베딩 모델까지 (검색·적재 담당, 배포 서버만)
uv sync --extra embedding
```

> Linux 서버에서 임베딩을 설치할 때는 CPU 전용 torch를 먼저 설치합니다.
> `uv pip install torch --index-url https://download.pytorch.org/whl/cpu`

명령은 `uv run`을 앞에 붙여 실행합니다. 가상환경을 활성화했다면 생략해도 됩니다.

```bash
uv run pytest
# 또는
.venv\Scripts\activate   # macOS: source .venv/bin/activate
```

패키지 추가·삭제는 `pip` 대신 `uv add <패키지>` / `uv remove <패키지>`로 합니다. `pyproject.toml`과 `uv.lock`이 함께 갱신되니 두 파일 모두 커밋하세요.

### 3. 환경 변수

`.env.example`을 `.env`로 복사하고 `DATABASE_URL`을 채웁니다.

### 4. DB 연결 확인

```bash
uv run pytest tests/test_db_connection.py -v
```

`PASSED`가 나오면 연결된 것입니다.

## 문서

| 문서 | 내용 |
|---|---|
| [프로젝트 기획서](docs/01.프로젝트_기획서.md) | 배경·목표·구현 범위 |
| [제품 정의서 (PRD)](docs/02.제품정의서(PRD).md) | 기능·정책·MVP 범위 |
| [요구사항 정의서 (SRS)](docs/03.요구사항정의서(SRS).md) | 기능·비기능 요구사항 |
| [시스템 설계서](docs/04.시스템_설계서.md) | 아키텍처·DB·API |
| [가상 기업 환경 정의서](docs/05.가상기업_환경정의서.md) | 조직·사용자·IT 환경 |
| [Jira Ticket 담당자 배정 로직](docs/11.Jira_티켓_담당자_배정_로직.md) | 담당자 선정 기준·Jira 호출·확인 필요 사항 |
| [Git 협업 가이드](docs/git-collaboration-guide.md) | 브랜치·커밋·PR 규칙 |
| [데이터셋 설명](dataset/README.md) | 데이터 파일과 코드 |

## 팀원

| 이름 | 역할 |
|---|---|
| 이민식 | 팀장 |
| 고나영 | 팀원 |
| 김태연 | 팀원 |
| 김현나 | 팀원 |
| 김현우 | 팀원 |
| 박민경 | 팀원 |

---

> 본 프로젝트의 회사·조직·데이터는 모두 **가상 설정**입니다.